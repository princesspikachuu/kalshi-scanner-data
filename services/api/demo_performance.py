"""Bounded saved-order summaries; no exchange requests or history rewrites."""
import json
import time
from .demo_models import PERIOD_HOURS

TIME_BOUNDS=(1,3,5,10,15,20,30,45,60,120,180,360,1440)
AGGREGATES="""count(*) AS orders,
 count(*) FILTER (WHERE coalesce((progress->>'filled')::numeric,0)>0) AS filled_orders,
 coalesce(sum((progress->>'filled')::numeric),0) AS contracts,
 coalesce(sum(CASE WHEN progress->>'status'='resting' THEN (progress->>'remaining')::numeric ELSE 0 END),0) AS resting_contracts,
 coalesce(sum(CASE WHEN progress->>'status' NOT IN ('closed','rejected') AND NOT coalesce((progress->>'reset_closed')::boolean,false)
 THEN greatest(0,coalesce((progress->>'filled')::numeric,0)-coalesce((parameters->>'sold')::numeric,0)) ELSE 0 END),0) AS held_contracts,
 count(*) FILTER (WHERE progress ? 'realized_cents' AND progress->>'status'='closed') AS scored,
 count(*) FILTER (WHERE progress->>'status'='closed' AND (progress->>'realized_cents')::numeric>0) AS wins,
 sum((progress->>'realized_cents')::numeric) FILTER (WHERE progress->>'status'='closed') AS recorded_pnl_cents,
 count(*) FILTER (WHERE coalesce((progress->>'reset_closed')::boolean,false) AND NOT (progress ? 'realized_cents')) AS unscored_resets"""

def query_performance(pool,bot,identifier,group='square',period='all',timezone='America/Los_Angeles',start=None,end=None):
    from zoneinfo import ZoneInfo
    if group not in ('square','time','time_price','hour') or period not in ('all',*PERIOD_HOURS):raise ValueError('Invalid performance filters')
    tz=ZoneInfo(timezone)
    from datetime import date,datetime,time as midnight,timedelta
    first=date.fromisoformat(start) if start else None;last=date.fromisoformat(end) if end else None
    if first and last and last<first:raise ValueError('Invalid dates')
    lower=datetime.combine(first,midnight.min,tz).timestamp() if first else None
    upper=datetime.combine(last+timedelta(days=1),midnight.min,tz).timestamp() if last else None
    since=None if period=='all' else time.time()-PERIOD_HOURS[period]*3600
    sql="""WITH base AS (SELECT parameters,progress,
        coalesce((parameters->>'created_at')::numeric,extract(epoch FROM created_at)) AS entered_at
        FROM research_job WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz'
        AND parameters->>'kind'='entry' AND parameters->>'bot'=%s),
        selected AS (SELECT * FROM base WHERE (%s::numeric IS NULL OR entered_at>=%s) AND (%s::numeric IS NULL OR entered_at>=%s) AND (%s::numeric IS NULL OR entered_at<%s))"""
    args=[identifier,since,since,lower,lower,upper,upper]
    if group=='square':
        sql+=" SELECT parameters->'revision' AS revision,parameters->'square' AS square,parameters->'condition' AS condition,"+AGGREGATES+" FROM selected GROUP BY 1,2,3 ORDER BY 1 DESC,2,3 LIMIT 251"
    else:
        if group in ('time','time_price'):
            sql+=""", legacy AS (SELECT progress#>>'{details,client_id}' AS client_id,
                max(coalesce((progress#>>'{details,quote,entry_close}')::numeric,(progress#>>'{details,quote,close}')::numeric)) AS market_close
                FROM research_job WHERE idempotency_key>='demo/event/' AND idempotency_key<'demo/event/zzzz'
                AND parameters->>'bot'=%s AND parameters->>'kind'='order_intent'
                AND progress#>>'{details,client_id}' IN (SELECT parameters->>'client_id' FROM selected WHERE NOT(parameters ? 'market_close_at'))
                GROUP BY 1), timed AS (SELECT b.*, (coalesce((b.parameters->>'market_close_at')::numeric,l.market_close,
                  CASE WHEN b.parameters->>'entry_strategy' IS DISTINCT FROM 'buy_low_sell_high' THEN (b.parameters->>'close')::numeric
                  WHEN (b.parameters->>'revision')::integer=%s THEN (b.parameters->>'close')::numeric+%s END)-b.entered_at)/60 AS minutes
                FROM selected b LEFT JOIN legacy l ON l.client_id=b.parameters->>'client_id'),
                grouped AS (SELECT *,CASE WHEN minutes IS NULL THEN NULL WHEN minutes<=0 THEN 0 WHEN minutes>1440 THEN 1441
                    ELSE (SELECT min(bound) FROM unnest(%s::numeric[]) AS bound WHERE minutes<=bound) END AS bucket FROM timed)"""
            args.extend([identifier,bot['revision'] if group=='time' else -1,bot['config'].get('cycle_cutoff_minutes',0)*60,sorted(set(time_bounds(bot)+[1440])) if group=='time_price' else list(TIME_BOUNDS)])
        else:
            sql+=", grouped AS (SELECT *,extract(hour FROM to_timestamp(entered_at::double precision) AT TIME ZONE %s)::integer AS bucket FROM selected)"
            args.append(timezone)
        dimensions="bucket,(parameters->>'price')::numeric AS entry_price" if group=='time_price' else 'bucket'
        grouping='bucket,entry_price' if group=='time_price' else 'bucket'
        sql+=" SELECT "+dimensions+","+AGGREGATES+" FROM grouped GROUP BY "+grouping+" ORDER BY bucket NULLS LAST LIMIT 251"
    with pool.connection() as c:
        c.execute('SET LOCAL statement_timeout=5000')
        rows=c.execute(sql,args).fetchall()
    if group=='square':return performance_rows(bot,rows[:250]),len(rows)>250
    items=[]
    for raw in rows[:250]:
        row=dict(raw)
        for field in COUNTS:row[field]=float(row[field] or 0)
        row['recorded_pnl_cents']=float(row['recorded_pnl_cents']) if row['scored'] and row['recorded_pnl_cents'] is not None else None
        value=row['bucket'];value=None if value is None else int(value)
        row['label']='Time unavailable' if value is None else f'{value:02d}:00–{(value+1)%24:02d}:00' if group=='hour' else 'At / after close' if value==0 else 'Over 1 day' if value==1441 else f'>{max((b for b in (time_bounds(bot) if group=='time_price' else TIME_BOUNDS) if b<value),default=0)}–{value} min remaining'
        items.append(row)
    return items,len(rows)>250

COUNTS=('orders','filled_orders','contracts','resting_contracts','held_contracts','scored','wins','unscored_resets')

def performance_rows(bot,rows):
    def key(revision,square,condition):
        return (revision,square,json.dumps(condition,sort_keys=True))
    result={}
    for index,condition in enumerate(bot['config']['squares']):
        row=dict(revision=bot['revision'],square=index,condition=condition,recorded_pnl_cents=None,**dict.fromkeys(COUNTS,0))
        result[key(row['revision'],index,condition)]=row
    for raw in rows:
        row=dict(raw)
        # Older records without a saved condition must not inherit a changed rule.
        condition=row.get('condition')
        if condition is None and row['revision']==bot['revision'] and isinstance(row.get('square'),int) and 0<=row['square']<len(bot['config']['squares']):
            condition=bot['config']['squares'][row['square']]
        row['condition']=condition
        for field in COUNTS:row[field]=float(row[field] or 0)
        row['recorded_pnl_cents']=float(row['recorded_pnl_cents']) if row.get('scored') and row.get('recorded_pnl_cents') is not None else None
        result[key(row['revision'],row['square'],condition)]=row
    return list(result.values())


def time_bounds(bot):
    from services.research.reports import MINUTES
    return sorted({bound for square in bot['config']['squares'] for bound in MINUTES[square['asset']]})
