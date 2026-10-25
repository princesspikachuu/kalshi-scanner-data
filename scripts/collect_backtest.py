#!/usr/bin/env python3
"""Manual historical research collector. Quotes are not confirmed maker fills."""
import argparse,csv,datetime as dt,json,time,urllib.parse,urllib.request,urllib.error,hashlib
from pathlib import Path
from collections import defaultdict
from execution_model import ATTEMPT_COLUMNS, simulate

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
    "KXLOWTMIA":("low_temperature","Miami"),
    "KXRAIN":("daily_rain","Multiple cities"),
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
def req(path,params):
    url=BASE+path+"?"+urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"KalshiPocketAnalytics/1.1","Accept":"application/json"}),timeout=40) as f:return json.load(f)
        except urllib.error.HTTPError as e:
            if e.code not in (429,500,502,503,504):raise
            print("HTTP",e.code,"retry",attempt+1,flush=True)
        time.sleep(3*2**attempt)
    raise RuntimeError("Historical API request failed: "+url)
def stamp(s):
    try:return int(dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp())
    except (AttributeError,ValueError):return None
def markets(series,start,end,archived):
    path="/historical/markets" if archived else "/markets"
    out=[]; cursor=""
    for page in range(25):
        q={"series_ticker":series,"limit":1000}
        if not archived:q.update({"min_close_ts":start-1,"max_close_ts":end})
        if cursor:q["cursor"]=cursor
        data=req(path,q)
        out += [m for m in data.get("markets",[]) if start <= (stamp(m.get("close_time")) or 0) < end and m.get("result") in ("yes","no")]
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
def run(asset,days_ago,cap):
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
    observations=[];failed=[];attempts=[]
    for market in sample:
        try:
            close=stamp(market.get("close_time"))
            if close is None:raise ValueError("Market missing close_time")
            bars=candles(market,archive,close-MAX_LOOKBACK_SECONDS[asset],close+60)
            kind,city=weather_metadata(market["series_ticker"])
            # Trade history is public, bounded to the sampled market ticker.
            # If unavailable, do not invent fill outcomes; keep legacy analysis.
            try:
                trades=[]; cursor=""
                for trade_page in range(20):
                    args={"ticker":market["ticker"],"limit":1000,
                          "min_ts":close-MAX_LOOKBACK_SECONDS[asset]-120,
                          "max_ts":close+60}
                    if cursor:args["cursor"]=cursor
                    page=req("/historical/trades" if archive else "/markets/trades",args)
                    trades.extend(page.get("trades",[]))
                    cursor=page.get("cursor") or ""
                    if not cursor:break
                if cursor:raise ValueError("Trade history truncated")
            except Exception as exc:
                print("Execution evidence unavailable:",market["ticker"],str(exc),flush=True)
                trades=None
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
            raise RuntimeError("No usable settled markets/quotes for "+asset+" on "+str(day))
        print("No eligible one-day observations for",asset,str(day),flush=True)
    folder=Path("backtests")/({"weather":"weather_hourly","sports":"sports_game","crypto":"crypto15m",
        "weather_daily":"weather_daily","financial_daily":"financial_daily"}.get(asset,asset+"15m"))
    folder.mkdir(parents=True,exist_ok=True)
    output=folder/(str(day)+".csv")
    execution_file=folder/(str(day)+".execution.csv")
    with execution_file.open("w",newline="") as handle:
        writer=csv.writer(handle);writer.writerow(ATTEMPT_COLUMNS);writer.writerows(attempts)
    with output.open("w",newline="") as handle:
        writer=csv.writer(handle);writer.writerow(COLUMNS);writer.writerows(observations)
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
    if not 1<=a.days_ago<=30 or not 1<=a.max_markets<=300:raise SystemExit("out of bounds")
    run(a.asset,a.days_ago,a.max_markets)
