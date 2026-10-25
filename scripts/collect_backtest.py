#!/usr/bin/env python3
"""Manual historical research collector. Quotes are not confirmed maker fills."""
import argparse,csv,datetime as dt,json,time,urllib.parse,urllib.request,urllib.error,hashlib
from pathlib import Path
from collections import defaultdict

BASE="https://external-api.kalshi.com/trade-api/v2"
SERIES={"btc":["KXBTC15M"],"eth":["KXETH15M"],"weather":["KXTEMPNYCH","KXTEMPCHIH","KXTEMPMIAH","KXTEMPLAH"]}
MINUTES={"btc":[10,5,3,1],"eth":[10,5,3,1],"weather":[15,10,5,3,1]}
COLUMNS=["date","asset","series","ticker","event_ticker","close_time","side","minutes_before_close","price_band","maker_bid","taker_ask","won","quote_age_seconds","roi_maker_zero","roi_maker_fee_stress","roi_taker","market_volume"]
SUM=["minutes_before_close","price_band","observations","unique_markets","unique_events","days_sampled","win_rate","mean_roi_no_fees_if_filled","mean_roi_maker_fee_stress","mean_roi_taker_if_filled","paired_observations","matched_maker_mean_roi","matched_taker_mean_roi","matched_maker_stake_weighted_roi","matched_taker_stake_weighted_roi","quote_coverage_rate","series"]
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
    for s in SERIES[asset]:
        rows=markets(s,start,end,archive);print(s,len(rows),"settled markets")
        for m in rows:m["series_ticker"]=s
        allm.extend(rows)
    # Distribute the sample over the entire day and across events.
    # The old implementation selected the earliest N markets and was time-biased.
    events=defaultdict(list)
    for m in allm:
        events[m.get("event_ticker") or m["ticker"]].append(m)
    event_keys=sorted(events,key=lambda k:(stamp(events[k][0].get("close_time")) or 0,k))
    selected_keys=event_keys
    if len(event_keys)>cap:
        selected_keys=[event_keys[int(i*len(event_keys)/cap)] for i in range(cap)]
    sample=[]
    offsets={}
    for key in selected_keys:
        group=sorted(events[key],key=lambda x:x["ticker"])
        offsets[key]=int.from_bytes(hashlib.sha256(key.encode()).digest()[:4],"big")%len(group)
        sample.append(group[offsets[key]])
    # If fewer events than our cap, rotate additional strikes between events.
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
    observations=[];failed=[];crossed_quotes=0
    for m in sample:
        try:
            close=stamp(m.get("close_time"));cs=candles(m,archive,close-1800,close+60)
            for mins in MINUTES[asset]:
                target=close-mins*60
                eligible=[c for c in cs if c.get("end_period_ts") is not None and 0<=target-int(c["end_period_ts"])<=120]
                if not eligible:continue
                c=max(eligible,key=lambda x:x["end_period_ts"])
                for side in ("yes","no"):
                    bid=val(c,side,"bid");ask=val(c,side,"ask")
                    # Some Kalshi candles provide only YES bid/ask. Derive NO from complementary executable quotes.
                    if side=="no":
                        if bid is None and val(c,"yes","ask") is not None:bid=1-val(c,"yes","ask")
                        if ask is None and val(c,"yes","bid") is not None:ask=1-val(c,"yes","bid")
                    if bid is None or not .5<=bid<1:continue
                    if ask is not None and ask<bid:
                        crossed_quotes+=1
                        ask=None
                    won=int(m["result"]==side);band=f"{int(bid*100)//10*10:02d}-{int(bid*100)//10*10+10:02d}"
                    observations.append([str(day),asset,m["series_ticker"],m["ticker"],m.get("event_ticker",""),m["close_time"],side,mins,band,round(bid,5),round(ask,5) if ask else "",won,target-int(c["end_period_ts"]),roi(bid,won,0),roi(bid,won,.0175),roi(ask,won,.07) if ask else "",m.get("volume_fp",m.get("volume",""))])
        except Exception as exc:
            failed.append({"ticker":m["ticker"],"error":str(exc)})
    if failed:raise RuntimeError("Aborting incomplete run; candle errors: "+json.dumps(failed[:5]))
    if not sample or not observations:raise RuntimeError("No usable settled markets/quotes for "+asset+" on "+str(day))
    folder=Path("backtests")/("weather_hourly" if asset=="weather" else asset+"15m");folder.mkdir(parents=True,exist_ok=True)
    f=folder/(str(day)+".csv")
    with f.open("w",newline="") as out:w=csv.writer(out);w.writerow(COLUMNS);w.writerows(observations)
    allrows=[]
    for path in folder.glob("????-??-??.csv"):
        with path.open(newline="") as infile:allrows.extend(csv.DictReader(infile))
    groups=defaultdict(list)
    for row in allrows:
        key=(int(row["minutes_before_close"]),row["price_band"])
        groups[key+("ALL",)].append(row)
        groups[key+(row["series"],)].append(row)
    with (folder/"summary.csv").open("w",newline="") as out:
        w=csv.writer(out);w.writerow(SUM)
        for (mins,band,series),rows in sorted(groups.items()):
            def mean(items,key):
                values=[float(r[key]) for r in items if r.get(key) not in ("",None)]
                return sum(values)/len(values) if values else ""
            paired=[r for r in rows if r.get("roi_taker") not in ("",None)
                    and r.get("taker_ask") not in ("",None)]
            def weighted(items,price_key,coef):
                costs=[float(r[price_key])*100+fee(float(r[price_key]),coef) for r in items]
                total=sum(costs)
                return (sum(100*int(r["won"]) for r in items)-total)/total if total else ""
            w.writerow([mins,band,len(rows),len(set(r["ticker"] for r in rows)),
                        len(set(r["event_ticker"] for r in rows)),len(set(r["date"] for r in rows)),
                        mean(rows,"won"),mean(rows,"roi_maker_zero"),
                        mean(rows,"roi_maker_fee_stress"),mean(paired,"roi_taker"),
                        len(paired),mean(paired,"roi_maker_zero"),mean(paired,"roi_taker"),
                        weighted(paired,"maker_bid",0),weighted(paired,"taker_ask",.07),
                        len(paired)/len(rows),series])
    (folder/"status.json").write_text(json.dumps({
        "asset":asset,"date":str(day),"markets_available":len(allm),"markets_sampled":len(sample),
        "sampling_truncated":len(allm)>len(sample),"observations":len(observations),
        "total_observations":len(allrows),"days_sampled":len(set(r["date"] for r in allrows)),
        "crossed_quotes_ignored":crossed_quotes,"historical_endpoint":archive,
        "updated_at":dt.datetime.now(dt.timezone.utc).isoformat()},indent=2))
    print("Saved",f,"observations",len(observations))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--asset",choices=SERIES,required=True);p.add_argument("--days-ago",type=int,default=2);p.add_argument("--max-markets",type=int,default=60);a=p.parse_args()
    if not 1<=a.days_ago<=30 or not 1<=a.max_markets<=300:raise SystemExit("out of bounds")
    run(a.asset,a.days_ago,a.max_markets)
