"""Completed round trips from durable parent-linked exchange order checks."""

def completed_pairs(pool, before=None, bot=None, ticker=None,version="full",versions=None):
    from .demo_versions import version_clause
    scope,args=version_clause(version,versions or {},"b.")
    with pool.connection() as c:
        rows = c.execute("""
            WITH sells AS (
                SELECT x.parameters->>'parent' AS parent,
                    coalesce(sum((x.progress->>'filled')::numeric),0) AS contracts,
                    coalesce(sum((x.progress->>'filled')::numeric*(x.parameters->>'price')::numeric),0) AS proceeds,
                    coalesce(sum((x.progress->>'fees')::numeric),0) AS fees,
                    count(*) FILTER (WHERE (x.progress->>'filled')::numeric>0) AS sell_count,
                    min(coalesce(x.parameters->>'bot','')) AS bot_min,max(coalesce(x.parameters->>'bot','')) AS bot_max,
                    min(coalesce(x.parameters->>'ticker','')) AS ticker_min,max(coalesce(x.parameters->>'ticker','')) AS ticker_max,
                    min(coalesce(x.parameters->>'side','')) AS side_min,max(coalesce(x.parameters->>'side','')) AS side_max
                FROM research_job x
                WHERE x.idempotency_key>='demo/order/' AND x.idempotency_key<'demo/order/zzzz'
                    AND x.parameters->>'kind'='exit'
                GROUP BY x.parameters->>'parent'
            )
            SELECT b.id::text,b.parameters,b.progress,b.finished_at,s.contracts,s.proceeds,s.fees,s.sell_count
            FROM research_job b JOIN sells s ON s.parent=b.parameters->>'client_id'
            WHERE b.idempotency_key>='demo/order/' AND b.idempotency_key<'demo/order/zzzz'
                AND b.parameters->>'kind'='entry' AND b.progress->>'status'='closed'
                AND (b.progress->>'filled')::numeric>0
                AND coalesce((b.progress->>'remaining')::numeric,0)=0
                AND coalesce((b.progress->>'offset_quantity')::numeric,(b.parameters->>'offset_quantity')::numeric,0)=0
                AND s.bot_min=b.parameters->>'bot' AND s.bot_max=b.parameters->>'bot'
                AND s.ticker_min=b.parameters->>'ticker' AND s.ticker_max=b.parameters->>'ticker'
                AND s.side_min=b.parameters->>'side' AND s.side_max=b.parameters->>'side'
                AND s.contracts=(b.progress->>'filled')::numeric
                AND (%s::uuid IS NULL OR (b.finished_at,b.id)<(SELECT finished_at,id FROM research_job WHERE id=%s::uuid))
                AND (%s::text IS NULL OR b.parameters->>'bot'=%s)
                AND (%s::text IS NULL OR b.parameters->>'ticker'=%s)
            AND """+scope+""" ORDER BY b.finished_at DESC,b.id DESC LIMIT 51
        """, [before,before,bot,bot,ticker,ticker,*args]).fetchall()
    items=[]
    for row in rows[:50]:
        entry=dict(row['parameters'],**row['progress'])
        contracts=float(row['contracts']);proceeds=float(row['proceeds'])
        fees=float(row['fees'])+float(entry.get('fees',0))
        items.append(dict(id=row['id'],entry=entry,contracts=contracts,sell_count=row['sell_count'],
            sell_price=proceeds/contracts,fees=fees,
            estimated_net_cents=proceeds-contracts*entry['price']-fees,
            completed_at=entry.get('closed_at') or row['finished_at']))
    return dict(contract='demo-v1',items=items,next_before=rows[49]['id'] if len(rows)>50 else None)
