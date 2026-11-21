"""Fee-inclusive event return attribution; pooled ROI is deliberately separate."""
from decimal import Decimal as D


def merge(target, source):
    for event, value in source.items():
        row = target.setdefault(event, dict(cost='0', net='0'))
        if value.get('estimated'):row['estimated']=True
        for field in ('cost', 'net'):
            row[field] = str(D(row[field]) + D(value[field]))


def summarize(events):
    values = [D(row['net']) / D(row['cost']) for row in events.values() if D(row['cost']) > 0]
    return dict(estimated_return_observations=sum(bool(row.get('estimated')) for row in events.values() if D(row['cost'])>0),
                return_observations=len(values), return_sum=str(sum(values, D(0))),
                average_return_pct=str(100 * sum(values, D(0)) / len(values)) if values else None)
