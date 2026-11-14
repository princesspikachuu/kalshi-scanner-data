"""Compressed per-minute bot P/L observations from worker and owner dashboard.

Financial snapshots include gap trades and all revisions. They are independent
of strategy evidence. No bot is assigned a fictitious slice of folder cash.
"""
import base64,gzip,json
from decimal import Decimal as D
from .performance import WINDOWS,equity_bounds,equity_estimate,period_change
from .storage import entry

PREFIX='demo/shadow/bot-performance-history/'
ORIGIN='demo/shadow/bot-performance-origin/'

def key(at):return PREFIX+f'{int(at//60):012d}'
def pack(value):return base64.b64encode(gzip.compress(json.dumps(value,separators=(',',':')).encode(),mtime=0)).decode()
def unpack(value):return json.loads(gzip.decompress(base64.b64decode(value)).decode())

def sample(account,positions,session):
    if not account or account.get('realized_pnl') is None or account.get('position_cost') is None:return None
    realized=D(account['realized_pnl']);cost=D(account['position_cost'])
    bounds=equity_bounds(dict(account,equity=account.get('total_pnl'),cash=str(realized-cost)),positions)
    if bounds is None:return None
    estimate=equity_estimate(dict(account,equity=account.get('total_pnl'),cash=str(realized-cost)),positions)
    return dict(session=session,equity_estimate=str(estimate) if estimate is not None else None,equity=str(bounds[0]) if bounds[0]==bounds[1] else None,
        equity_low=str(bounds[0]),equity_high=str(bounds[1]),deposits='0',realized_pnl=str(realized))

def samples_for(bots,folders,now,legacy_positions=()):
    sessions={f['id']:f for f in folders};current={}
    positions={}
    for p in legacy_positions:positions.setdefault(p.get('bot_id'),[]).append(p)
    for f in folders:
        for p in (f.get('accounting') or {}).get('positions',[]):positions.setdefault(p.get('bot_id'),[]).append(p)
    for b in bots:
        f=sessions.get(b.get('folder_id','convexity'))
        if not f or now<max(f.get('reset_at',0),f.get('created_at',0)):continue
        s=sample(b.get('account'),positions.get(b['id'],[]),f['session'])
        if s is not None:
            research=(b.get('experiment') or {}).get('scalper')
            if research:s['research']={k:v for k,v in research.get('totals',{}).items() if isinstance(v,(int,float)) or isinstance(v,dict)}
            current[b['id']]=s
    return current,sessions

def record(c,bots,current,sessions,now):
    # The first observation wins each minute, across concurrent requests.
    # Gzip keeps repeated zero/unchanged bot records compact as bots expand.
    if not current:return []
    payload=dict(at=now,bots=current)
    c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
        VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp()) ON CONFLICT(idempotency_key) DO NOTHING""",
        entry(key(now),{},dict(at=now,snapshot=pack(payload))))
    origin_keys=[]
    for folder,f in sessions.items():
        selected={b['id']:current[b['id']] for b in bots if b.get('folder_id','convexity')==folder and b['id'] in current}
        if not selected:continue
        origin=ORIGIN+folder+'/'+f['session'];origin_keys.append(origin)
        c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
            VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp()) ON CONFLICT(idempotency_key) DO NOTHING""",
            entry(origin,{},dict(at=now,snapshot=pack(dict(at=now,bots=selected)))))
    return origin_keys

def bot_performance(pool,bots,folders,now,legacy_positions=()):
    current,sessions=samples_for(bots,folders,now,legacy_positions)
    with pool.connection() as c:
        origin_keys=record(c,bots,current,sessions,now)
        origins={}
        if origin_keys:
            for row in c.execute('SELECT progress FROM research_job WHERE idempotency_key=ANY(%s)',(origin_keys,)).fetchall():
                p=unpack(row['progress']['snapshot'])
                for ident,value in p['bots'].items():origins[ident]=(p['at'],value)
        baselines={}
        for period,seconds in WINDOWS.items():
            target=now-seconds
            row=c.execute("""SELECT progress FROM research_job WHERE idempotency_key>=%s AND idempotency_key<=%s
                AND (progress->>'at')::numeric<=%s ORDER BY idempotency_key DESC LIMIT 1""",(PREFIX,key(target),target)).fetchone()
            baselines[period]=unpack(row['progress']['snapshot']) if row else None
    for b in bots:
        a=current.get(b['id']);result={}
        if a:
            result['all']=dict(pnl=a.get('equity_estimate',a['equity']),pnl_low=a['equity_low'],pnl_high=a['equity_high'],
                realized_pnl=a['realized_pnl'],partial=False,missing_history=False,since=None,unpriced=a['equity'] is None)
        for period,seconds in WINDOWS.items():
            target=now-seconds;p=baselines[period];baseline=(p or {}).get('bots',{}).get(b['id']);at=(p or {}).get('at')
            usable=baseline is not None and a is not None and baseline['session']==a['session'] and 0<=target-at<=120
            if not usable:
                at,baseline=origins.get(b['id'],(None,None))
                usable=a is not None and baseline is not None and baseline['session']==a['session'] and target<=at<=now
            result[period]=dict(**period_change(a or {},baseline if usable else None),since=at if usable else None,
                partial=bool(usable and at>target),missing_history=not usable,approximate=True)
        b['performance']=result
        research=(b.get('experiment') or {}).get('scalper')
        if research:
            reports={'all':research['totals']}
            for period in WINDOWS:
                baseline=(baselines.get(period) or {}).get('bots',{}).get(b['id'])
                if baseline is None or not a or baseline.get('session')!=a['session']:
                    baseline=origins.get(b['id'],(None,None))[1]
                old=(baseline or {}).get('research')
                reports[period]=research_delta(research['totals'],old) if old and not result[period]['missing_history'] else None
            research['periods']=reports

def record_bot_balances(store,accounts,experiments,now,legacy_positions=()):
    folders=[dict(r['parameters'],**r['progress'],accounting=accounts.get(r['parameters']['id'])) for r in store.rows('shadow/folder/',24)]
    reset=next((f.get('reset_at',0) for f in folders if f['id']=='convexity'),0)
    legacy=accounts.get('convexity') or {};cycles=legacy.get('current_cycles',{})
    bots=[]
    with store.pool.connection() as c:
        history=c.execute("""SELECT progress->>'bot_id' AS bot,
            coalesce(sum((progress->>'net_realized_pnl')::numeric),0)::text AS net
            FROM research_job WHERE idempotency_key>='demo/shadow/report/' AND idempotency_key<'demo/shadow/report/zzzz'
            AND NOT ((progress->>'ticker')=ANY(%s::text[])) AND (progress->>'at')::numeric>=%s
            AND (progress->>'at')::numeric<=%s GROUP BY progress->>'bot_id'""",(list(cycles),reset,now)).fetchall()
        net={r['bot']:D(r['net']) for r in history}
        for row in cycles.values():net[row['bot_id']]=net.get(row['bot_id'],D(0))+D(row['net_realized_pnl'])
        for folder,account in accounts.items():
            for ident,row in (account.get('bots') or {}).items():
                realized=net.get(ident,D(0)) if folder=='convexity' else D(experiments[folder]['bots'].get(ident,{}).get('net_realized_pnl','0'))
                total=str(realized+D(row['unrealized_pnl'])) if row.get('unrealized_pnl') is not None else None
                bots.append(dict(id=ident,folder_id=folder,experiment=experiments.get(folder,{}).get('bots',{}).get(ident),account=dict(row,realized_pnl=str(realized),total_pnl=total)))
        current,sessions=samples_for(bots,folders,now,legacy_positions)
        record(c,bots,current,sessions,now)

    print(json.dumps(dict(event='paper_bot_balances_sampled',at=now,bots=len(current),
        compressed_bytes=len(pack(dict(at=now,bots=current))),real_orders_enabled=False)),flush=True)


def research_delta(current,baseline):
    # Reuse existing minute snapshots; no additional read/write stream.
    counters=('maker_entry_orders_filled','maker_submitted','taker_submitted','spread_sum','spread_rounds','completed','wins','round_net','holding_seconds','fill_seconds','fill_events','opportunities','submitted','entry_orders_filled','entry_fills','exit_fills','maker_fills','taker_fills','maker_net','taker_net','partial_fills','canceled','repriced','missed','risk_rejected','economics_rejected','adverse_losses','settlement_carryovers','net','dollar_hours')
    r={k:current.get(k,0)-baseline.get(k,0) for k in counters}
    n=r['completed'];f=r['fill_events']
    r.update(maker_fill_rate=r['maker_entry_orders_filled']/r['maker_submitted'] if r['maker_submitted'] else None,average_spread=r['spread_sum']/r['spread_rounds'] if r['spread_rounds'] else None,win_rate=100*r['wins']/n if n else None,average_net=r['round_net']/n if n else None,average_holding_seconds=r['holding_seconds']/n if n else None,average_fill_seconds=r['fill_seconds']/f if f else None,execution_success=r['entry_orders_filled']/r['submitted'] if r['submitted'] else None,net_per_dollar_hour=r['net']/r['dollar_hours'] if r['dollar_hours'] else None)
    r['rejections']={k:v-baseline.get('rejections',{}).get(k,0) for k,v in current.get('rejections',{}).items() if v>baseline.get('rejections',{}).get(k,0)}
    return r
