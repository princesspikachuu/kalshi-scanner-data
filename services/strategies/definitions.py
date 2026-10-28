"""Strict, versioned strategy contract using integer cents and contract counts.

The record is deliberately draft-only. A paper engine must add its own evidence,
mode and permission gates before it can evaluate or submit anything.
"""
import hashlib
import json

from services.research.reports import SERIES

VERSION='draft-strategy-v1'
BANDS=('50-60','60-70','70-80','80-90','90-100')


def _keys(value,expected):
    if not isinstance(value,dict) or set(value)!=set(expected):
        raise ValueError('Invalid strategy fields')


def _int(value,low,high):
    if type(value) is not int or not low<=value<=high:
        raise ValueError('Invalid strategy integer')
    return value


def validate(raw):
    """Return canonical JSON-safe rules; reject floats, extras and implicit units."""
    _keys(raw,('version','asset','series','entry','exit','limits'))
    if raw['version']!=VERSION or type(raw['asset']) is not str or raw['asset'] not in SERIES:
        raise ValueError('Unsupported strategy version or category')
    asset=raw['asset'];series=raw['series']
    if (not isinstance(series,list) or not 1<=len(series)<=len(SERIES[asset])
            or any(type(s) is not str for s in series) or len(set(series))!=len(series)
            or not set(series)<=SERIES[asset]):
        raise ValueError('Invalid strategy market series')
    entry=raw['entry'];_keys(entry,('minutes_before_close','side','max_bid_cents','maker_offset_cents',
                                  'contracts','wait_seconds','replace_limit'))
    _int(entry['minutes_before_close'],1,1440)
    if entry['side'] not in ('yes','no'):raise ValueError('Invalid entry side')
    _int(entry['max_bid_cents'],50,99);_int(entry['maker_offset_cents'],0,20)
    _int(entry['contracts'],1,10000);_int(entry['wait_seconds'],0,3600)
    _int(entry['replace_limit'],0,20)
    exit_rule=raw['exit'];_keys(exit_rule,('loss_reduction_enabled','decision_minutes_before_close',
                                          'thresholds_cents','research_result_id'))
    if type(exit_rule['loss_reduction_enabled']) is not bool:raise ValueError('Invalid exit switch')
    _int(exit_rule['decision_minutes_before_close'],0,1439)
    if exit_rule['decision_minutes_before_close']>=entry['minutes_before_close']:
        raise ValueError('Exit decision must follow entry')
    thresholds=exit_rule['thresholds_cents'];_keys(thresholds,BANDS)
    for band,value in thresholds.items():
        if value is not None:
            _int(value,1,int(band[:2]))
    if exit_rule['loss_reduction_enabled']:
        _int(exit_rule['research_result_id'],1,2**63-1)
        if all(value is None for value in thresholds.values()):
            raise ValueError('Enabled exit needs a measured threshold')
    elif exit_rule['research_result_id'] is not None or any(v is not None for v in thresholds.values()):
        raise ValueError('Disabled exit cannot silently retain active thresholds')
    limits=raw['limits'];_keys(limits,('per_trade_cents','category_open_cents','strategy_open_cents',
                                     'global_open_cents','daily_spend_cents'))
    for value in limits.values():_int(value,1,10**9)
    per_trade=entry['contracts']*entry['max_bid_cents']
    if limits['per_trade_cents']<per_trade or any(limits[key]<limits['per_trade_cents'] for key in
          ('category_open_cents','strategy_open_cents','global_open_cents','daily_spend_cents')):
        raise ValueError('Strategy spending limits contradict order size')
    return {**raw,'series':sorted(series),'entry':dict(entry),'exit':{**exit_rule,'thresholds_cents':dict(thresholds)},
            'limits':dict(limits)}


def fingerprint(rules):
    canonical=validate(rules)
    return hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
