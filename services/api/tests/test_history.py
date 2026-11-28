"""History contract, authorization/keysets and real-Postgres precomputed reads."""
from copy import deepcopy
from datetime import datetime,timezone
import json
import os
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from services.api.app import create_app,SESSION,digest
from services.api.config import Settings
from services.api.history import Cursors,Detail
from services.api.manage import migrate
from services.api.store import PostgresStore
from services.research.datasets import DatasetStore
from services.research.history import HistoryStore
from services.research.reports import ReportStore,prepare_report
from test_datasets import Fixture
from test_reports import dataset
from test_routes import MemoryStore

URL=os.environ.get('POCKET_TEST_DATABASE_URL')
SETTINGS=Settings('https://app.test','client','postgresql://unused','x'*32,owner_subject='owner')
STAMP=datetime(2026,10,27,tzinfo=timezone.utc)


def detail():
    p=json.loads(prepare_report('btc',[dataset()],latest_ids=[1]).payload_json)
    return dict(id='1',fingerprint='a'*64,published_at=STAMP,
        **{k:p[k] for k in ('model_version','asset','latest_membership_known','source_commit','entry_minutes','price_bands','execution_included','baseline_fees_cents','exit_cost_stress_cents')},
        summary={k:p['historical'][k] for k in ('candidate_count','observation_count','first_date','last_date')},cells=p['historical']['cells'])


class FakeHistory:
    def __init__(self):self.calls=[];self.row=detail()
    def results(self,stream,**kwargs):
        self.calls.append((stream,kwargs))
        base={k:self.row[k] for k in ('id','fingerprint','published_at','model_version','asset','latest_membership_known')}
        return [{**base,'id':str(i),'dataset_count':1,'historical':self.row['summary'],'latest':self.row['summary']}
                for i in (3,2,1) if kwargs['before'] is None or i<kwargs['before']][:kwargs['limit']]
    def result(self,stream,identifier,**kwargs):
        self.calls.append((stream,identifier,kwargs))
        return self.row if identifier==1 else None
    def members(self,stream,identifier,**kwargs):return [] if identifier==1 else None
    def datasets(self,stream,**kwargs):return []
    def windows(self,stream,identifier,**kwargs):
        if identifier!=1:return None
        return [dict(id=str(i),dataset_id='9007199254740993',start_at=STAMP,end_at=STAMP.replace(day=28)) for i in (3,2,1) if kwargs['before'] is None or i<kwargs['before']][:kwargs['limit']]


def client(history):
    auth=MemoryStore();token='t'*43
    auth.sessions[digest(token)]={'csrf_hash':'c'*64,'display_email':'owner@example.test'}
    c=TestClient(create_app(SETTINGS,auth,history_store=history),base_url='https://app.test',headers={'x-pocket-proxy':'x'*32})
    c.cookies.set(SESSION,token)
    return c,auth


class HistoryTests(unittest.TestCase):
    def setUp(self):self.history=FakeHistory();self.client,self.auth=client(self.history)
    def tearDown(self):self.client.close()
    def test_proxy_and_live_owner_session_required_before_any_history_query(self):
        for path in ('datasets','results','results/1?view=latest','results/1/datasets','results/1/coverage'):
            url='/research/'+path+('&' if '?' in path else '?')+'stream=btc'
            self.assertEqual(self.client.get(url,headers={'x-pocket-proxy':'wrong'}).status_code,403)
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/research/results?stream=btc').status_code,401)
        self.assertFalse(self.history.calls)

    def test_keyset_pages_bound_to_stream_route_and_parent_not_page_size(self):
        first=self.client.get('/research/results?stream=btc&limit=1').json()
        self.assertEqual([r['id'] for r in first['items']],['3'])
        token=first['next_cursor']
        second=self.client.get('/research/results',params={'stream':'btc','limit':2,'cursor':token}).json()
        self.assertEqual([r['id'] for r in second['items']],['2','1'])
        self.assertIsNone(second['next_cursor'])
        for path,stream in (('results','eth'),('datasets','btc'),('results/1/datasets','btc')):
            self.assertEqual(self.client.get('/research/'+path,params={'stream':stream,'cursor':token}).status_code,422)
        forged=token[:10]+('A' if token[10]!='A' else 'B')+token[11:]
        self.assertEqual(self.client.get('/research/results',params={'stream':'btc','cursor':forged}).status_code,422)
        c=Cursors('x'*32);token=c.encode(['members','btc','1'],4)
        with self.assertRaises(Exception):c.decode(token,['members','btc','2'])
        with self.assertRaises(Exception):Cursors('y'*32).decode(token,['members','btc','1'])

    def test_coverage_windows_are_bounded_parent_scoped_readonly_pages(self):
        first=self.client.get('/research/results/1/coverage?stream=category-btc&limit=1').json()
        self.assertEqual([r['id'] for r in first['items']],['3'])
        self.assertEqual(first['items'][0]['dataset_id'],'9007199254740993')
        second=self.client.get('/research/results/1/coverage',params={'stream':'category-btc','cursor':first['next_cursor']}).json()
        self.assertEqual([r['id'] for r in second['items']],['2','1'])
        self.assertEqual(self.client.get('/research/results/2/coverage',params={'stream':'category-btc','cursor':first['next_cursor']}).status_code,422)
        self.assertEqual(self.client.get('/research/results/99/coverage?stream=category-btc').status_code,404)
        self.assertEqual(self.client.get('/research/results/1/datasets',params={'stream':'category-btc','cursor':first['next_cursor']}).status_code,422)

    def test_unknown_duplicate_and_unbounded_queries_fail_without_echo(self):
        for suffix in ('','?stream=btc&stream=eth','?stream=btc&limit=51','?stream=btc&limit=-1','?stream=btc&limit=1.2',
                       '?stream=btc&cursor=private-sentinel!','?stream=btc&day=private-sentinel','?stream=bad%20stream'):
            r=self.client.get('/research/results'+suffix)
            self.assertEqual(r.status_code,422);self.assertNotIn('private-sentinel',r.text)
        for identifier in ('0','-1','01','9223372036854775808'):
            self.assertEqual(self.client.get(f'/research/results/{identifier}?stream=btc&view=latest').status_code,422)
        self.assertFalse(self.history.calls)

    def test_explicit_view_missing_result_empty_members_and_read_only_methods(self):
        self.assertEqual(self.client.get('/research/results/1?stream=btc').status_code,422)
        self.assertEqual(self.client.get('/research/results/1?stream=btc&view=cumulative').status_code,422)
        self.assertEqual(self.client.get('/research/results/99?stream=btc&view=latest').status_code,404)
        self.assertEqual(self.client.get('/research/results/99/datasets?stream=btc').status_code,404)
        self.assertEqual(self.client.get('/research/results/1/datasets?stream=btc').json()['items'],[])
        self.assertEqual(self.client.post('/research/results?stream=btc',json={}).status_code,405)

    def test_precomputed_cells_keep_full_sample_labels_and_never_invoke_builders(self):
        with patch('services.research.reports.prepare_report',side_effect=AssertionError('GET computed report')):
            r=self.client.get('/research/results/1?stream=btc&view=historical')
        self.assertEqual(r.status_code,200)
        item=r.json()['result'];self.assertEqual(item['cells'],json.loads(Detail.model_validate(self.history.row).model_dump_json())['cells'])
        self.assertEqual(item['cells'][0]['hold']['sampled_markets'],item['cells'][0]['loss_prevention']['sampled_markets'])
        self.assertEqual(item['cells'][0]['loss_prevention']['sell_label'],'Trade not recommended')
        self.assertNotIn('email',r.text);self.assertNotIn('policy_cells',r.text)
        self.assertEqual(r.headers['cache-control'],'no-store')

    def test_corrupt_or_future_stored_contract_fails_closed(self):
        original=deepcopy(self.history.row)
        for modify in (
            lambda r:r.update(asset='future'),lambda r:r.update(private='private-sentinel'),
            lambda r:r['cells'][0]['loss_prevention'].update(sampled_markets=0),
            lambda r:r['cells'][0]['loss_prevention'].update(sell_label='Sell ≤ 50¢'),
            lambda r:r['cells'][0]['hold'].update(hypothetical_roi_percent=float('nan')),
            lambda r:r.update(cells=None)):
            self.history.row=deepcopy(original);modify(self.history.row)
            r=self.client.get('/research/results/1?stream=btc&view=historical')
            self.assertEqual(r.status_code,503);self.assertNotIn('private-sentinel',r.text)
        self.history.row=original;self.history.row['latest_membership_known']=False
        self.assertEqual(self.client.get('/research/results/1?stream=btc&view=latest').status_code,503)


@unittest.skipUnless(URL,'Requires disposable pocket_test PostgreSQL')
class HistoryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path!='/pocket_test':raise RuntimeError('Requires disposable pocket_test database')
        migrate(URL);cls.db=PostgresStore(URL);cls.db.open()
    @classmethod
    def tearDownClass(cls):cls.db.close()
    def setUp(self):
        with self.db.pool.connection() as c:
            c.execute('TRUNCATE research_result_dataset,research_observation,research_result,research_dataset_artifact,research_summary,research_dataset,research_artifact CASCADE')
        self.datasets=DatasetStore(self.db.pool);self.reports=ReportStore(self.db.pool)
        self.history=HistoryStore(self.db.pool);self.client,_=client(self.history)
        self.ids=[self.datasets.publish('raw',Fixture(price=price).prepare()) for price in ('0.88','0.89','0.90')]
        self.results=[self.reports.publish('results','btc',[i],latest_ids=[i]) for i in self.ids]
    def tearDown(self):self.client.close()
    def test_real_sql_keysets_stream_isolation_and_no_raw_data_in_pages(self):
        r=self.client.get('/research/datasets?stream=raw&limit=2');self.assertEqual(r.status_code,200)
        p=r.json();self.assertEqual([r['id'] for r in p['items']],[str(i) for i in reversed(self.ids[1:])])
        self.assertNotIn('payload',r.text);self.assertNotIn('artifacts',r.text)
        p=self.client.get('/research/datasets',params={'stream':'raw','cursor':p['next_cursor']}).json()
        self.assertEqual([r['id'] for r in p['items']],[str(self.ids[0])]);self.assertIsNone(p['next_cursor'])
        self.assertEqual(self.client.get('/research/datasets?stream=other').json()['items'],[])
        r=self.client.get('/research/results?stream=results&limit=1');self.assertEqual(r.status_code,200)
        p=r.json();self.assertEqual(p['items'][0]['id'],str(self.results[-1]))
        self.assertNotIn('cells',r.text);self.assertNotIn('missing_entry_slots',r.text)
        older=self.client.get('/research/results',params={'stream':'results','cursor':p['next_cursor']}).json()
        self.assertEqual([r['id'] for r in older['items']],[str(i) for i in reversed(self.results[:-1])])

    def test_exact_membership_dates_unknown_latest_and_precomputed_view(self):
        result=self.results[0];url=f'/research/results/{result}'
        r=self.client.get(url+'?stream=results&view=historical');self.assertEqual(r.status_code,200)
        with self.db.pool.connection() as c:
            p=c.execute('SELECT report FROM research_result WHERE id=%s',(result,)).fetchone()['report']
            day=c.execute('SELECT day::text AS day FROM research_dataset WHERE id=%s',(self.ids[0],)).fetchone()['day']
        self.assertEqual(r.json()['result']['cells'],p['historical']['cells'])
        members=self.client.get(url+'/datasets?stream=results').json()
        self.assertEqual(members['items'],[dict(id=str(self.ids[0]),fingerprint=p['datasets'][0]['fingerprint'],day=day,is_latest=True,summary=json.loads(Fixture(price='0.88').prepare().summary_json))])
        for suffix in ('?stream=other&view=latest','/datasets?stream=other'):
            self.assertEqual(self.client.get(url+suffix).status_code,404)
        unknown=self.reports.publish('results','btc',[self.ids[0]],latest_ids=None)
        r=self.client.get(f'/research/results/{unknown}?stream=results&view=latest')
        self.assertEqual(r.status_code,200);self.assertFalse(r.json()['result']['latest_membership_known'])
        self.assertEqual(r.json()['result']['cells'],[]);self.assertIsNone(r.json()['result']['summary']['candidate_count'])

    def test_multi_dataset_membership_uses_relation_keyset_not_raw_or_observation_scan(self):
        # Empty raw versions may cover the same day: they contain no overlapping candidates.
        ids=[self.datasets.publish(s,Fixture(empty=True).prepare()) for s in ('empty-a','empty-b','empty-c')]
        result=self.reports.publish('empty','btc',ids,latest_ids=[ids[1]])
        path=f'/research/results/{result}/datasets'
        first=self.client.get(path+'?stream=empty&limit=1').json()
        rest=self.client.get(path,params={'stream':'empty','cursor':first['next_cursor']}).json()
        members=first['items']+rest['items']
        self.assertEqual([int(m['id']) for m in members],list(reversed(ids)))
        self.assertEqual([int(m['id']) for m in members if m['is_latest']],[ids[1]])
        self.assertIsNone(rest['next_cursor'])

    def test_bigint_history_orders_numerically_and_preserves_browser_precision(self):
        # Exercise IDs spanning a decimal digit boundary and exceeding JS safe integer range.
        with self.db.pool.connection() as c:
            c.execute("SELECT setval(pg_get_serial_sequence('research_result','id'),9999999999999999,true)")
        newer=self.reports.publish('big','btc',[self.ids[1]],latest_ids=[])
        with self.db.pool.connection() as c:
            c.execute("SELECT setval(pg_get_serial_sequence('research_result','id'),9999999999999998,true)")
        older=self.reports.publish('big','btc',[self.ids[0]],latest_ids=[])
        self.assertLess(older,newer)
        first=self.client.get('/research/results?stream=big&limit=1').json()
        self.assertEqual(first['items'][0]['id'],str(newer))
        rest=self.client.get('/research/results',params={'stream':'big','cursor':first['next_cursor']}).json()
        self.assertEqual([r['id'] for r in rest['items']],[str(older)])
        with self.db.pool.connection() as c:
            c.execute("SELECT setval(pg_get_serial_sequence('research_result','id'),(SELECT max(id) FROM research_result),true)")
