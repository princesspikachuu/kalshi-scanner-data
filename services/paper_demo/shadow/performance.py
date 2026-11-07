"""Compact minute balance history for deposit-adjusted folder returns."""
import json
from decimal import Decimal as D
from .storage import entry,put

PREFIX='demo/shadow/balance-history/'
WINDOWS={'1H':3600,'6H':21600,'24H':86400,'7D':604800,'30D':2592000}

def history_key(at):return PREFIX+f'{int(at//60):012d}'

def equity_bounds(row,positions=None):
    """Known cash plus priced positions; each unpriced contract is worth $0–$1."""
    def number(value):
        try:
            result=D(str(value))
            return result if result.is_finite() else None
        except Exception:return None
    exact=number(row.get('equity'))
    if exact is not None:return exact,exact
    low,high=number(row.get('equity_low')),number(row.get('equity_high'))
    if low is not None and high is not None and low<=high:return low,high
    cash=number(row.get('cash'))
    if cash is None or not any(k in row for k in ('active_contracts','pending_contracts')):return None
    quantity=sum((number(row.get(k,0)) or D(0) for k in ('active_contracts','pending_contracts')),D(0))
    if positions is not None:
        priced=[p for p in positions if number(p.get('value')) is not None]
        known=sum((number(p['value']) for p in priced),D(0))
        missing=max(D(0),quantity-sum((number(p.get('quantity')) or D(0) for p in priced),D(0)))
    else:
        known=D(0);missing=D(0)
        for kind in ('active','pending'):
            value=number(row.get(kind+'_value'))
            if value is None:missing+=number(row.get(kind+'_contracts')) or D(0)
            else:known+=value
    return cash+known,cash+known+missing

def balance_sample(account,session):
    row=account['portfolio'];bounds=equity_bounds(row,account.get('positions'))
    return dict(session=session,**{k:row.get(k) for k in ('equity','cash','deposits','total_pnl','realized_pnl')},
        equity_low=str(bounds[0]) if bounds else None,equity_high=str(bounds[1]) if bounds else None)

def record_balances(store,accounts,now):
    folders=store.rows('shadow/folder/',10)
    samples={r['parameters']['id']:balance_sample(accounts[r['parameters']['id']],r['progress']['session'])
        for r in folders if r['parameters']['id'] in accounts}
    with store.pool.connection() as c:
        put(c,history_key(now),{},dict(at=now,folders=samples))
        for folder,sample in samples.items():
            if equity_bounds(sample) is None:continue
            for prefix in ('balance-origin','balance-range-origin'):
                c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())
                ON CONFLICT(idempotency_key) DO NOTHING""",
                    entry('demo/shadow/'+prefix+'/'+folder+'/'+sample['session'],{},dict(at=now,**sample)))
        if int(now//60)%60==0:
            c.execute('DELETE FROM research_job WHERE idempotency_key>=%s AND idempotency_key<%s',(PREFIX,history_key(now-35*86400)))
            c.execute('DELETE FROM research_job WHERE idempotency_key>=%s AND idempotency_key<%s',('demo/shadow/bot-performance-history/','demo/shadow/bot-performance-history/'+f'{int((now-35*86400)//60):012d}'))

    print(json.dumps(dict(event='paper_folder_balances_sampled',at=now,folders=len(samples),bounded_folders=sum(equity_bounds(s) is not None for s in samples.values()),unpriced_folders=sum(s['equity'] is None and equity_bounds(s) is not None for s in samples.values()),real_orders_enabled=False)),flush=True)

def change(current,baseline):
    # Adding cash is not profit. A missing valuation is not a zero value.
    if not baseline or any(row.get(k) is None for row in (current,baseline) for k in ('equity','deposits')):return None
    return str(D(current['equity'])-D(baseline['equity'])-D(current['deposits'])+D(baseline['deposits']))

def period_change(current,baseline,positions=None):
    a=equity_bounds(current,positions);b=equity_bounds(baseline or {})
    if not a or not b or current.get('deposits') is None or baseline.get('deposits') is None:
        return dict(pnl=None,pnl_low=None,pnl_high=None,unpriced=False,realized_pnl=None)
    funds=D(current['deposits'])-D(baseline['deposits'])
    low,high=a[0]-b[1]-funds,a[1]-b[0]-funds
    realized=str(D(current['realized_pnl'])-D(baseline['realized_pnl'])) if all(r.get('realized_pnl') is not None for r in (current,baseline)) else None
    return dict(pnl=str(low) if low==high else None,pnl_low=str(low),pnl_high=str(high),unpriced=low!=high,realized_pnl=realized)

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
            origins=c.execute('SELECT progress FROM research_job WHERE idempotency_key=ANY(%s)',
                (['demo/shadow/'+p+'/'+folder['id']+'/'+folder['session'] for p in ('balance-origin','balance-range-origin')],)).fetchall()
            origins=sorted((r['progress'] for r in origins if equity_bounds(r['progress']) is not None),key=lambda r:r['at'])
            result={'all':dict(pnl=a.get('total_pnl'),partial=False,since=folder.get('reset_at'))}
            for period,seconds in WINDOWS.items():
                target=now-seconds;row=baselines[period];baseline=(row or {}).get('folders',{}).get(folder['id'])
                at=row.get('at') if row else None
                if not baseline or baseline.get('session')!=folder['session'] or equity_bounds(baseline) is None:
                    baseline=next((o for o in origins if target<=o['at']<=now),None)
                    at=baseline.get('at') if baseline else None
                partial=at is not None and at>target
                usable=at is not None and (partial or target-at<=120) and at<=now
                result[period]=dict(**period_change(a,baseline if usable else None,(folder.get('accounting') or {}).get('positions')),since=at,
                    partial=partial,approximate=True,missing_history=not usable)
            folder['performance']=result
