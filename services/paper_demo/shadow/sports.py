"""Late-game favorites require fresh live status, never merely market close."""
import asyncio,json,time,math
from uuid import uuid4
from .runner import ts
from .discovery_budget import candidate_markets,next_profile,CATEGORY_LIMITS
from .storage import put
from services.research.reports import SERIES

NAMES={'KXNBAGAME':'NBA','KXNFLGAME':'NFL','KXNHLGAME':'NHL','KXMLBGAME':'MLB','KXNCAAFGAME':'College football','KXATPMATCH':'ATP tennis','KXWTAMATCH':'WTA tennis'}
def sports_profiles():
    return [dict(id='fav_'+s.lower(),series=s,name='Sports · '+NAMES.get(s,s),asset='sports',contracts=10,
        folder_id='favorites',strategy='favorites',version='favorites-sports-1',late_game_hours=2) for s in sorted(SERIES['sports'])]

def initialize_sports(store,guard):
    if store.get('shadow/sports-layout'):return
    guard();now=time.time()
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(73820193,))
        if c.execute("SELECT 1 FROM research_job WHERE idempotency_key='demo/shadow/sports-layout'").fetchone():return
        old=c.execute("SELECT progress FROM research_job WHERE idempotency_key='demo/shadow/bot/fav_btc'").fetchone()
        for p in sports_profiles():
            key='demo/shadow/bot/'+p['id']
            if not c.execute('SELECT 1 FROM research_job WHERE idempotency_key=%s',(key,)).fetchone():
                put(c,key,dict(p,key=str(uuid4()),revision=1,changed_at=now),dict(desired=old['progress'].get('desired','running') if old else 'running'))
        description='Tests 70–95¢ favorites in 15-minute markets, hourly/daily weather, and live sports in the final two hours before estimated game end. Favorite bias remains a hypothesis.'
        c.execute("UPDATE research_job SET parameters=jsonb_set(parameters,'{description}',to_jsonb(%s::text)) WHERE idempotency_key='demo/shadow/folder/favorites'",(description,))
        put(c,'demo/shadow/sports-layout',{},dict(at=now,bots=len(sports_profiles()),late_game_hours=2))
    print(json.dumps(dict(event='paper_sports_initialized',bots=len(sports_profiles()),late_game_hours=2,real_orders_enabled=False)),flush=True)

def stamp(value):
    if isinstance(value,(int,float)):return float(value)
    if not isinstance(value,str):raise ValueError('Missing game time')
    return ts(value)

def expected_end(raw):
    try:
        end=stamp(raw['expected_expiration_time']);close=stamp(raw['close_time'])
        return end if math.isfinite(end) and 0<end<=close else None
    except (KeyError,TypeError,ValueError):return None

def live_gate(raw,milestone,live,now,late_hours=2):
    """The final two scheduled hours are an estimate, not a known game clock."""
    try:
        event=raw['event_ticker'];mid=milestone['id'];d=live['live_data']['details']
        start=stamp(milestone['start_date']);end=expected_end(raw)
        at=d.get('last_updated_ts')
        if isinstance(at,str) and not at.replace('.','',1).isdigit():at=ts(at)
        else:at=float(at)
        if at>1e12:at/=1000
        linked=event in set(milestone.get('related_event_tickers',[])+milestone.get('primary_event_tickers',[]))
        fresh=math.isfinite(at) and -3<=now-at<=45
        live_now=(str(d.get('status','')).lower()=='live' and d.get('live_data_delayed') is not True
                  and d.get('result_pending') is not True and not d.get('winner'))
        valid=(linked and milestone.get('category')=='Sports' and live['live_data'].get('milestone_id')==mid
               and raw.get('status')=='active' and stamp(raw['close_time'])>now+60 and start<=now and end is not None and fresh and live_now
               and ((end-now<=86400) if late_hours is None else 60<end-now<=late_hours*3600))
        return dict(sports=True,milestone_id=mid,sports_start=start,sports_expected_end=end,
            sports_live=bool(valid),sports_verified_until=min(now+30,at+45) if valid else now,
            sports_status=d.get('status','unknown'),sports_checked_at=now)
    except (KeyError,TypeError,ValueError,OverflowError):
        return dict(sports=True,sports_live=False,sports_verified_until=now,sports_status='unverified',sports_checked_at=now)

async def sports_once(host):
    suite=host.experiments;now=time.time();markets=suite.feed_markets()
    # Update entry permissions even when the bot is paused or slots are full.
    for ticker,m in list(markets.items()):
        if not m.get('sports') or m.get('paid'):continue
        if now>=m['sports_expected_end'] or m.get('sports_status') in ('closed','finished','final'):
            raw=(await asyncio.to_thread(host.verified_data.call,'GET','/markets/'+ticker))['market']
            if raw.get('ticker')==ticker and raw.get('status') in ('settled','finalized') and raw.get('result') in ('yes','no'):
                await host.put('experiment_settlement',dict(ticker=ticker,result=raw['result'],status=raw['status']))
                continue
        try:
            live=await asyncio.to_thread(host.verified_data.call,'GET','/live_data/milestone/'+m['milestone_id'])
            raw=dict(event_ticker=m['event_ticker'],status='active',expected_expiration_time=m['sports_expected_end'],close_time=m['close'])
            milestone=dict(id=m['milestone_id'],start_date=m['sports_start'],category='Sports',related_event_tickers=[m['event_ticker']])
            gate=live_gate(raw,milestone,live,time.time(),late_hours=None)
        except Exception:gate=dict(sports_live=False,sports_verified_until=time.time(),sports_status='unverified')
        await host.put('sports_status',dict(ticker=ticker,gate=gate))
    active=candidate_markets(suite,markets,'sports',now)
    if len(active)>=CATEGORY_LIMITS['sports'] or not suite.extra_capacity(['sports-slot'],now):return
    choices=suite.enabled_profiles('sports')
    if not choices:return
    p,cursor=next_profile(suite,choices,active,suite.sports_cursor)
    if not p:return
    suite.sports_cursor=cursor
    result=await asyncio.to_thread(host.verified_data.call,'GET','/markets',dict(status='open',series_ticker=p['series'],limit=1000,cursor=suite.sports_pages.get(p['series'],'')))
    suite.sports_pages[p['series']]=result.get('cursor','')
    rows=[r for r in result.get('markets',[]) if r.get('ticker','').startswith(p['series']+'-') and r.get('status')=='active'
          and ts(r['open_time'])<=now and r['ticker'] not in markets and expected_end(r) is not None and -21600<expected_end(r)-now<=86400]
    seen=set()
    for raw in sorted(rows,key=lambda r:(expected_end(r),-float(r.get('volume_fp') or r.get('volume') or 0))):
        event=raw['event_ticker']
        if event in seen:continue
        seen.add(event)
        if len(seen)>2:break
        milestones=(await asyncio.to_thread(host.verified_data.call,'GET','/milestones',dict(related_event_ticker=event,limit=20)))['milestones']
        for milestone in milestones:
            if milestone.get('category')!='Sports':continue
            live=await asyncio.to_thread(host.verified_data.call,'GET','/live_data/milestone/'+milestone['id'])
            gate=live_gate(raw,milestone,live,time.time(),late_hours=None)
            if not gate['sports_live']:continue
            fee=await host.fee_policy(raw,{})
            await host.put('sports_market',dict(market=dict(ticker=raw['ticker'],event_ticker=event,series_ticker=p['series'],
                open=ts(raw['open_time']),close=ts(raw['close_time']),discovered_at=now,**gate),
                taker_multiplier=str(fee.taker_multiplier),maker_multiplier=str(fee.maker_multiplier)))
            return

async def discover_sports(host):
    while not host.done.is_set():
        try:await sports_once(host)
        except asyncio.CancelledError:raise
        except Exception as exc:print(json.dumps(dict(event='paper_sports_retry',error=type(exc).__name__,code=getattr(exc,'code',None),real_orders_enabled=False)),flush=True)
        await asyncio.sleep(10)
