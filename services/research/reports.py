"""Versioned full-hold-cohort research summaries; no trades or hosting actions."""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import hashlib

from psycopg.types.json import Jsonb

from .datasets import FORMAT,decoded_dataset
from .inventory import digest
from .models.conditional_v2 import SOURCE_COMMIT, analyze_risk, policy_cells
from .normalize import _closed
from .queue import EvidenceConflict, text_key

MODEL = 'research-return-conditional-v1'
MAX_REPORT_BYTES=96*1024*1024
MAX_PATH_BARS=1000000
PUBLICATION_BATCH_ROWS=1000
MINUTES = {
    'btc':(15,10,5,3,1),'eth':(15,10,5,3,1),'crypto':(15,10,5,3,1),
    'weather':(60,45,30,20,15,10,5,3,1),
    'sports':(360,180,120,60,30,15,5),'weather_daily':(360,180,120,60,30,15,5)}
SERIES = {
    'btc':{'KXBTC15M'},'eth':{'KXETH15M'},
    'crypto':{'KXBTC15M','KXETH15M','KXSOL15M','KXXRP15M','KXDOGE15M','KXBNB15M','KXHYPE15M','KXZEC15M','KXNEAR15M'},
    'weather':{'KXTEMPNYCHS','KXTEMPCHIHS','KXTEMPMIAH','KXTEMPLAXHS','KXTEMPNYCH','KXTEMPCHIH','KXTEMPLAH','KXTEMPDCH'},
    'sports':{'KXNBAGAME','KXNFLGAME','KXNHLGAME','KXMLBGAME','KXNCAAFGAME','KXATPMATCH','KXWTAMATCH'},
    'weather_daily':{'KXHIGHNY','KXHIGHCHI','KXHIGHLAX','KXHIGHMIA','KXHIGHAUS','KXHIGHDEN','KXHIGHTEWR'}}


def _price(candle,side,kind):
    quote=candle.get(side+'_'+kind) or {}
    raw=quote.get('close_dollars',quote.get('close'))
    try:
        value=Decimal(str(raw))
        return value if value.is_finite() and 0<=value<=1 else None
    except InvalidOperation: return None


def _bid(candle,side):
    value=_price(candle,side,'bid')
    if value is None and side=='no':
        ask=_price(candle,'yes','ask')
        if ask is not None: value=1-ask
    return value


def observations(asset,datasets):
    return _observations(asset,sorted(datasets,key=lambda d:d['id']))


def _observations(asset,datasets,*,candidate_filter=None):
    if asset not in MINUTES: raise ValueError('Unsupported research category')
    rows,paths,origin,seen,missing=[],{}, {},set(),[]
    candidate_count=0;bar_count=0
    for dataset in datasets:
        payload=decoded_dataset(dataset)['payload']
        if payload.get('format')!=FORMAT or digest(payload)!=dataset['fingerprint']:
            raise EvidenceConflict('Published raw dataset integrity mismatch')
        if payload['candidates'] and 'candles' not in payload['summary']['resources']:
            raise EvidenceConflict('Candle membership is required for return summaries')
        candidates=[candidate for candidate in payload['candidates'] if candidate_filter is None or candidate_filter(dataset['id'],candidate)]
        tickers={candidate['ticker'] for candidate in candidates}
        bars=defaultdict(list)
        for record in payload['records']:
            if record['resource']=='candles' and (candidate_filter is None or record['ticker'] in tickers):
                bar_count+=1
                if bar_count>MAX_PATH_BARS:raise ValueError('Report path limit exceeded; split the range')
                bars[record['ticker']].append(record['record'])
        for candidate in candidates:
            ticker,day=candidate['ticker'],payload['day']
            key=(day,ticker)
            if key in seen: raise EvidenceConflict('Select one raw version per market/day; refreshes cannot be pooled')
            seen.add(key);candidate_count+=1
            if candidate_count*len(MINUTES[asset])>250000:raise ValueError('Report entry limit exceeded; split the range')
            if candidate['series'] not in SERIES[asset] or candidate['result'] not in ('yes','no'):
                raise EvidenceConflict('Candidate does not belong to selected category')
            close=int(_closed(candidate['close_time']).timestamp())
            candles=sorted(bars[ticker],key=lambda b:b['end_period_ts'])
            times=[b['end_period_ts'] for b in candles]
            paths[key]={'close_ts':close,'bars':[[b['end_period_ts'],
                float(_bid(b,'yes')*100) if _bid(b,'yes') is not None else None,
                float(_bid(b,'no')*100) if _bid(b,'no') is not None else None] for b in candles]}
            for minute in MINUTES[asset]:
                target=close-minute*60
                index=bisect_right(times,target)-1
                selected=[]
                if index>=0 and 0<=target-times[index]<=120:
                    candle=candles[index]
                    for side in ('yes','no'):
                        bid=_bid(candle,side)
                        if bid is not None and Decimal('.5')<=bid<1: selected.append((bid,side))
                if not selected:
                    missing.append(dict(dataset_id=dataset['id'],date=day,ticker=ticker,minutes_before_close=minute))
                    continue
                # Highest entry bid, YES on an exact tie, before examining outcome.
                bid,side=max(selected,key=lambda v:(v[0],v[1]=='yes'))
                low=int(bid*100)//10*10
                row=dict(date=day,asset=asset,series=candidate['series'],ticker=ticker,event_ticker=candidate['event_ticker'],
                    close_time=candidate['close_time'],side=side,minutes_before_close=minute,price_band=f'{low:02d}-{low+10:02d}',
                    maker_bid=str(bid),won=int(candidate['result']==side),quote_age_seconds=target-times[index],
                    dataset_id=dataset['id'],dataset_fingerprint=dataset['fingerprint'],quote_period_ts=times[index])
                rows.append(row);origin[(day,ticker,minute)]=dataset['id']
    return rows,paths,origin,dict(candidate_count=candidate_count,requested_entry_slots=candidate_count*len(MINUTES[asset]),
        missing_entry_slots=missing,observation_count=len(rows))


def _cells(rows,policies):
    grouped=defaultdict(list)
    for row in rows: grouped[(int(row['minutes_before_close']),row['price_band'])].append(row)
    by_policy={(int(p['minutes_before_close']),p['price_band_cents']):p for p in policies}
    cells=[]
    for (minute,band),items in sorted(grouped.items()):
        n=len(items);wins=sum(int(r['won']) for r in items)
        paid=sum(float(r['maker_bid']) for r in items)
        price=round(100*paid/n,4);hold=round(100*(wins-paid)/n,4)
        policy=by_policy.get((minute,band),{})
        covered=policy.get('covered_observations',0)
        if not 0<=covered<=n: raise EvidenceConflict('Exit sample exceeds original hold cohort')
        delta=policy.get('total_delta_cents',0)
        pnl=hold+delta/n
        recoveries=policy.get('missed_recoveries',0)
        threshold=policy.get('threshold_cents')
        original=dict(asset=items[0]['asset'],minutes_before_close=minute,price_band_cents=band,sampled_markets=n,
            wins=wins,win_rate_percent=round(100*wins/n,4),average_purchase_price_cents=price,
            average_profit_loss_cents_per_contract=hold,hypothetical_roi_percent=round(100*(wins-paid)/paid,4),
            sampled_days=len({r['date'] for r in items}))
        adjusted={**original,'wins':max(0,wins-recoveries),'win_rate_percent':100*max(0,wins-recoveries)/n if recoveries else original['win_rate_percent'],
            'average_profit_loss_cents_per_contract':pnl,'hypothetical_roi_percent':100*pnl/price if delta else original['hypothetical_roi_percent'],
            'threshold_cents':threshold,'trade_not_recommended':2*wins<n,'exit_coverage':covered,
            'early_exits':policy.get('early_exits',0),'improvement_cents':delta/n,'hold_net_cents':hold,
            'sell_label':'Trade not recommended' if 2*wins<n else 'Sell: —' if threshold is None else f'Sell ≤ {threshold}¢'}
        cells.append(dict(hold=original,loss_prevention=adjusted))
    return cells


@dataclass(frozen=True)
class PreparedReport:
    payload_json: str
    fingerprint: str
    observations_json: str


def report_fingerprint(report_json,observations_json):
    """Hash the exact canonical envelope without another full observation copy."""
    checksum=hashlib.sha256()
    checksum.update(b'{"observations":')
    for value in (observations_json,',"report":',report_json,'}'):
        for offset in range(0,len(value),65536):
            checksum.update(value[offset:offset+65536].encode())
    return checksum.hexdigest()


def prepare_report(asset,datasets,*,latest_ids):
    return prepare_report_stream(asset,iter(sorted(datasets,key=lambda d:d['id'])),latest_ids=latest_ids)


def prepare_report_stream(asset,datasets,*,latest_ids,candidate_filter=None):
    """Load one immutable raw dataset at a time, retaining bounded derived inputs.

    Caller supplies ascending unique IDs; model/rounding/full-cohort arithmetic is
    identical to the original builder. Memory limits FAIL rather than sample rows.
    """
    metadata=[]
    def inputs():
        previous=0
        for d in datasets:
            if type(d['id']) is not int or d['id']<=previous or len(metadata)>=3661:raise ValueError('Select ascending unique dataset IDs, at most 3661')
            previous=d['id']
            d=decoded_dataset(d)
            metadata.append(dict(id=d['id'],fingerprint=d['fingerprint'],day=d['payload']['day'],candidate_count=sum(1 for candidate in d['payload']['candidates'] if candidate_filter is None or candidate_filter(d['id'],candidate))))
            yield d
    rows,paths,origin,coverage=_observations(asset,inputs(),candidate_filter=candidate_filter)
    datasets=metadata;ids=[d['id'] for d in datasets]
    if not ids:raise ValueError('Select dataset versions')
    latest_list=None if latest_ids is None else list(latest_ids)
    if latest_list is not None and (len(set(latest_list))!=len(latest_list) or any(type(i) is not int or i<1 for i in latest_list)):
        raise ValueError('Invalid latest membership')
    latest=None if latest_list is None else set(latest_list)
    if latest is not None and not latest.issubset(ids): raise ValueError('Latest membership must be an explicit subset')
    latest_keys=None if latest is None else {k for k,v in origin.items() if v in latest}
    del origin
    risk=analyze_risk(rows,paths,asset,include_snapshots=True,compact=True)
    del paths
    historical_policy,latest_policy=policy_cells(risk.pop('_snapshot_groups'),latest_keys)
    risk.pop('records',None)
    latest_rows=[r for r in rows if latest_keys is not None and (r['date'],r['ticker'],r['minutes_before_close']) in latest_keys]
    historical_cells=_cells(rows,historical_policy);latest_cells=_cells(latest_rows,latest_policy)
    for policies,cells in ((historical_policy,historical_cells),(latest_policy,latest_cells)):
        bases={(c['hold']['minutes_before_close'],c['hold']['price_band_cents']):c['hold'] for c in cells}
        for p in policies:
            base=bases.get((p['minutes_before_close'],p['price_band_cents']))
            if base: p.update(base_n=base['sampled_markets'],base_wins=base['wins'],base_price_cents=base['average_purchase_price_cents'])
    days=sorted({d['day'] for d in datasets})
    latest_days=sorted({d['day'] for d in datasets if latest is not None and d['id'] in latest})
    latest_candidates=None if latest is None else sum(d['candidate_count'] for d in datasets if d['id'] in latest)
    payload=dict(model_version=MODEL,source_commit=SOURCE_COMMIT,asset=asset,entry_minutes=list(MINUTES[asset]),
        price_bands=['50-60','60-70','70-80','80-90','90-100'],
        datasets=[dict(id=d['id'],fingerprint=d['fingerprint'],latest=latest is not None and d['id'] in latest) for d in sorted(datasets,key=lambda d:d['id'])],
        latest_membership_known=latest is not None,coverage=coverage,risk_coverage=risk,
        historical=dict(cells=historical_cells,policy_cells=historical_policy,observation_count=len(rows),candidate_count=coverage['candidate_count'],first_date=days[0],last_date=days[-1]),
        latest=dict(cells=latest_cells,policy_cells=latest_policy,observation_count=len(latest_rows),candidate_count=latest_candidates,first_date=latest_days[0] if latest_days else None,last_date=latest_days[-1] if latest_days else None),
        execution_included=False,baseline_fees_cents=0,exit_cost_stress_cents=2)
    encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False)
    obs=json.dumps(rows,sort_keys=True,separators=(',',':'),allow_nan=False)
    if len(encoded.encode())+len(obs.encode())>MAX_REPORT_BYTES: raise ValueError('Research result too large; explicit partitions required')
    return PreparedReport(encoded,report_fingerprint(encoded,obs),obs)


class ReportStore:
    def __init__(self,pool): self.pool=pool

    def publish(self,stream_key,asset,dataset_ids,*,latest_ids):
        text_key(stream_key,128)
        ids=list(dataset_ids)
        if not ids or len(ids)>1000 or len(set(ids))!=len(ids) or any(type(i) is not int or i<1 for i in ids): raise ValueError('Invalid dataset membership')
        with self.pool.connection() as c:
            size=c.execute("SELECT count(*) AS n,COALESCE(sum(COALESCE((payload->>'uncompressed_bytes')::bigint,octet_length(payload::text))),0) AS bytes FROM research_dataset WHERE id=ANY(%s::bigint[])",(ids,)).fetchone()
            if size['n']!=len(ids): raise EvidenceConflict('Missing selected dataset version')
            if size['bytes']>64*1024*1024: raise ValueError('Selected raw inputs exceed bounded report memory budget')
            datasets=c.execute("SELECT id,fingerprint,payload FROM research_dataset WHERE id=ANY(%s::bigint[]) ORDER BY id",(ids,)).fetchall()
        if len(datasets)!=len(ids): raise EvidenceConflict('Missing selected dataset version')
        prepared=prepare_report(asset,datasets,latest_ids=latest_ids)
        return self._save(stream_key,asset,prepared)

    def _save(self,stream_key,asset,prepared,*,minimum_revision=None):
        payload=json.loads(prepared.payload_json)
        # Preview cells retain full source cohorts; raw datasets already retain
        # every observation input. Avoid O(days squared) observation duplication.
        preview=payload.get('publication',{}).get('complete') is False
        rows=[] if preview else json.loads(prepared.observations_json)
        with self.pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,91028))',(stream_key,))
            if stream_key.startswith('campaign-') and 'publication' in payload:
                latest=c.execute('SELECT id,report FROM research_result WHERE stream_key=%s ORDER BY id DESC LIMIT 1',(stream_key,)).fetchone()
                if latest:
                    previous=latest['report'].get('publication',{'complete':True,'revision':0})
                    incoming=payload['publication']
                    if not incoming['complete'] and (previous['complete'] or previous['revision']>incoming['revision']):return latest['id']
                    if incoming['complete'] and previous['complete'] and previous['revision']>incoming['revision']:return latest['id']
            if minimum_revision is not None:
                latest=c.execute('SELECT id,report FROM research_result WHERE stream_key=%s ORDER BY id DESC LIMIT 1',(stream_key,)).fetchone()
                if latest and latest['report'].get('selection',{}).get('revision',0)>minimum_revision:return latest['id']
            found=c.execute('SELECT id FROM research_result WHERE stream_key=%s AND fingerprint=%s',(stream_key,prepared.fingerprint)).fetchone()
            if found: return found['id']
            result=c.execute('INSERT INTO research_result(stream_key,model_version,fingerprint,asset,report) VALUES(%s,%s,%s,%s,%s) RETURNING id',
                (stream_key,MODEL,prepared.fingerprint,asset,Jsonb(payload))).fetchone()['id']
            c.execute('''INSERT INTO research_result_dataset(result_id,dataset_id,is_latest)
                SELECT %s,id,latest FROM jsonb_to_recordset(%s::jsonb) AS m(id bigint,latest boolean)''',(result,Jsonb(payload['datasets'])))
            # Bound PostgreSQL's JSON expansion memory; every batch remains in
            # this SAME publication transaction, preserving all-or-nothing sealing.
            for offset in range(0,len(rows),PUBLICATION_BATCH_ROWS):
                c.execute('''INSERT INTO research_observation(result_id,day,ticker,minute,observation)
                    SELECT %s,(r->>'date')::date,r->>'ticker',(r->>'minutes_before_close')::integer,r
                    FROM jsonb_array_elements(%s::jsonb) AS t(r)''',(result,Jsonb(rows[offset:offset+PUBLICATION_BATCH_ROWS])))
            return result

    def publish_campaign(self,stream_key,asset,dataset_ids,*,publication=None):
        text_key(stream_key,128)
        ids=sorted(dataset_ids)
        if not ids or len(ids)>3661 or len(set(ids))!=len(ids) or any(type(i) is not int or i<1 for i in ids):raise ValueError('Invalid campaign membership')
        def inputs():
            for identifier in ids:
                with self.pool.connection() as c:
                    size=c.execute("SELECT COALESCE((payload->>'uncompressed_bytes')::bigint,octet_length(payload::text)) AS bytes FROM research_dataset WHERE id=%s",(identifier,)).fetchone()
                    if not size:raise EvidenceConflict('Missing campaign dataset')
                    if size['bytes']>64*1024*1024:raise ValueError('Raw dataset exceeds bounded report input')
                    row=c.execute("SELECT id,fingerprint,payload FROM research_dataset WHERE id=%s",(identifier,)).fetchone()
                yield row
        prepared=prepare_report_stream(asset,inputs(),latest_ids=ids)
        if publication is not None:
            payload=json.loads(prepared.payload_json);payload['publication']=publication
            encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False)
            prepared=PreparedReport(encoded,report_fingerprint(encoded,prepared.observations_json),prepared.observations_json)
        return self._save(stream_key,asset,prepared)
