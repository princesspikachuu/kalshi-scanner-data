"""Bounded saved-order summaries; no exchange requests or history rewrites."""
import json

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
