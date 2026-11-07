"""Compact minute balance history for deposit-adjusted folder returns."""
import json
from decimal import Decimal as D
from .storage import entry,put

PREFIX='demo/shadow/balance-history/'
WINDOWS={'1H':3600,'6H':21600,'24H':86400,'7D':604800,'30D':2592000}

def history_key(at):return PREFIX+f'{int(at//60):012d}'

def record_balances(store,accounts,now):
    folders=store.rows('shadow/folder/',10)
    samples={r['parameters']['id']:dict(session=r['progress']['session'],
        **{k:accounts[r['parameters']['id']]['portfolio'].get(k) for k in ('equity','cash','deposits','total_pnl')})
        for r in folders if r['parameters']['id'] in accounts}
    with store.pool.connection() as c:
        put(c,history_key(now),{},dict(at=now,folders=samples))
        for folder,sample in samples.items():
            if sample['equity'] is None:continue
            c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())
                ON CONFLICT(idempotency_key) DO NOTHING""",
                entry('demo/shadow/balance-origin/'+folder+'/'+sample['session'],{},dict(at=now,**sample)))
        if int(now//60)%60==0:
            c.execute('DELETE FROM research_job WHERE idempotency_key>=%s AND idempotency_key<%s',(PREFIX,history_key(now-35*86400)))

    print(json.dumps(dict(event='paper_folder_balances_sampled',at=now,folders=len(samples),real_orders_enabled=False)),flush=True)

def change(current,baseline):
    # Adding cash is not profit. A missing valuation is not a zero value.
    if not baseline or any(row.get(k) is None for row in (current,baseline) for k in ('equity','deposits')):return None
    return str(D(current['equity'])-D(baseline['equity'])-D(current['deposits'])+D(baseline['deposits']))

def folder_performance(pool,folders,now):
    with pool.connection() as c:
        baselines={}
        for period,seconds in WINDOWS.items():
            target=now-seconds
            row=c.execute("""SELECT progress FROM research_job WHERE idempotency_key>=%s AND idempotency_key<=%s
                AND (progress->>'at')::numeric<=%s ORDER BY idempotency_key DESC LIMIT 1""",(PREFIX,history_key(target),target)).fetchone()
            baselines[period]=row['progress'] if row else None
        for folder in folders:
            a=(folder.get('accounting') or {}).get('portfolio',{})
            origin=c.execute('SELECT progress FROM research_job WHERE idempotency_key=%s',
                ('demo/shadow/balance-origin/'+folder['id']+'/'+folder['session'],)).fetchone()
            origin=origin['progress'] if origin else None
            result={'all':dict(pnl=a.get('total_pnl'),partial=False,since=folder.get('reset_at'))}
            for period,seconds in WINDOWS.items():
                target=now-seconds;row=baselines[period];baseline=(row or {}).get('folders',{}).get(folder['id'])
                at=row.get('at') if row else None
                if not baseline or baseline.get('session')!=folder['session'] or baseline.get('equity') is None:
                    baseline=origin if origin and origin['at']>=target else None
                    at=baseline.get('at') if baseline else None
                partial=at is not None and at>target
                usable=at is not None and (partial or target-at<=120) and at<=now
                result[period]=dict(pnl=change(a,baseline) if usable else None,since=at,
                    partial=partial,approximate=True,missing_history=not usable)
            folder['performance']=result
