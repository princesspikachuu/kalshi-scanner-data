#!/usr/bin/env python3
"""Manual historical research collector. Quotes are not confirmed maker fills."""
import argparse,csv,datetime as dt,json,time,urllib.parse,urllib.request,urllib.error,hashlib,os
from pathlib import Path
from collections import defaultdict
from execution_model import ATTEMPT_COLUMNS, simulate
from loss_prevention import pack_path

BASE="https://external-api.kalshi.com/trade-api/v2"
# Hourly Weather Index (multi-station) and legacy single-station hourly contracts.
# No daily high/low or rainfall contracts.
WEATHER_SERIES={
    "KXTEMPNYCHS":("index","New York City"),
    "KXTEMPCHIHS":("index","Chicago"),
    "KXTEMPMIAH":("index","Miami"),
    "KXTEMPLAXHS":("index","Coastal Los Angeles"),
    "KXTEMPNYCH":("station","New York City"),
    "KXTEMPCHIH":("station","Chicago"),
    "KXTEMPLAH":("station","Los Angeles"),
    "KXTEMPDCH":("station","Washington DC"),
}
# Same 15-minute UP/DOWN settlement format; exclude 15m coin-race markets.
CRYPTO_SERIES={
    "KXBTC15M":"BTC", "KXETH15M":"ETH", "KXSOL15M":"SOL",
    "KXXRP15M":"XRP", "KXDOGE15M":"DOGE", "KXBNB15M":"BNB",
    "KXHYPE15M":"HYPE", "KXZEC15M":"ZEC", "KXNEAR15M":"NEAR",
}
# Sports game/match winners only. Do not pool spreads, totals or outrights.
SPORTS_SERIES={
    "KXNBAGAME":"NBA", "KXNFLGAME":"NFL", "KXNHLGAME":"NHL",
    "KXMLBGAME":"MLB", "KXNCAAFGAME":"NCAA Football",
    "KXATPMATCH":"ATP Tennis", "KXWTAMATCH":"WTA Tennis",
}
# Only one-calendar-day underlying outcomes. Excludes weekly/monthly
# economic releases, futures, and longer-horizon prediction contracts.
DAILY_WEATHER_SERIES={
    "KXHIGHNY":("high_temperature","New York City"),
    "KXHIGHCHI":("high_temperature","Chicago"),
    "KXHIGHLAX":("high_temperature","Los Angeles"),
    "KXHIGHMIA":("high_temperature","Miami"),
    "KXHIGHAUS":("high_temperature","Austin"),
    "KXHIGHDEN":("high_temperature","Denver"),
    "KXHIGHTEWR":("high_temperature","Newark"),
}
# Calendar-day equity index close only. Weekly/monthly price targets excluded.
DAILY_FINANCIAL_SERIES={
    "KXINX":"S&P 500 daily close",
    "KXNASDAQ100":"Nasdaq-100 daily close",
}
SERIES={"btc":["KXBTC15M"],"eth":["KXETH15M"],
        "crypto":list(CRYPTO_SERIES),"weather":list(WEATHER_SERIES),
        "sports":list(SPORTS_SERIES),
        "weather_daily":list(DAILY_WEATHER_SERIES),
        "financial_daily":list(DAILY_FINANCIAL_SERIES)}
MINUTES={"btc":[15,10,5,3,1],"eth":[15,10,5,3,1],
         "crypto":[15,10,5,3,1],"weather":[60,45,30,20,15,10,5,3,1],
         "sports":[360,180,120,60,30,15,5],
         "weather_daily":[360,180,120,60,30,15,5],
         "financial_daily":[360,180,120,60,30,15,5]}
MAX_LOOKBACK_SECONDS={asset:max(minutes)*60+120 for asset,minutes in MINUTES.items()}
COLUMNS=["date","asset","weather_type","city","series","ticker","event_ticker","close_time","side","minutes_before_close","price_band","maker_bid","won","quote_age_seconds","roi_maker_zero","roi_maker_fee_stress","market_volume"]
SUM=["weather_type","city","series","minutes_before_close","price_band","observations","unique_markets","unique_events","days_sampled","win_rate","mean_maker_bid_cents","maker_mean_roi_no_fee","maker_stake_weighted_roi_no_fee","maker_mean_roi_fee_stress","maker_stake_weighted_roi_fee_stress"]
def weather_metadata(series):
    # The historical CSV retains weather_type/city columns for compatibility.
    # For crypto/sports, they represent contract family and coin/league.
    if series in WEATHER_SERIES:return WEATHER_SERIES[series]
    if series in CRYPTO_SERIES:return ("crypto15m",CRYPTO_SERIES[series])
    if series in SPORTS_SERIES:return ("game_winner",SPORTS_SERIES[series])
    if series in DAILY_WEATHER_SERIES:return DAILY_WEATHER_SERIES[series]
    if series in DAILY_FINANCIAL_SERIES:return ("daily_index",DAILY_FINANCIAL_SERIES[series])
    return ("unknown","")
# Pace all requests, including optional evidence, below the public read ceiling.
_next_request = 0.0
REQUEST_INTERVAL = 0.25
REQUEST_TIMEOUT = 15
REQUEST_BUDGET = 40

def paced_open(request, timeout=REQUEST_TIMEOUT, deadline=None):
    global _next_request
    delay=max(0, _next_request-time.monotonic())
    if deadline is not None and time.monotonic()+delay >= deadline:
        raise TimeoutError("API request budget exhausted")
    if delay:time.sleep(delay)
    _next_request=time.monotonic()+REQUEST_INTERVAL
    if deadline is not None:timeout=min(timeout,max(.01,deadline-time.monotonic()))
    return urllib.request.urlopen(request,timeout=timeout)

def req(path,params):
    url=BASE+path+"?"+urllib.parse.urlencode(params)
    deadline=time.monotonic()+REQUEST_BUDGET
    for attempt in range(3):
        try:
            with paced_open(urllib.request.Request(url,headers={"User-Agent":"KalshiPocketAnalytics/1.2","Accept":"application/json"}),deadline=deadline) as f:
                return json.load(f)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504):raise
            last_error=exc
            print("HTTP",exc.code,"attempt",attempt+1,flush=True)
        except (urllib.error.URLError,TimeoutError) as exc:
            last_error=exc
        if attempt == 2:break
        delay=2*2**attempt
        if time.monotonic()+delay >= deadline:break
        time.sleep(delay)
    raise RuntimeError("Historical API request failed: "+url) from last_error
def stamp(s):
    try:return int(dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp())
    except (AttributeError,ValueError):return None
def archived_markets(series):
    """Load a complete archive index once per series per workflow, not per day.

    The historical listing accepts series/event/ticker filters, but no close
    date filter. Never silently stop at the old 25-page ceiling.
    """
    cache_dir=os.environ.get("POCKET_HISTORY_INDEX")
    cache=Path(cache_dir)/(series+".json") if cache_dir else None
    if cache and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    out=[];cursor="";seen=set()
    for page in range(1000):
        args={"series_ticker":series,"limit":1000}
        if cursor:args["cursor"]=cursor
        payload=req("/historical/markets",args)
        # Retain the fields needed for selection and analysis, not full rules.
        fields=("ticker","event_ticker","close_time","result","volume_fp","volume")
        out.extend({k:m[k] for k in fields if k in m} for m in payload.get("markets",[]))
        cursor=payload.get("cursor") or ""
        if page%10==0:print("Archive index",series,len(out),"markets loaded",flush=True)
        if not cursor:
            if cache:
                cache.parent.mkdir(parents=True,exist_ok=True)
                cache.write_text(json.dumps(out),encoding="utf-8")
            return out
        if cursor in seen:raise RuntimeError("Repeated archive cursor for "+series)
        seen.add(cursor)
    raise RuntimeError("Archive index exceeds safety limit for "+series+"; no partial dataset saved")

def markets(series,start,end,archived):
    def eligible(rows):
        return [m for m in rows if start <= (stamp(m.get("close_time")) or 0) < end and m.get("result") in ("yes","no")]
    if archived:return eligible(archived_markets(series))
    out=[];cursor=""
    for page in range(25):
        q={"series_ticker":series,"limit":1000,"min_close_ts":start-1,"max_close_ts":end}
        if cursor:q["cursor"]=cursor
        data=req("/markets",q)
        out.extend(eligible(data.get("markets",[])))
        cursor=data.get("cursor") or ""
        if not cursor:return out
    raise RuntimeError("Incomplete pagination for "+series)
def val(c,side,kind):
    b=c.get(side+"_"+kind) or {}
    x=b.get("close_dollars",b.get("close"))
    try:
        y=float(x)
        return y if 0<y<1 else None
    except (TypeError,ValueError):return None
def fee(p,coefficient):
    import math
    return math.ceil(coefficient*100*p*(1-p)*100)/100
def roi(p,win,coefficient):
    cost=100*p+fee(p,coefficient)
    return (100*win-cost)/cost if cost else None
def candles(m,archived,start,end):
    path=("/historical/markets/" if archived else "/series/"+m["series_ticker"]+"/markets/")+ (m["ticker"]+"/candlesticks" if archived else m["ticker"]+"/candlesticks")
    # Endpoint paths differ: recent /series/{series}/markets/{ticker}/candlesticks; archived /historical/markets/{ticker}/candlesticks
    if archived:path="/historical/markets/"+m["ticker"]+"/candlesticks"
    else:path="/series/"+m["series_ticker"]+"/markets/"+m["ticker"]+"/candlesticks"
    return req(path,{"start_ts":start,"end_ts":end,"period_interval":1}).get("candlesticks",[])
def candle_batches(sample, asset, archived):
    """Batch nearby recent markets; never accept silently missing batch entries."""
    ordered=sorted(sample,key=lambda m:stamp(m.get("close_time")) or 0)
    for offset in range(0,len(ordered),20):
        group=ordered[offset:offset+20]
        closes=[stamp(m.get("close_time")) for m in group]
        if any(c is None for c in closes):raise ValueError("Market missing close_time")
        start=min(closes)-MAX_LOOKBACK_SECONDS[asset]
        end=max(closes)+60
        # Stay below the endpoint's 10,000-candle response cap, even for
        # six-hour sports windows spread across a whole UTC day.
        safe=not archived and len(group)*((end-start)//60+2)<9500
        data={}
        if safe:
            try:
                payload=req("/markets/candlesticks",{
                    "market_tickers":",".join(m["ticker"] for m in group),
                    "start_ts":start,"end_ts":end,"period_interval":1})
                data={r["market_ticker"]:r["candlesticks"] for r in payload.get("markets",[])}
            except urllib.error.HTTPError as exc:
                if exc.code not in (400,404,422):raise
                print("Batch endpoint unavailable; using individual candles",flush=True)
        for market,close in zip(group,closes):
            bars=data.get(market["ticker"])
            # Empty batches may indicate candle migration; consult the usual
            # per-market endpoint instead of silently dropping observations.
            if not bars:bars=candles(market,archived,close-MAX_LOOKBACK_SECONDS[asset],close+60)
            yield market,bars

# Execution-evidence requests are strictly optional and must never stall the
# ordinary full-size backtest. One research day can contain up to 300 markets.
EXECUTION_MARKETS_PER_DAY = 60
EXECUTION_SECONDS_PER_DAY = 45
EXECUTION_TRADE_PAGES = 2

class OptionalTradeRateLimit(Exception):
    """Circuit breaker: stop optional trade history after a 429 for the day."""

def execution_sample_indices(total, limit=EXECUTION_MARKETS_PER_DAY):
    """Evenly distribute a capped execution subsample across selected markets."""
    if total <= 0 or limit <= 0:return set()
    count=min(total,limit)
    return {i*total//count for i in range(count)}

def quick_trade_history(market, archived, start, end, deadline=None):
    """Fail fast for optional execution evidence; NEVER treat truncated data as no fills."""
    out=[];cursor=""
    endpoint="/historical/trades" if archived else "/markets/trades"
    for _page in range(EXECUTION_TRADE_PAGES):
        args={"ticker":market["ticker"],"limit":1000,"min_ts":start,"max_ts":end}
        if cursor:args["cursor"]=cursor
        url=BASE+endpoint+"?"+urllib.parse.urlencode(args)
        request=urllib.request.Request(url,headers={
            "User-Agent":"KalshiPocketAnalytics/1.1","Accept":"application/json"})
        try:
            with paced_open(request,timeout=7,deadline=deadline) as handle:
                payload=json.load(handle)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise OptionalTradeRateLimit() from exc
            print("Execution evidence skipped:",market["ticker"],"HTTP",exc.code,flush=True)
            return None
        except (urllib.error.URLError,TimeoutError,ValueError) as exc:
            print("Execution evidence skipped:",market["ticker"],str(exc)[:160],flush=True)
            return None
        out.extend(payload.get("trades",[]))
        cursor=payload.get("cursor") or ""
        if not cursor:return out
    print("Execution evidence skipped: trade pagination truncated",market["ticker"],flush=True)
    return None

def run(asset,days_ago,cap):
    collection_started=time.monotonic()
    day=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=days_ago)).date()
    start=int(dt.datetime.combine(day,dt.time.min,dt.timezone.utc).timestamp());end=start+86400
    cutoff=req("/historical/cutoff",{})
    # Markets and candles can migrate separately; prefer historical when day is before market cutoff.
    market_cutoff=stamp(cutoff.get("market_settled_ts"))
    if market_cutoff is None:raise RuntimeError("Missing historical market cutoff")
    archive=end<=market_cutoff
    allm=[]
    unavailable_series=[]
    for series in SERIES[asset]:
        try:
            rows=markets(series,start,end,archive)
        except urllib.error.HTTPError as exc:
            if exc.code != 404: raise
            unavailable_series.append(series)
            print("Series unavailable (HTTP 404):",series,flush=True)
            continue
        print(series,len(rows),"settled markets",flush=True)
        for market in rows:market["series_ticker"]=series
        allm.extend(rows)
    # Stratify by series and event across the day. This prevents busy coins
    # or sports leagues from crowding out other subcategories.
    events=defaultdict(list)
    for market in allm:
        key=(market["series_ticker"],market.get("event_ticker") or market["ticker"])
        events[key].append(market)
    byseries=defaultdict(list)
    for key,group in events.items():
        byseries[key[0]].append(key)
    active=sorted(byseries)
    selected_keys=[]
    if active:
        for ix,series in enumerate(active):
            eventkeys=sorted(byseries[series],key=lambda k:(stamp(events[k][0].get("close_time")) or 0,k[1]))
            quota=cap//len(active)+(ix<cap%len(active))
            count=min(len(eventkeys),quota)
            for i in range(count):
                selected_keys.append(eventkeys[i*len(eventkeys)//count])
        if len(selected_keys)<cap:
            extra=[key for series in active for key in sorted(byseries[series])
                   if key not in selected_keys]
            extra.sort(key=lambda k:(stamp(events[k][0].get("close_time")) or 0,k))
            selected_keys+=extra[:cap-len(selected_keys)]
    sample=[]
    offsets={}
    for key in selected_keys:
        group=sorted(events[key],key=lambda x:x["ticker"])
        seed=key[0]+":"+key[1]
        offsets[key]=int.from_bytes(hashlib.sha256(seed.encode()).digest()[:4],"big")%len(group)
        sample.append(group[offsets[key]])
    # Extra strike thresholds if there are fewer events than the market cap.
    depth=1
    while len(sample)<cap:
        added=False
        for key in selected_keys:
            group=sorted(events[key],key=lambda x:x["ticker"])
            if depth>=len(group):continue
            sample.append(group[(offsets[key]+depth)%len(group)])
            added=True
            if len(sample)>=cap:break
        if not added:break
        depth+=1
    observations=[];failed=[];attempts=[];quote_paths={}
    execution_indices=execution_sample_indices(len(sample))
    execution_elapsed=0.0
    execution_checked=0
    execution_skipped=0
    execution_rate_limited=False
    trade_cutoff=stamp(cutoff.get("trades_created_ts"))
    for market_index,(market,bars) in enumerate(candle_batches(sample,asset,archive)):
        try:
            close=stamp(market.get("close_time"))
            if close is None:raise ValueError("Market missing close_time")
            quote_paths[market["ticker"]]=pack_path(bars,close)
            kind,city=weather_metadata(market["series_ticker"])
            # Full historical candle collection is unaffected by expensive
            # secondary trade-history analysis. Sample evenly and enforce a
            # strict per-day time budget, including API errors or rate limits.
            trades=None
            if not execution_rate_limited and market_index in execution_indices and (
                    execution_elapsed < EXECUTION_SECONDS_PER_DAY):
                # Don't query trades for markets with no usable post-only quote.
                has_candidate=False
                for mins in MINUTES[asset]:
                    target=close-mins*60
                    eligible=[c for c in bars if c.get("end_period_ts") is not None
                              and 0<=target-int(c["end_period_ts"])<=60]
                    if eligible:
                        from execution_model import best_quote
                        if best_quote(max(eligible,key=lambda x:x["end_period_ts"])) is not None:
                            has_candidate=True
                            break
                if has_candidate:
                    evidence_started=time.monotonic()
                    try:
                        trades=quick_trade_history(market,
                            archive if trade_cutoff is None else close+60<=trade_cutoff,
                            close-MAX_LOOKBACK_SECONDS[asset]-120,close+60,
                            deadline=evidence_started+EXECUTION_SECONDS_PER_DAY-execution_elapsed)
                    except OptionalTradeRateLimit:
                        execution_rate_limited=True
                        trades=None
                        print("Kalshi HTTP 429: pausing optional execution analysis for this UTC day.",flush=True)
                    finally:
                        execution_elapsed+=time.monotonic()-evidence_started
                    if trades is None:execution_skipped+=1
                    else:execution_checked+=1
            if market_index%25==0:
                print("Progress",asset,str(day),market_index+1,"of",len(sample),
                      "markets; execution checked",execution_checked,flush=True)
            for mins in MINUTES[asset]:
                target=close-mins*60
                eligible=[c for c in bars if c.get("end_period_ts") is not None
                          and 0<=target-int(c["end_period_ts"])<=120]
                if not eligible:continue
                candle=max(eligible,key=lambda x:x["end_period_ts"])
                if trades is not None:
                    attempts.extend(simulate(market,asset,str(day),mins,candle,trades,target,close))
                for side in ("yes","no"):
                    bid=val(candle,side,"bid")
                    if side=="no" and bid is None:
                        # Historical API expresses NO bid as 1 - YES ask.
                        yes_ask=val(candle,"yes","ask")
                        if yes_ask is not None:bid=1-yes_ask
                    if bid is None or not .50<=bid<1:continue
                    won=int(market["result"]==side)
                    ten=int(bid*100)//10*10
                    band=f"{ten:02d}-{ten+10:02d}"
                    observations.append([str(day),asset,kind,city,market["series_ticker"],
                         market["ticker"],market.get("event_ticker",""),
                         market["close_time"],side,mins,band,round(bid,5),won,
                         target-int(candle["end_period_ts"]),roi(bid,won,0),
                         roi(bid,won,.0175),market.get("volume_fp",market.get("volume",""))])
        except Exception as exc:
            failed.append({"ticker":market.get("ticker","?"),"error":str(exc)})
    if failed:raise RuntimeError("Aborting incomplete run; candle errors: "+json.dumps(failed[:5]))
    if not sample or not observations:
        if asset not in ("weather_daily","financial_daily"):
            raise RuntimeError("No usable settled markets/quotes for "+asset+" on "+str(day)+". This category may not have existed then, or Kalshi may not retain quotes for that date. Saved history is unchanged.")
        print("No eligible one-day observations for",asset,str(day),flush=True)
    folder=Path("backtests")/({"weather":"weather_hourly","sports":"sports_game","crypto":"crypto15m",
        "weather_daily":"weather_daily","financial_daily":"financial_daily"}.get(asset,asset+"15m"))
    folder.mkdir(parents=True,exist_ok=True)
    output=folder/(str(day)+".csv")
    execution_file=folder/(str(day)+".execution.csv")
    # Stage exactly this run's output BEFORE merging into cumulative history.
    # GitHub Actions gives each collection its own runner-local staging directory.
    stage_path=os.environ.get("POCKET_COLLECTION_STAGE")
    if stage_path:
        target=Path(stage_path)/asset
        target.mkdir(parents=True,exist_ok=True)
        (target/(str(day)+".paths.json")).write_text(json.dumps(quote_paths,separators=(",",":")),encoding="utf-8")
        with (target/(str(day)+".csv")).open("w",newline="") as handle:
            writer=csv.writer(handle);writer.writerow(COLUMNS);writer.writerows(observations)
        with (target/(str(day)+".execution.csv")).open("w",newline="") as handle:
            writer=csv.writer(handle);writer.writerow(ATTEMPT_COLUMNS);writer.writerows(attempts)
        (target/(str(day)+".status.json")).write_text(json.dumps({
            "date":str(day),"sampled_markets":len(sample),
            "sampled_observations":len(observations),
            "execution_attempts":len(attempts),
            "available_markets":len(allm)}),encoding="utf-8")

    path_file=folder/(str(day)+".paths.json")
    previous_paths=json.loads(path_file.read_text()) if path_file.exists() else {}
    previous_paths.update(quote_paths)
    path_file.write_text(json.dumps(previous_paths,separators=(",",":")),encoding="utf-8")

    def merge_day(path,columns,new_rows,key_columns):
        # A repeat sample of an old date must not delete previously saved markets.
        combined={}
        if path.exists():
            with path.open(newline="",encoding="utf-8") as handle:
                for previous in csv.DictReader(handle):
                    if previous.get("ticker"):
                        combined[tuple(str(previous.get(c,"")) for c in key_columns)]=previous
        for row in new_rows:
            record=dict(zip(columns,row))
            combined[tuple(str(record.get(c,"")) for c in key_columns)]=record
        with path.open("w",newline="",encoding="utf-8") as handle:
            writer=csv.DictWriter(handle,fieldnames=columns)
            writer.writeheader()
            writer.writerows(combined[k] for k in sorted(combined))
    merge_day(execution_file,ATTEMPT_COLUMNS,attempts,
              ("date","series","ticker","side","minutes_before_close","bid_offset_cents"))
    merge_day(output,COLUMNS,observations,
              ("date","series","ticker","side","minutes_before_close"))
    allrows=[]
    for dailyfile in sorted(folder.glob("????-??-??.csv")):
        with dailyfile.open(newline="") as handle:allrows.extend(csv.DictReader(handle))
    groups=defaultdict(list)
    for row in allrows:
        kind,city=weather_metadata(row["series"])
        kind=row.get("weather_type") or kind
        city=row.get("city") or city
        mins=int(row["minutes_before_close"]);band=row["price_band"]
        # Overall, by weather type, by city, and individual series.
        scopes=[("ALL","ALL","ALL"),(kind,"ALL","ALL"),
                (kind,city,"ALL"),(kind,city,row["series"])]
        for scope in set(scopes):groups[scope+(mins,band)].append(row)
    with (folder/"summary.csv").open("w",newline="") as handle:
        writer=csv.writer(handle);writer.writerow(SUM)
        for (kind,city,series,mins,band),rows in sorted(groups.items()):
            def mean(field):
                values=[float(row[field]) for row in rows if row.get(field) not in (None,"")]
                return sum(values)/len(values) if values else ""
            def weighted(coefficient):
                costs=[float(row["maker_bid"])*100+
                       fee(float(row["maker_bid"]),coefficient) for row in rows]
                invested=sum(costs)
                return (sum(100*int(row["won"]) for row in rows)-invested)/invested if invested else ""
            writer.writerow([kind,city,series,mins,band,len(rows),
                len(set(row["ticker"] for row in rows)),
                len(set(row["event_ticker"] for row in rows)),
                len(set(row["date"] for row in rows)),
                mean("won"),100*mean("maker_bid"),mean("roi_maker_zero"),
                weighted(0),mean("roi_maker_fee_stress"),weighted(.0175)])
    (folder/"status.json").write_text(json.dumps({
        "asset":asset,"date":str(day),"markets_available":len(allm),
        "markets_sampled":len(sample),"sampling_truncated":len(allm)>len(sample),
        "observations":len(observations),"total_observations":len(allrows),
        "execution_attempts":len(attempts),"execution_through_proxies":sum(row[15]=="trade_through" for row in attempts),
        "execution_markets_checked":execution_checked,
        "execution_markets_skipped":execution_skipped,
        "execution_rate_limited":execution_rate_limited,
        "execution_subsample_limit":EXECUTION_MARKETS_PER_DAY,
        "execution_time_budget_seconds":EXECUTION_SECONDS_PER_DAY,
        "execution_elapsed_seconds":round(execution_elapsed,2),
        "collection_elapsed_seconds":round(time.monotonic()-collection_started,2),
        "days_sampled":len(set(row["date"] for row in allrows)),
        "sampled_by_series":dict(sorted((series,sum(m["series_ticker"]==series for m in sample))
                                 for series in SERIES[asset])),
        "hourly_types":sorted(set(weather_metadata(m["series_ticker"])[0] for m in sample)),
        "sampled_subtypes":sorted(set(weather_metadata(m["series_ticker"])[1] for m in sample)),
        "requested_markets":cap,"markets_shortfall":max(0,cap-len(sample)),
        "unavailable_series":unavailable_series,
        "historical_endpoint":archive,
        "method":"simulated maker bid entry relative to listed close_time; fills not observed; sports close_time can differ from game end",
        "updated_at":dt.datetime.now(dt.timezone.utc).isoformat()},indent=2))
    print("Saved",output,"observations",len(observations))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--asset",choices=SERIES,required=True);p.add_argument("--days-ago",type=int,default=2);p.add_argument("--max-markets",type=int,default=60);a=p.parse_args()
    if not 1<=a.days_ago<=3650 or not 1<=a.max_markets<=300:raise SystemExit("out of bounds")
    run(a.asset,a.days_ago,a.max_markets)
