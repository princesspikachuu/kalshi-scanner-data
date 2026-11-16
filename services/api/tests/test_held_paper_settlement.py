"""Paper payouts never replay queued fills and commit with their audit trail."""
from copy import deepcopy
from decimal import Decimal as D
import io
import os
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from services.demo import held_paper_settlement as h
from services.demo.maintenance import put_verified
from services.paper_demo.shadow.core import Engine, FeePolicy, Lot, Order
from services.paper_demo.shadow.state import encode
from services.paper_demo.shadow.checkpoint_codec import pack_checkpoint, unpack_checkpoint


class Objects:
    bucket = 'test-only'
    def __init__(self):
        self.data = {};self.client = self
    def put_object(self, **kwargs):
        self.data[kwargs['Key']] = kwargs['Body']
    def get_object(self, **kwargs):
        value = self.data[kwargs['Key']]
        return dict(ContentLength=len(value), Body=io.BytesIO(value))


def environment():
    return dict(MT_STORAGE_RECOVERY_HOLD='true', COLLECTION_ENABLED='false',
                RUNTIME_DB_PROFILE='research', WORKER_ROLE='collector',
                MT_CONTROL_BACKUP_HELD_WORKER='true', MT_CONTROL_BACKUP_V2_ENABLED='true',
                MT_DIAGNOSTIC_RETENTION_HELD_WORKER='false', MT_DIAGNOSTIC_RETENTION_ENABLED='false')


def fixture():
    now = time.time();ticker = 'HELD-' + uuid4().hex
    engine = Engine(Mock(), cash='98.78');engine.now = now-20
    engine.add_market(dict(ticker=ticker, close=now-10), FeePolicy())
    engine.add_market(dict(ticker='OPEN', close=now+1000), FeePolicy())
    engine.wallet.deposits = D('100')
    engine.wallet.lots = [Lot('lot-1',ticker,'yes',D('2'),D('.40'),D('.02'),1),
                          Lot('lot-2',ticker,'no',D('1'),D('.40'),D('0'),1)]
    engine.wallet.stat(ticker).fees_paid = D('.02')
    engine.wallet.stat('OPEN').valid = True
    for ident, market in [('due',ticker), ('unrelated','OPEN')]:
        engine.orders[ident] = Order(ident,market,'yes','buy',D('1'),D('.3'),False,
                                    1,now-25,now-15,now+100,None,reserved=D('.3'))
    engine.pending = [(now-15,1,'arrive','due'),(now-15,2,'arrive','unrelated')]
    state = h.frozen(encode(engine, SimpleNamespace(bots={})))
    state['unknown_extension'] = {'preserve':[1,'verbatim']}
    state['experiments'] = {'_model':{'preserve':True},
        'paused':{'engine':deepcopy(state), 'strategies':{'pause':'unchanged'}}}
    outcomes = {ticker:dict(ticker=ticker,status='finalized',result='yes',fetched_at=now)}
    return pack_checkpoint(state,binary=True), outcomes, now, ticker


def evidence(objects, before, plan):
    checkpoint = put_verified(objects,'backups/test',dict(progress=before))
    reconciliation = put_verified(objects,'backups/test',dict(
        format='current-paper-financial-reconciliation-v1',financial_state_changed=False,
        venue=dict(recorded_outcome_mismatches=0,recorded_outcomes_not_final=0),
        checkpoint_reference=checkpoint,replay={'test':dict(replay_matches_checkpoint=True,
                                              recorded_fees_match_saved_totals=True)}))
    return put_verified(objects,'backups/test',dict(format='held-paper-settlement-evidence-v1',
            before=before,plan=plan,reconciliation_reference=reconciliation))


class HeldSettlementTests(unittest.TestCase):
    def test_payouts_fees_unknown_state_and_pauses_survive_without_pending_fills(self):
        before, outcomes, now, ticker = fixture();original = deepcopy(before)
        plan = h.build_plan(before,outcomes,now=now)
        self.assertEqual(before,original)
        after = unpack_checkpoint(plan['proposed']);old = unpack_checkpoint(before)
        for state in (after, after['experiments']['paused']['engine']):
            self.assertEqual(state['wallet']['cash'],'100.78')
            self.assertEqual(state['wallet']['deposits'],'100')
            self.assertEqual(state['wallet']['lots'],[])
            self.assertEqual(state['wallet']['stats'][ticker]['realized_fees'],'0.02')
            self.assertEqual(state['wallet']['stats'][ticker]['fees_paid'],'0.02')
            self.assertFalse(state['wallet']['stats'][ticker]['valid'])
            self.assertTrue(state['markets'][ticker]['paid'])
            self.assertEqual(state['orders']['due']['status'],'cancelled')
            self.assertEqual(state['orders']['unrelated'],old['orders']['unrelated'])
            self.assertEqual(state['pending'],[old['pending'][1]])
            self.assertEqual(state['unknown_extension'],old['unknown_extension'])
            self.assertEqual(state['wallet']['stats']['OPEN'],old['wallet']['stats']['OPEN'])
        self.assertEqual(after['experiments']['paused']['strategies'],{'pause':'unchanged'})
        self.assertFalse(any(e['event']=='FILL' for e in plan['events']))
        self.assertEqual(sum(e['event']=='SETTLED' for e in plan['events']),2)
        self.assertEqual(sum(e['event']=='CYCLE_REPORT' for e in plan['events']),2)
        self.assertEqual(plan,h.build_plan(before,outcomes,now=now))

    def test_wrong_missing_extra_unfinalized_stale_or_future_outcomes_fail(self):
        before, outcomes, now, ticker = fixture()
        for bad in ({},dict(outcomes,EXTRA={}),{ticker:dict(outcomes[ticker],ticker='WRONG')},
                    {ticker:dict(outcomes[ticker],status='determined')},
                    {ticker:dict(outcomes[ticker],result='')},
                    {ticker:dict(outcomes[ticker],fetched_at=now-301)},
                    {ticker:dict(outcomes[ticker],fetched_at=now+6)}):
            with self.subTest(outcome=bad),self.assertRaises(ValueError):
                h.build_plan(before,bad,now=now)

    def test_paid_inventory_and_regressed_time_fail(self):
        before,outcomes,now,ticker=fixture();state=unpack_checkpoint(before)
        state['markets'][ticker]['paid']=True
        with self.assertRaisesRegex(ValueError,'paid_market'):
            h.build_plan(state,outcomes,now=now)
        with self.assertRaises(ValueError):h.pending_markets(before,now-100)

    def test_evidence_corruption_rebuild_mismatch_and_unsafe_env_never_open_sql(self):
        before,outcomes,now,ticker=fixture();plan=h.build_plan(before,outcomes,now=now)
        objects=Objects();ref=evidence(objects,before,plan);connection=Mock()
        for env in ({},dict(environment(),MT_STORAGE_RECOVERY_HOLD='false'),
                    dict(environment(),RECOVERY_DATABASE_URL='forbidden')):
            with self.assertRaises(ValueError):h.commit_plan(connection,objects,plan,before,ref,env=env)
        tampered=deepcopy(plan);tampered['events']=[]
        bad_ref=evidence(objects,before,tampered)
        with self.assertRaisesRegex(ValueError,'rebuild'):
            h.commit_plan(connection,objects,tampered,before,bad_ref,env=environment())
        objects.data[ref['key']]=b'broken'
        with self.assertRaises(Exception):h.commit_plan(connection,objects,plan,before,ref,env=environment())
        connection.execute.assert_not_called()

    def test_complete_settlement_is_idempotent_without_clock_advance(self):
        before,outcomes,now,ticker=fixture();engine=Engine(Mock())
        from services.paper_demo.shadow.state import restore
        restore(engine,SimpleNamespace(bots={},halted=set(),owner=lambda _:None),unpack_checkpoint(before))
        engine.report=Mock();engine.advance=Mock(side_effect=AssertionError('must not advance'))
        with self.assertRaises(ValueError):engine.complete_settlement(ticker,D(1))
        engine.settled.add(ticker)
        engine.complete_settlement(ticker,D(1));cash=engine.wallet.cash
        engine.complete_settlement(ticker,D(1))
        self.assertEqual(engine.wallet.cash,cash);engine.report.assert_called_once()
        engine.advance.assert_not_called()


URL=os.environ.get('POCKET_TEST_DATABASE_URL')


@unittest.skipUnless(URL,'Requires disposable pocket_test PostgreSQL')
class HeldSettlementPostgresTests(unittest.TestCase):
    def setUp(self):
        from urllib.parse import urlparse
        if urlparse(URL).path!='/pocket_test':raise RuntimeError('Disposable pocket_test only')
        from services.api.manage import migrate
        migrate(URL)
        self.before,self.outcomes,self.now,self.ticker=fixture()
        self.plan=h.build_plan(self.before,self.outcomes,now=self.now)
        self.objects=Objects();self.ref=evidence(self.objects,self.before,self.plan)
        self.connection=psycopg.connect(URL,autocommit=True)
        self.key='demo/shadow/checkpoint/test-'+uuid4().hex
        self.checkpoint_patch=patch.object(h,'CHECKPOINT',self.key);self.checkpoint_patch.start()
        def test_database(c):
            self.assertEqual(c.execute('SELECT current_database()').fetchone()[0],'pocket_test')
        self.role_patch=patch.object(h,'validate_runtime',side_effect=test_database);self.role_patch.start()
        self.before_ids={r[0] for r in self.connection.execute('SELECT id FROM research_job').fetchall()}
        self.connection.execute("INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status) VALUES(%s,'crypto','{}',%s,%s,'succeeded')",
                                (uuid4(),Jsonb(self.before),self.key))

    def tearDown(self):
        # Only disposable test-owned rows; no production connection is accepted.
        for ident, in self.connection.execute('SELECT id FROM research_job').fetchall():
            if ident not in self.before_ids:self.connection.execute('DELETE FROM research_job WHERE id=%s',(ident,))
        self.role_patch.stop();self.checkpoint_patch.stop();self.connection.close()

    def apply(self,connection=None):
        return h.commit_plan(connection or self.connection,self.objects,self.plan,self.before,self.ref,env=environment())

    def saved(self):
        return self.connection.execute('SELECT progress FROM research_job WHERE idempotency_key=%s',(self.key,)).fetchone()[0]

    def test_checkpoint_financial_audits_reports_and_receipt_commit_once(self):
        result=self.apply();self.assertFalse(result['already_applied'])
        self.assertEqual(self.saved(),self.plan['proposed'])
        count=self.connection.execute('SELECT count(*) FROM research_job').fetchone()[0]
        self.assertTrue(self.apply()['already_applied'])
        self.assertEqual(count,self.connection.execute('SELECT count(*) FROM research_job').fetchone()[0])
        for folder in ('convexity','paused'):
            key=('demo/shadow/report/' if folder=='convexity' else 'demo/experiment/report/paused/')+self.ticker
            report=self.connection.execute('SELECT progress FROM research_job WHERE idempotency_key=%s',(key,)).fetchone()[0]
            self.assertTrue(report['final']);self.assertFalse(report['data_valid'])
        self.assertEqual(self.connection.execute("SELECT count(*) FROM research_job WHERE progress->>'event'='SETTLED' AND progress->>'ticker'=%s",(self.ticker,)).fetchone()[0],2)

    def test_concurrent_checkpoint_edit_or_runtime_fence_prevents_payout(self):
        with psycopg.connect(URL,autocommit=True) as other:
            other.execute('SELECT pg_advisory_lock(%s)',(h.RUNTIME_LOCK,))
            with self.assertRaisesRegex(ValueError,'fence_busy'):self.apply()
            other.execute('SELECT pg_advisory_unlock(%s)',(h.RUNTIME_LOCK,))
        self.assertEqual(self.saved(),self.before)
        changed=dict(self.before,operator_marker='preserve')
        self.connection.execute('UPDATE research_job SET progress=%s WHERE idempotency_key=%s',(Jsonb(changed),self.key))
        with self.assertRaisesRegex(ValueError,'checkpoint_changed'):self.apply()
        self.assertEqual(self.saved(),changed)

    def test_insert_failure_rolls_back_payout_and_all_new_audits(self):
        real=self.connection
        class Failure:
            autocommit=True
            info=real.info
            transaction=real.transaction
            def execute(self,sql,args=None):
                if sql.startswith('INSERT'):raise RuntimeError('injected audit insert failure')
                return real.execute(sql,args)
        count=real.execute('SELECT count(*) FROM research_job').fetchone()[0]
        with self.assertRaisesRegex(RuntimeError,'audit insert failure'):self.apply(Failure())
        self.assertEqual(self.saved(),self.before)
        self.assertEqual(real.execute('SELECT count(*) FROM research_job').fetchone()[0],count)

    def test_existing_final_report_is_never_overwritten_to_force_acceptance(self):
        key='demo/shadow/report/'+self.ticker
        self.connection.execute("INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status) VALUES(%s,'crypto','{}',%s,%s,'succeeded')",
                                (uuid4(),Jsonb(dict(final=True,preserve='original')),key))
        with self.assertRaisesRegex(ValueError,'final_report_conflict'):self.apply()
        self.assertEqual(self.saved(),self.before)
        self.assertEqual(self.connection.execute('SELECT progress FROM research_job WHERE idempotency_key=%s',(key,)).fetchone()[0],
                         dict(final=True,preserve='original'))
