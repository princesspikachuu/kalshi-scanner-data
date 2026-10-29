"""Full-cohort metric regression and disposable-PG report publication tests."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timezone,timedelta
import json
import os
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import psycopg
from services.api.manage import migrate
from services.api.store import PostgresStore
from services.research.datasets import DatasetStore
from services.research.inventory import digest
from services.research.queue import EvidenceConflict
from services.research.reports import prepare_report,ReportStore,_cells
from test_datasets import Fixture

URL=os.environ.get('POCKET_TEST_DATABASE_URL')


def dataset(identifier=1,*,day=1,entry='.95',decision='.55',won=False,age=0):
    date=datetime(2026,10,day,12,tzinfo=timezone.utc)
    close=int(date.timestamp());ticker=f'KXBTC15M-D{day}'
    bars=[dict(end_period_ts=close-600-age,yes_bid={'close':entry})]
    if decision is not None:bars.append(dict(end_period_ts=close-300,yes_bid={'close':decision}))
    payload=dict(format='raw-evidence-dataset-v1',day=date.date().isoformat(),
        candidates=[dict(ticker=ticker,event_ticker=f'E{day}',series='KXBTC15M',close_time=date.isoformat(),result='yes' if won else 'no')],
        records=[dict(resource='candles',ticker=ticker,record=b) for b in bars],summary={'resources':['candles']})
    return dict(id=identifier,payload=payload,fingerprint=digest(payload))


def row(ticker='T',won=0):
    return dict(asset='btc',date='2026-10-25',ticker=ticker,minutes_before_close=10,price_band='90-100',maker_bid='.95',won=won)


class ReportTests(unittest.TestCase):
    def report(self,rows,latest=None):return json.loads(prepare_report('btc',rows,latest_ids=latest).payload_json)

    def test_compact_policy_inputs_preserve_exact_report_and_fingerprint(self):
        import services.research.reports as model
        selected=[dataset(i,day=i,decision=None if i%3==0 else '.55',
                          won=i%2==0,age=120 if i%4==0 else 0) for i in range(1,21)]
        compact=prepare_report('btc',selected,latest_ids=[19,20])
        original=model.analyze_risk
        def diagnostics(*args,**kwargs):
            kwargs['compact']=False
            return original(*args,**kwargs)
        with patch.object(model,'analyze_risk',side_effect=diagnostics):
            self.assertEqual(compact,prepare_report('btc',selected,latest_ids=[19,20]))
        payload=json.loads(compact.payload_json);rows=json.loads(compact.observations_json)
        self.assertEqual(compact.fingerprint,digest(dict(report=payload,observations=rows)))

    def test_compressed_report_projection_verifies_source_and_preserves_full_result(self):
        from services.research.datasets import storage_payload
        from services.research.report_inputs import report_dataset
        d=dataset();plain=deepcopy(d)
        plain['payload']['records'] += [dict(resource='trades',ticker='KXBTC15M-D1',record={'trade_id':str(i),'details':'x'*1000},
            provenance=[{'unused':'z'*1000}]) for i in range(2000)]
        plain['fingerprint']=digest(plain['payload'])
        encoded=json.dumps(plain['payload'],sort_keys=True,separators=(',',':'))
        packed={**plain,'payload':storage_payload(encoded,plain['fingerprint'])}
        projected=report_dataset(packed)
        self.assertEqual(len(projected['payload']['records']),len(d['payload']['records']))
        self.assertEqual(prepare_report('btc',[plain],latest_ids=[1]),prepare_report('btc',[packed],latest_ids=[1]))
        self.assertEqual(len(plain['payload']['records']),2002)
        corrupt=deepcopy(packed);corrupt['fingerprint']='0'*64
        with self.assertRaises(EvidenceConflict):report_dataset(corrupt)
        corrupt=deepcopy(plain);corrupt['payload']['candidates'][0]['result']='yes'
        with self.assertRaises(EvidenceConflict):report_dataset(corrupt)

    def test_checkpoint_projection_preserves_dense_paths_nulls_and_report(self):
        import services.research.reports as model
        from services.research.models.conditional_v2 import CHECKPOINTS
        selected=[dataset(i,day=i,won=i%2==0) for i in range(1,21)]
        for d in selected:
            close=int(datetime.fromisoformat(d['payload']['candidates'][0]['close_time']).timestamp())
            d['payload']['records']=[dict(resource='candles',ticker=d['payload']['candidates'][0]['ticker'],
                record=dict(end_period_ts=close-60*m,yes_bid={'close':None if m==5 else '.95' if m>=10 else '.55'}))
                for m in range(370,0,-1) if m not in (3,20)]
            d['fingerprint']=digest(d['payload'])
        expected=prepare_report('btc',selected,latest_ids=[19,20])
        def full_paths(asset,inputs,*,candidate_filter=None):
            inputs=list(inputs)
            rows,paths,origin,coverage=model._raw_observations(asset,inputs,candidate_filter=candidate_filter)
            paths=dict(paths)
            for d in inputs:
                key=(d['payload']['day'],d['payload']['candidates'][0]['ticker'])
                paths[key]['bars']=[[r['record']['end_period_ts'],
                    float(model._bid(r['record'],'yes')*100) if model._bid(r['record'],'yes') is not None else None,None]
                    for r in d['payload']['records']]
            return rows,paths,dict(origin),{k:v for k,v in coverage.items() if k!='_path_bars'}
        with patch.object(model,'_observations',side_effect=full_paths):
            self.assertEqual(expected,prepare_report('btc',selected,latest_ids=[19,20]))
        _,paths,_,coverage=model._raw_observations('btc',selected)
        self.assertLessEqual(coverage['_path_bars'],len(selected)*len(CHECKPOINTS))
        self.assertTrue(any(b[1] is None for p in dict(paths).values() for b in p['bars']))

    def test_hold_denominator_does_not_shrink_to_exit_coverage_or_missing_trades(self):
        rows=[row(str(i),int(i==0)) for i in range(4)]
        p=dict(minutes_before_close=10,price_band_cents='90-100',threshold_cents=60,
               covered_observations=1,total_delta_cents=38,early_exits=1,missed_recoveries=0)
        cell=_cells(rows,[p])[0]
        self.assertEqual(cell['hold']['sampled_markets'],4)
        self.assertEqual(cell['loss_prevention']['sampled_markets'],4)
        self.assertAlmostEqual(cell['loss_prevention']['average_profit_loss_cents_per_contract'],cell['hold']['average_profit_loss_cents_per_contract']+38/4)
        self.assertEqual(cell['loss_prevention']['exit_coverage'],1)
        self.assertEqual(cell['loss_prevention']['sell_label'],'Trade not recommended')

    def test_exactly_half_losing_is_not_rejected_and_threshold_label_contains_no_time(self):
        p=dict(minutes_before_close=10,price_band_cents='90-100',threshold_cents=60,covered_observations=0,total_delta_cents=0)
        cell=_cells([row('A',1),row('B',0)],[p])[0]['loss_prevention']
        self.assertFalse(cell['trade_not_recommended'])
        self.assertEqual(cell['sell_label'],'Sell ≤ 60¢')
        self.assertEqual(cell['sampled_markets'],2)
        self.assertEqual(cell['wins'],1)

    def test_full_historical_and_latest_membership_are_separate_and_deterministic(self):
        selected=[dataset(1,day=1),dataset(2,day=2,won=True)]
        a=prepare_report('btc',selected,latest_ids=[1])
        b=prepare_report('btc',reversed(selected),latest_ids=[1])
        self.assertEqual(a.fingerprint,b.fingerprint)
        p=json.loads(a.payload_json)
        self.assertEqual(p['historical']['candidate_count'],2)
        self.assertEqual(p['latest']['candidate_count'],1)
        self.assertGreater(p['historical']['observation_count'],p['latest']['observation_count'])
        self.assertFalse(p['execution_included'])
        self.assertTrue(p['latest_membership_known'])

    def test_daily_contributions_are_reused_without_changing_global_cohorts(self):
        import services.research.reports as model
        from services.research.cache import ByteCache
        selected=[dataset(i,day=i,won=i%2==0) for i in range(1,8)]
        with patch.object(model,'_daily_inputs',ByteCache(16*1024*1024)) as cache:
            cold=prepare_report('btc',selected,latest_ids=[6,7])
            def original_inputs(asset,inputs,*,candidate_filter=None):
                rows,paths,origin,coverage=model._raw_observations(asset,inputs,candidate_filter=candidate_filter)
                return rows,dict(paths),dict(origin),{k:v for k,v in coverage.items() if k!='_path_bars'}
            with patch.object(model,'_observations',side_effect=original_inputs):
                self.assertEqual(cold,prepare_report('btc',selected,latest_ids=[6,7]))
            self.assertEqual(len(cache),7)
            warm=prepare_report('btc',selected,latest_ids=[6,7])
            self.assertEqual(cold,warm)
            self.assertEqual(len(cache),7)
            self.assertEqual(json.loads(warm.payload_json)['historical']['candidate_count'],7)
            corrupt=deepcopy(selected[0]);corrupt['payload']['candidates'][0]['result']='yes'
            with self.assertRaises(EvidenceConflict):
                prepare_report('btc',[corrupt]+selected[1:],latest_ids=[6,7])

    def test_unknown_latest_membership_cannot_invent_latest_rows_or_roi(self):
        p=self.report([dataset()],latest=None)
        self.assertFalse(p['latest_membership_known'])
        self.assertEqual(p['latest']['cells'],[])
        self.assertIsNone(p['latest']['candidate_count'])

    def test_missing_quotes_are_explicit_and_do_not_invent_safe_holding(self):
        d=dataset();d['payload']['records']=[];d['fingerprint']=digest(d['payload'])
        p=self.report([d],[1])
        self.assertEqual(p['historical']['candidate_count'],1)
        self.assertEqual(p['historical']['cells'],[])
        self.assertEqual(len(p['coverage']['missing_entry_slots']),5)
        self.assertEqual(p['coverage']['requested_entry_slots'],5)

    def test_120_second_hold_quote_stays_in_full_sample_but_not_fresh_exit_training(self):
        p=self.report([dataset(age=120,decision=None)],[1])
        cells=[c for c in p['historical']['cells'] if c['hold']['minutes_before_close']==10]
        self.assertEqual(len(cells),1)
        self.assertEqual(cells[0]['hold']['sampled_markets'],1)
        self.assertEqual(cells[0]['loss_prevention']['exit_coverage'],0)
        self.assertEqual(p['risk_coverage']['eligible_entry_observations'],0)

    def test_higher_bid_side_is_chosen_without_looking_at_settlement_and_no_bid_uses_yes_ask(self):
        d=dataset(entry='.20');d['payload']['records'][0]['record']['yes_ask']={'close':'.25'}
        d['fingerprint']=digest(d['payload'])
        p=self.report([d],[1])
        cell=next(c['hold'] for c in p['historical']['cells'] if c['hold']['minutes_before_close']==10)
        self.assertEqual(cell['average_purchase_price_cents'],75)
        self.assertEqual(cell['wins'],1)

    def test_refresh_overlap_fingerprint_changes_and_invalid_latest_ids_fail(self):
        d=dataset();other={**deepcopy(d),'id':2}
        with self.assertRaises(EvidenceConflict):self.report([d,other],[1])
        corrupt=deepcopy(d);corrupt['payload']['candidates'][0]['result']='yes'
        with self.assertRaises(EvidenceConflict):self.report([corrupt],[1])
        for latest in ([2],[True],[1,1]):
            with self.assertRaises(ValueError):self.report([d],latest)

    def test_end_to_end_policy_delta_uses_all_twenty_hold_rows_not_six_covered_rows(self):
        selected=[dataset(i,day=i,decision=(('.55' if i%2 else '.65') if i<=14 else ('.40' if i%2 else '.65')),
                          won=(i%2==0 or i==19)) for i in range(1,21)]
        report=self.report(selected,[19])
        cell=next(c for c in report['historical']['cells'] if c['hold']['minutes_before_close']==10)
        self.assertEqual(cell['hold']['sampled_markets'],20)
        self.assertEqual(cell['loss_prevention']['sampled_markets'],20)
        self.assertEqual(cell['loss_prevention']['exit_coverage'],6)
        self.assertEqual(cell['loss_prevention']['threshold_cents'],60)
        self.assertAlmostEqual(cell['loss_prevention']['improvement_cents'],14/20)
        self.assertEqual(cell['loss_prevention']['sell_label'],'Sell ≤ 60¢')
        latest=next(c for c in report['latest']['cells'] if c['hold']['minutes_before_close']==10)
        self.assertEqual(latest['hold']['sampled_markets'],1)
        self.assertEqual(latest['loss_prevention']['improvement_cents'],-62)

    def test_older_latest_threshold_and_adjustment_do_not_change_with_future_outcomes(self):
        selected=[dataset(i,day=i,decision=('.55' if i%2 else '.65'),won=i%2==0) for i in range(1,21)]
        before=self.report(selected,list(range(1,11)))['latest']
        for d in selected[10:]:
            d['payload']['candidates'][0]['result']='yes' if d['payload']['candidates'][0]['result']=='no' else 'no'
            d['fingerprint']=digest(d['payload'])
        after=self.report(selected,list(range(1,11)))['latest']
        self.assertEqual(before,after)


@unittest.skipUnless(URL,'Requires disposable pocket_test PostgreSQL')
class ReportPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path!='/pocket_test':raise RuntimeError('Requires disposable pocket_test database')
        migrate(URL);cls.store=PostgresStore(URL);cls.store.open();cls.datasets=DatasetStore(cls.store.pool);cls.reports=ReportStore(cls.store.pool)
    @classmethod
    def tearDownClass(cls):cls.store.close()
    def setUp(self):
        with self.store.pool.connection() as c:
            c.execute('TRUNCATE research_result_dataset,research_observation,research_result,research_dataset_artifact,research_summary,research_dataset,research_artifact CASCADE')
        fixture=Fixture()
        for n,(job,pages) in enumerate(fixture.attempts):
            scope=next(s for s in fixture.plan.scopes if s.key==job['id'])
            if scope.resource=='candles':
                payload={'ticker':scope.ticker,'candlesticks':[{'end_period_ts':scope.start_ts,'yes_bid':{'close':'0.88'}}]}
                fixture.attempts[n]=fixture.attempt(scope,payload,1,jid=scope.key)
        self.dataset_id=self.datasets.publish('btc-raw',fixture.prepare())
    def counts(self):
        with self.store.pool.connection() as c:
            return tuple(c.execute('SELECT count(*) AS n FROM '+t).fetchone()['n'] for t in ('research_result','research_result_dataset','research_observation'))

    def test_publish_is_atomic_idempotent_and_keeps_exact_dataset_membership(self):
        result=self.reports.publish('btc-results','btc',[self.dataset_id],latest_ids=[self.dataset_id])
        self.assertEqual(self.reports.publish('btc-results','btc',[self.dataset_id],latest_ids=[self.dataset_id]),result)
        with self.store.pool.connection() as c:
            payload=c.execute('SELECT report FROM research_result WHERE id=%s',(result,)).fetchone()['report']
            member=c.execute('SELECT dataset_id,is_latest FROM research_result_dataset WHERE result_id=%s',(result,)).fetchone()
        self.assertEqual(payload['latest']['candidate_count'],1)
        self.assertEqual(member,dict(dataset_id=self.dataset_id,is_latest=True))
        self.assertEqual(self.counts()[0:2],(1,1))

    def test_progress_snapshots_cannot_replace_newer_or_completed_reports(self):
        partial=lambda revision:dict(complete=False,revision=revision,reported_sections=1,total_sections=2)
        first=self.reports.publish_campaign('campaign-progress','btc',[self.dataset_id],publication=partial(1))
        newer=self.reports.publish_campaign('campaign-progress','btc',[self.dataset_id],publication=partial(3))
        self.assertNotEqual(first,newer)
        self.assertEqual(self.reports.publish_campaign('campaign-progress','btc',[self.dataset_id],publication=partial(1)),newer)
        self.assertEqual(self.counts()[2],0)
        complete=self.reports.publish_campaign('campaign-progress','btc',[self.dataset_id],
            publication=dict(complete=True,revision=4,reported_sections=1,total_sections=1))
        self.assertEqual(self.counts()[2],1)
        self.assertEqual(self.reports.publish_campaign('campaign-progress','btc',[self.dataset_id],publication=partial(5)),complete)

    def test_multiple_publication_batches_commit_all_observations(self):
        import services.research.reports as model
        prepared=prepare_report('btc',[dataset()],latest_ids=[1])
        rows=json.loads(prepared.observations_json)
        self.assertGreater(len(rows),1)
        payload=json.loads(prepared.payload_json)
        payload['datasets']=[dict(id=self.dataset_id,latest=True)]
        changed=replace(prepared,payload_json=json.dumps(payload))
        with patch.object(model,'PUBLICATION_BATCH_ROWS',1):
            result=self.reports._save('batched-results','btc',changed)
        self.assertEqual(self.counts(),(1,1,len(rows)))
        with self.store.pool.connection() as c:
            saved=c.execute('SELECT observation FROM research_observation WHERE result_id=%s ORDER BY minute',(result,)).fetchall()
        self.assertEqual([r['observation'] for r in saved],sorted(rows,key=lambda r:r['minutes_before_close']))

    def test_failed_or_unknown_membership_cannot_publish_partial_report(self):
        with self.assertRaises(EvidenceConflict):self.reports.publish('btc-results','btc',[self.dataset_id,999999999],latest_ids=[])
        with self.assertRaises(ValueError):self.reports.publish('btc-results','btc',[self.dataset_id],latest_ids=[999999999])
        self.assertEqual(self.counts(),(0,0,0))

    def test_concurrent_retry_does_not_duplicate_report_or_observations(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            ids=list(executor.map(lambda _:self.reports.publish('btc-results','btc',[self.dataset_id],latest_ids=[self.dataset_id]),range(8)))
        self.assertEqual(len(set(ids)),1)
        self.assertEqual(self.counts()[0:2],(1,1))

    def test_result_membership_and_observations_are_immutable(self):
        self.reports.publish('btc-results','btc',[self.dataset_id],latest_ids=[self.dataset_id])
        self.assertEqual(self.counts(),(1,1,1))
        for table in ('research_result','research_result_dataset','research_observation'):
            with self.assertRaises(psycopg.Error):
                with self.store.pool.connection() as c:c.execute('DELETE FROM '+table)
        self.assertEqual(self.counts(),(1,1,1))

    def test_mid_publication_failure_rolls_back_result_membership_and_observations(self):
        import services.research.reports as model
        original=model.prepare_report
        def duplicate(*args,**kwargs):
            prepared=original(*args,**kwargs)
            rows=json.loads(prepared.observations_json)
            self.assertTrue(rows)
            rows=rows+rows
            payload=json.loads(prepared.payload_json)
            return replace(prepared,observations_json=json.dumps(rows),fingerprint=digest(dict(report=payload,observations=rows)))
        with patch.object(model,'prepare_report',side_effect=duplicate),patch.object(model,'PUBLICATION_BATCH_ROWS',1):
            with self.assertRaises(psycopg.Error):
                self.reports.publish('btc-results','btc',[self.dataset_id],latest_ids=[self.dataset_id])
        self.assertEqual(self.counts(),(0,0,0))

    def test_committed_versions_reject_late_child_insertions(self):
        result=self.reports.publish('btc-results','btc',[self.dataset_id],latest_ids=[self.dataset_id])
        attempts=[
            ("INSERT INTO research_observation VALUES(%s,'2026-10-25','late-new-ticker',1,'{}'::jsonb)",(result,)),
            ('INSERT INTO research_result_dataset VALUES(%s,%s,false)',(result,self.dataset_id)),
            ("INSERT INTO research_summary VALUES(%s,'late','{}'::jsonb)",(self.dataset_id,)),
            ("INSERT INTO research_dataset_artifact VALUES(%s,'late-missing-object')",(self.dataset_id,))]
        for sql,args in attempts:
            with self.assertRaisesRegex(psycopg.Error,'sealed'):
                with self.store.pool.connection() as c:c.execute(sql,args)
        self.assertEqual(self.counts(),(1,1,1))


class ObservationBatchTests(unittest.TestCase):
    def test_large_observation_array_roundtrips_in_bounded_batches(self):
        from services.research.reports import observation_batches
        rows=[dict(ticker=f'ticker-{i}',note='quote \" and unicode Ω',minute=i%15) for i in range(2501)]
        encoded=json.dumps(rows,sort_keys=True,separators=(',',':'))
        batches=list(observation_batches(encoded))
        self.assertEqual([len(batch) for batch in batches],[1000,1000,501])
        self.assertEqual([row for batch in batches for row in batch],rows)
        self.assertEqual(list(observation_batches('[]')),[])
        for bad in ('{}','[1]','[{},]','[{}{}]'):
            with self.assertRaises(ValueError):list(observation_batches(bad))
