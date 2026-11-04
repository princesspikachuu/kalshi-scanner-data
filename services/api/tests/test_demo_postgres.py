"""Actual database/API checks using the same disposable database as other tests."""
import os,unittest
from urllib.parse import urlsplit
from unittest.mock import patch
from fastapi.testclient import TestClient
from services.api.app import create_app,CSRF
from services.api.config import Settings
from services.api.auth_policy import GoogleIdentity
from services.api.store import PostgresStore
from services.api.manage import migrate
from services.demo.store import DemoStore
from services.api.tests.test_demo_engine import config
URL=os.environ.get('POCKET_TEST_DATABASE_URL')
@unittest.skipUnless(URL,'Disposable PostgreSQL is required')
class DemoPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path!='/pocket_test':raise RuntimeError('Use disposable pocket_test only')
        migrate(URL);cls.store=PostgresStore(URL);cls.store.open();cls.demo=DemoStore(cls.store.pool)
    @classmethod
    def tearDownClass(cls):cls.store.close()
    def setUp(self):
        with self.store.pool.connection() as c:c.execute("TRUNCATE owner_session,owner_account,login_challenge,login_rate,research_job CASCADE")
        settings=Settings('https://app.test','client',URL,'x'*32,owner_email='owner@gmail.com')
        self.client=TestClient(create_app(settings,self.store,lambda **_:GoogleIdentity('owner','owner@gmail.com',True)),base_url='https://app.test',headers={'X-Pocket-Proxy':'x'*32,'Origin':'https://app.test'})
        challenge=self.client.get('/auth/challenge').json();self.client.post('/auth/google',json=dict(credential='opaque',nonce=challenge['nonce'],csrf_token=challenge['csrf_token']))
        self.client.headers['x-csrf-token']=self.client.cookies[CSRF]
    def tearDown(self):self.client.close()
    def test_cycle_direction_uses_closed_fills_and_all_bot_revisions(self):
        for key,ticker,side,filled,kind in [('yes','t','yes',2,'entry'),('zero','t','no',0,'entry'),
                ('exit','t','no',3,'exit'),('both-yes','both','yes',1,'entry'),('both-no','both','no',1,'entry')]:
            self.demo.put('order/'+key,dict(status='closed',filled=filled,remaining=0),
                parameters=dict(ticker=ticker,side=side,kind=kind,entry_strategy='buy_low_sell_high',revision=1))
        self.assertEqual(self.demo.filled_cycle_sides({'t','both','new'}),{'t':'yes','both':'both'})
        self.assertEqual(self.demo.filled_cycle_sides(set()),{})
    def test_multi_square_bot_revision_and_archive_without_history_mutation(self):
        body=config();body['squares'].append(dict(body['squares'][0],min_price=80,max_price=89))
        result=self.client.post('/demo/bots',json=body);self.assertEqual(result.status_code,200,result.text);identifier=result.json()['id']
        page=self.client.get('/demo/workspace');self.assertEqual(page.status_code,200,page.text)
        bot=page.json()['bots'][0];self.assertEqual(bot['key'],identifier);self.assertEqual(len(bot['config']['squares']),2);self.assertEqual(bot['desired'],'paused')
        self.assertEqual(self.client.post('/demo/bots/'+identifier+'/control',json=dict(action='resume',revision=1)).status_code,200)
        body['adjustment_cents']=-2
        self.demo.put('health',dict(state='ready',features=['editable_rules_v1']))
        self.assertEqual(self.client.post('/demo/bots/'+identifier+'/configure',json=body).status_code,200)
        saved=self.client.get('/demo/workspace').json()['bots'][0]
        self.assertEqual((saved['revision'],saved['desired']),(2,'running'))
        self.assertEqual(self.client.post('/demo/bots/'+identifier+'/control',json=dict(action='pause',revision=1)).status_code,409)
        self.assertEqual(self.client.post('/demo/bots/'+identifier+'/control',json=dict(action='pause',revision=2)).status_code,200)
    def test_order_detail_follows_exact_parent_after_closure_and_rejects_cross_lot_links(self):
        from uuid import uuid4
        bot=str(uuid4());buy=str(uuid4());sell=str(uuid4());other=str(uuid4())
        entry=dict(client_id=buy,kind='entry',bot=bot,ticker='T',side='yes',price=3,quantity=5,created_at=1000)
        self.demo.put('order/'+buy,dict(status='closed',filled=5,remaining=0),parameters=entry)
        child=dict(client_id=sell,parent=buy,kind='exit',bot=bot,ticker='T',side='yes',exit_role='profit',price=6,quantity=5,created_at=1001)
        self.demo.put('order/'+sell,dict(status='resting',filled=1,remaining=4),parameters=child)
        self.demo.put('order/'+other,dict(status='closed',filled=5,remaining=0),parameters=dict(child,client_id=other,parent=str(uuid4())))
        self.demo.event('settlement','Verified',bot=bot,details=dict(client_id=buy,side='yes',quote=dict(result='yes')))
        for selected in (buy,sell):
            response=self.client.get('/demo/orders?client_id='+selected);self.assertEqual(response.status_code,200,response.text)
            data=response.json();self.assertEqual(data['entry']['client_id'],buy)
            self.assertEqual([o['client_id'] for o in data['exits']],[sell]);self.assertEqual(data['selected'],selected)
            self.assertEqual(data['settlement']['details']['quote']['result'],'yes')
        self.demo.put('order/'+sell,dict(status='resting',filled=1,remaining=4),parameters=dict(child,side='no'))
        self.assertEqual(self.client.get('/demo/orders?client_id='+buy).status_code,409)
        self.assertEqual(self.client.get('/demo/orders?client_id='+str(uuid4())).status_code,404)
        self.assertEqual(self.client.get('/demo/orders?client_id=bad').status_code,422)
        self.client.cookies.clear();self.assertEqual(self.client.get('/demo/orders?client_id='+buy).status_code,401)
    def test_activity_combines_event_types_without_crossing_bot_or_market_filters(self):
        from uuid import uuid4
        daily=str(uuid4());sports=str(uuid4())
        for bot,ticker,kind in [(daily,'WEATHER','fill'),(daily,'WEATHER','settlement'),(daily,'WEATHER','order'),(sports,'SPORTS','fill'),(daily,'OTHER','settlement')]:
            self.demo.event(kind,'Saved',bot=bot,ticker=ticker)
        response=self.client.get('/demo/activity?bot='+daily+'&ticker=WEATHER&kind=fill,settlement')
        self.assertEqual(response.status_code,200,response.text)
        rows=response.json()['items'];self.assertEqual({r['kind'] for r in rows},{'fill','settlement'})
        self.assertEqual(len(rows),2);self.assertTrue(all(r['bot']==daily and r['ticker']=='WEATHER' for r in rows))
        self.assertEqual(self.client.get('/demo/activity?kind=fill,,settlement').status_code,422)
    def test_low_high_time_grid_uses_standard_windows_entry_prices_and_last_hour_filter(self):
        from uuid import uuid4
        from types import SimpleNamespace
        self.demo.put('health',dict(state='ready',features=['buy_low_sell_high_v1']))
        bot=self.client.post('/demo/bots',json=config(strategy='buy_low_sell_high',cycle_buy_cents=3,cycle_sell_cents=6)).json()['id']
        now=1800000000
        for minutes,price in [(12,3),(7,3),(4,3),(2,1),(.5,1)]:
            key=str(uuid4());at=now-120
            self.demo.put('order/'+key,dict(status='closed',filled=1,remaining=0,realized_cents=2),parameters=dict(client_id=key,bot=bot,kind='entry',revision=1,square=0,entry_strategy='buy_low_sell_high',price=price,created_at=at,market_close_at=at+minutes*60))
        self.demo.put('order/older',dict(status='closed',filled=1,remaining=0,realized_cents=100),parameters=dict(bot=bot,kind='entry',revision=1,price=3,created_at=now-7200,market_close_at=now-6300))
        with patch('services.api.demo_performance.time',SimpleNamespace(time=lambda:now)):
            response=self.client.get('/demo/performance?bot='+bot+'&group=time_price&period=1H')
        self.assertEqual(response.status_code,200,response.text)
        data=response.json();self.assertEqual(data['time_bounds'],[1,3,5,10,15])
        self.assertEqual({r['bucket'] for r in data['items']},{1,3,5,10,15})
        self.assertEqual({r['entry_price'] for r in data['items']},{1,3})
        self.assertEqual(sum(r['orders'] for r in data['items']),5)
    def test_minimum_bid_roundtrip_validation_and_existing_config_default(self):
        body=config(minimum_cents=60,maximum_cents=96)
        response=self.client.post('/demo/bots',json=body)
        self.assertEqual(response.status_code,200,response.text)
        saved=self.client.get('/demo/workspace').json()['bots'][0]['config']
        self.assertEqual(saved['minimum_cents'],60);self.assertEqual(saved['maximum_cents'],96)
        body['minimum_cents']=97
        self.assertEqual(self.client.post('/demo/bots',json=body).status_code,422)
        body.pop('minimum_cents')
        response=self.client.post('/demo/bots',json=body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertIsNone(self.demo.get('bot/'+response.json()['id'])['parameters']['config']['minimum_cents'])
    def test_reset_archives_and_copies_without_funding_or_order_mutation(self):
        from uuid import uuid4
        created=self.client.post('/demo/bots',json=config()).json()['id']
        self.client.post('/demo/bots/'+created+'/control',json=dict(action='resume',revision=1))
        self.demo.event('fill','Existing historical execution')
        history=self.demo.rows('event/',100)
        self.demo.put('account',dict(cash_cents=53627,equity_cents=53627))
        self.demo.put('order/unsettled',dict(status='held',filled=1,remaining=0),parameters=dict(kind='entry',bot=created,ticker='T'))
        prior=self.demo.get('order/unsettled')
        # Old cached clients may still send these fields: neither is a gate.
        body=dict(request_id=str(uuid4()),fresh_bots=False,target_balance_cents=100000,confirmation='RESET BOTS')
        response=self.client.post('/demo/reset',json=body);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['state'],'complete')
        self.assertEqual(self.client.get('/demo/workspace').json()['reset_mode'],'archive_copy')
        self.assertEqual(self.client.post('/demo/reset',json=body).status_code,200)
        bots=self.demo.rows('bot/',100);self.assertEqual(len(bots),2)
        old=self.demo.get('bot/'+created);self.assertTrue(old['progress']['archived']);self.assertEqual(old['progress']['desired'],'paused')
        fresh=next(b for b in bots if b['idempotency_key']!='demo/bot/'+created)
        self.assertEqual(fresh['progress']['desired'],'paused');self.assertEqual(fresh['parameters']['config']['squares'],config()['squares'])
        fresh_id=fresh['idempotency_key'].split('/')[-1]
        self.assertEqual(self.client.post('/demo/bots/'+fresh_id+'/control',json=dict(action='resume',revision=1)).status_code,200)
        self.assertEqual(self.demo.get('account')['progress']['cash_cents'],53627)
        self.assertEqual(self.demo.get('order/unsettled')['progress'],prior['progress'])
        self.assertEqual(self.demo.get('order/unsettled')['parameters'],prior['parameters'])
        for previous in history:self.assertEqual(self.demo.get(previous['idempotency_key'][5:])['progress'],previous['progress'])
        self.client.headers.pop('x-csrf-token');self.assertEqual(self.client.post('/demo/reset',json=body).status_code,403)
    def test_legacy_reset_unblocks_resumes_and_reuses_existing_copies(self):
        from uuid import uuid4
        from services.demo.reset import ResetController
        from unittest.mock import MagicMock
        identifier=self.client.post('/demo/bots',json=config()).json()['id']
        self.client.post('/demo/reset',json=dict(request_id=str(uuid4()),confirmation='RESET BOTS'))
        reset=self.demo.get('reset');params=dict(reset['parameters'],target_balance_cents=100000)
        pending=dict(client_id='legacy-unknown-sale')
        self.demo.put('reset',dict(reset['progress'],state='awaiting_funds',pending=pending,cash_cents=100001),parameters=params)
        fresh=next(b for b in self.demo.rows('bot/',100) if not b['progress'].get('archived'))
        fresh_id=fresh['idempotency_key'].split('/')[-1]
        result=self.client.post('/demo/bulk',json=dict(action='resume',bots=[dict(id=fresh_id,revision=1)]))
        self.assertEqual(result.status_code,200,result.text)
        exchange=MagicMock();ResetController(self.demo,exchange).step(self.demo.get('reset'))
        self.assertEqual(exchange.mock_calls,[])
        self.assertEqual(self.demo.get('reset')['progress']['state'],'complete')
        self.assertEqual(self.demo.get('reset')['progress']['pending'],pending)
        self.assertEqual(len(self.demo.rows('bot/',100)),2)
        self.assertEqual(self.demo.get('bot/'+fresh_id)['progress']['desired'],'running')
        ResetController(self.demo,exchange).step(self.demo.get('reset'))
        self.assertEqual(len(self.demo.rows('bot/',100)),2)
    def test_activity_pagination_and_filter_includes_archive_summaries(self):
        for i in range(55):self.demo.event('fill','Event '+str(i),bot='00000000-0000-0000-0000-000000000001',ticker='T')
        first=self.client.get('/demo/activity?kind=fill').json();self.assertEqual(len(first['items']),50)
        second=self.client.get('/demo/activity?kind=fill&before='+first['next_before']).json();self.assertEqual(len(second['items']),5)
        self.assertFalse(set(r['id'] for r in first['items'])&set(r['id'] for r in second['items']))
    def test_private_controls_require_session_and_csrf(self):
        self.client.headers.pop('x-csrf-token');self.assertEqual(self.client.post('/demo/bots',json=config()).status_code,403)
        self.client.cookies.clear();self.assertEqual(self.client.get('/demo/workspace').status_code,401)
    def test_chart_and_research_empty_is_not_fabricated_data(self):
        self.assertEqual(self.client.get('/demo/chart?period=7D').json()['points'],[])
        r=self.client.get('/demo/research?asset=btc&start=2026-10-01&end=2026-10-30');self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['items'],[])
    def test_durable_order_roundtrip_keeps_open_entries_only(self):
        self.demo.put('order/a',dict(status='held',filled=2,remaining=0),parameters=dict(kind='entry',bot='b'))
        self.demo.put('order/b',dict(status='closed',filled=2,remaining=0),parameters=dict(kind='entry',bot='b'))
        self.assertEqual(len(self.demo.active_orders()),1)
    def test_ask_policy_upgrade_uses_saved_trigger_evidence_and_preserves_completed_sales(self):
        import threading
        from services.demo.runtime import Worker
        order=dict(client_id='entry',kind='entry',bot='bot',revision=1,ticker='T',side='yes',square=0,price=96,quantity=2,sold=1,close=1800000000,exit_triggered=True,exit_ceiling_cents=2)
        self.demo.put('order/entry',dict(status='held',filled=2,remaining=0),parameters=order)
        self.demo.put('order/completed',dict(status='closed',filled=1,remaining=0),parameters=dict(client_id='completed',kind='exit',parent='entry',bot='bot',ticker='T',side='yes',price=2,quantity=1))
        self.demo.event('exit_trigger','Previous bid rule',bot='bot',details=dict(client_id='entry',side='yes',threshold=55,quote=dict(bid=1,ask=99)))
        completed=self.demo.get('order/completed')
        worker=Worker(self.demo,object(),threading.Event(),lambda:None);worker.orders=self.demo.active_orders();worker.recovered=True
        self.assertFalse(worker.upgrade_legacy_exits())
        params=self.demo.get('order/entry')['parameters']
        self.assertFalse(params['exit_triggered']);self.assertEqual(params['exit_reference'],'ask');self.assertNotIn('exit_ceiling_cents',params)
        self.assertEqual(self.demo.get('order/completed')['progress'],completed['progress'])
        self.assertEqual(self.demo.get('order/completed')['parameters'],completed['parameters'])
    def test_workspace_returns_actionable_issue_evidence(self):
        import time
        self.demo.put('health',dict(state='attention',message='Saved order not returned',at=time.time(),issue=dict(summary='Saved order not returned',action='Review Activity',control='retry',phase='reconciliation',market='T',order_id='one',code='not_found')))
        result=self.client.get('/demo/workspace');self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['health']['issue']['order_id'],'one')
        self.assertEqual(result.json()['health']['issue']['action'],'Review Activity')

    def test_per_square_performance_separates_revisions_and_reset_closures(self):
        identifier=self.client.post('/demo/bots',json=config()).json()['id']
        condition=self.demo.get('bot/'+identifier)['parameters']['config']['squares'][0]
        for name,state,params in [
            ('open',dict(status='held',filled=3,remaining=0),dict(sold=1)),
            ('closed',dict(status='closed',filled=2,remaining=0,realized_cents=35),{}),
            ('reset',dict(status='closed',filled=2,remaining=0,reset_closed=True),{}),
            ('rejected',dict(status='rejected',filled=0,remaining=0),{}),
            ('old',dict(status='closed',filled=1,remaining=0,realized_cents=-20),dict(revision=0)),
        ]:
            self.demo.put('order/'+name,state,parameters=dict(dict(bot=identifier,kind='entry',revision=1,square=0,condition=condition),**params))
        self.demo.put('order/exit',dict(status='closed',filled=1,realized_cents=999),parameters=dict(bot=identifier,kind='exit',revision=1,square=0))
        response=self.client.get('/demo/performance?bot='+identifier);self.assertEqual(response.status_code,200,response.text)
        rows=response.json()['items'];self.assertEqual(len(rows),2)
        current=next(r for r in rows if r['revision']==1)
        self.assertEqual(current['orders'],4);self.assertEqual(current['contracts'],7)
        self.assertEqual(current['held_contracts'],2);self.assertEqual(current['scored'],1)
        self.assertEqual(current['unscored_resets'],1);self.assertEqual(current['recorded_pnl_cents'],35)
        self.assertEqual(next(r for r in rows if r['revision']==0)['recorded_pnl_cents'],-20)
        for query in ['','?bot=bad','?bot='+identifier+'&period=bad','?bot='+identifier+'&bot='+identifier]:
            self.assertEqual(self.client.get('/demo/performance'+query).status_code,422)
        self.client.cookies.clear();self.assertEqual(self.client.get('/demo/performance?bot='+identifier).status_code,401)
    def test_time_statistics_use_market_clock_legacy_evidence_and_local_dst_hours(self):
        from datetime import datetime,timezone
        self.demo.put('health',dict(state='ready',features=['buy_low_sell_high_v1']))
        identifier=self.client.post('/demo/bots',json=config(strategy='buy_low_sell_high',cycle_cutoff_minutes=5)).json()['id']
        start=datetime(2026,11,1,8,30,tzinfo=timezone.utc).timestamp()
        from types import SimpleNamespace
        clock=patch('services.api.demo_performance.time',SimpleNamespace(time=lambda:start+8*3600));clock.start();self.addCleanup(clock.stop)
        cases=[('a',start,1,15,20),('b',start+3600,1,None,-5),('c',start+7200,0,None,9),('d',start+7800,0,None,None),('old',start-10*86400,1,15,100)]
        for key,at,revision,minutes,pnl in cases:
            data=dict(bot=identifier,kind='entry',entry_strategy='buy_low_sell_high',client_id=key,revision=revision,square=0,created_at=at,close=at+300,price=10)
            if minutes is not None:data['market_close_at']=at+minutes*60
            state=dict(status='closed' if pnl is not None else 'rejected',filled=1 if pnl is not None else 0,remaining=0)
            if pnl is not None:state['realized_cents']=pnl
            self.demo.put('order/'+key,state,parameters=data)
        self.demo.event('order_intent','Saved legacy market clock',bot=identifier,details=dict(client_id='c',quote=dict(entry_close=start+7200+180)))
        path='/demo/performance?bot='+identifier
        times=self.client.get(path+'&group=time&period=24H');self.assertEqual(times.status_code,200,times.text)
        rows=times.json()['items'];self.assertEqual({r['bucket'] for r in rows},{3,10,15,None})
        self.assertEqual(sum(r['orders'] for r in rows),4)
        self.assertEqual(sum(r['recorded_pnl_cents'] or 0 for r in rows),24)
        self.assertIn('Time unavailable',[r['label'] for r in rows])
        self.assertEqual(next(r for r in rows if r['bucket']==15)['recorded_pnl_cents'],20)
        hours=self.client.get(path+'&group=hour&period=24H&timezone=America/Los_Angeles').json()['items']
        first=next(r for r in hours if r['bucket']==1)
        self.assertEqual((first['orders'],first['recorded_pnl_cents']),(2,15))
        self.assertEqual(first['label'],'01:00–02:00')
        self.assertEqual(sum(r['orders'] for r in self.client.get(path+'&group=time').json()['items']),5)
        for suffix in ['&group=bad','&timezone=invalid','&group=time&group=hour']:
            self.assertEqual(self.client.get(path+suffix).status_code,422)

    def test_time_performance_uses_entry_cohorts_local_dates_and_original_market_clock(self):
        from datetime import datetime,timezone
        identifier=self.client.post('/demo/bots',json=config()).json()['id']
        # Two occurrences of 01:30 on the Pacific fall-back day, plus the next day.
        instants=['2026-11-01T08:30:00+00:00','2026-11-01T09:30:00+00:00','2026-11-02T08:00:00+00:00']
        for i,instant in enumerate(instants):
            at=datetime.fromisoformat(instant).timestamp()
            self.demo.put('order/time-'+str(i),dict(status='closed',filled=2,remaining=0,realized_cents=10),
                parameters=dict(bot=identifier,kind='entry',revision=1,square=0,created_at=at,market_close_at=at+300,close=at+240,entry_strategy='buy_low_sell_high'))
        at=datetime.fromisoformat(instants[0]).timestamp()
        self.demo.put('order/legacy-cycle',dict(status='rejected',filled=0,remaining=0),parameters=dict(bot=identifier,kind='entry',revision=0,square=0,created_at=at,close=at+60,entry_strategy='buy_low_sell_high'))
        query='?bot='+identifier+'&start=2026-11-01&end=2026-11-01&timezone=America/Los_Angeles'
        response=self.client.get('/demo/performance'+query+'&group=hour')
        self.assertEqual(response.status_code,200,response.text)
        rows=response.json()['items'];self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['bucket'],rows[0]['orders'],rows[0]['scored'],rows[-1]['recorded_pnl_cents']),(1,3,2,20))
        rows=self.client.get('/demo/performance'+query+'&group=time').json()['items']
        self.assertEqual([(r['bucket'],r['orders']) for r in rows],[(5,2),(None,1)])
        self.assertIsNone(rows[-1]['recorded_pnl_cents'])
        # Closing today does not move an entry from its original date cohort.
        self.assertEqual(sum(r['orders'] for r in self.client.get('/demo/performance'+query+'&group=square').json()['items']),3)
        for suffix in ['&group=bad','&timezone=bad','&start=2026-11-03&end=2026-11-01','&start=bad']:
            self.assertEqual(self.client.get('/demo/performance?bot='+identifier+suffix).status_code,422)

    def test_latest_transactions_filter_is_bot_scoped_and_ignores_control_events(self):
        from uuid import uuid4
        identifier=self.client.post('/demo/bots',json=config()).json()['id']
        self.demo.event('order','Accepted',bot=identifier,details=dict(order_kind='entry',price=3,quantity=10))
        self.demo.event('fill','Filled',bot=identifier,details=dict(filled=2))
        self.demo.event('bot_configured','Changed',bot=identifier)
        self.demo.event('order','Other bot order',bot=str(uuid4()))
        response=self.client.get('/demo/activity?bot='+identifier+'&kind=transactions')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([r['kind'] for r in response.json()['items']],['fill','order'])
        self.assertEqual(len(self.client.get('/demo/activity?bot='+identifier+'&kind=order').json()['items']),1)

    def test_retired_column_values_are_ignored_and_removed_from_new_configs(self):
        body=config(column_maximum_cents={'60-70':65,'90-100':94})
        response=self.client.post('/demo/bots',json=body);self.assertEqual(response.status_code,200,response.text)
        page=self.client.get('/demo/workspace').json();self.assertNotIn('column_bid_caps',page)
        self.assertEqual(page['bots'][0]['config']['column_maximum_cents'],{})

    def test_running_allocation_edit_preserves_strategy_orders_triggers_and_checks_stale_settings(self):
        body=config();identifier=self.client.post('/demo/bots',json=body).json()['id']
        self.client.post('/demo/bots/'+identifier+'/control',json=dict(action='resume',revision=1))
        self.demo.put('order/existing',dict(status='held',filled=2,remaining=0),parameters=dict(kind='entry',bot=identifier,ticker='T',revision=1,price=60))
        self.demo.put('trigger/'+identifier,{'T/0/yes':dict(submitted=True)},parameters=dict(revision=1))
        order=self.demo.get('order/existing');trigger=self.demo.get('trigger/'+identifier)
        edited=dict(body,bot_percent=25,expected_settings_revision=1)
        response=self.client.post('/demo/bots/'+identifier+'/configure',json=edited)
        self.assertEqual(response.status_code,200,response.text)
        bot=self.client.get('/demo/workspace').json()['bots'][0]
        self.assertEqual((bot['revision'],bot['settings_revision'],bot['desired'],bot['config']['bot_percent']),(1,2,'running',25))
        self.assertEqual(self.demo.get('order/existing'),order);self.assertEqual(self.demo.get('trigger/'+identifier),trigger)
        response=self.client.post('/demo/bots/'+identifier+'/configure',json=dict(edited,bot_percent=30))
        self.assertEqual(response.status_code,409)
        response=self.client.post('/demo/bots/'+identifier+'/configure',json=dict(edited,expected_settings_revision=2,adjustment_cents=-2))
        self.assertEqual(response.status_code,409)
        self.client.post('/demo/bots/'+identifier+'/control',json=dict(action='pause',revision=1))
        response=self.client.post('/demo/bots/'+identifier+'/configure',json=dict(edited,expected_settings_revision=2,bot_percent=5))
        self.assertEqual(response.status_code,200,response.text)
        bot=self.client.get('/demo/workspace').json()['bots'][0]
        self.assertEqual((bot['revision'],bot['settings_revision'],bot['config']['bot_percent']),(1,3,5))

    def test_individual_square_limits_gate_old_worker_and_can_change_live_without_revising_strategy(self):
        import time
        body=config();body['squares'][0]['maximum_cents']=62
        response=self.client.post('/demo/bots',json=body);self.assertEqual(response.status_code,409)
        self.demo.put('health',dict(state='ready',at=time.time(),features=['square_bid_caps_v1']))
        identifier=self.client.post('/demo/bots',json=body).json()['id']
        self.client.post('/demo/bots/'+identifier+'/control',json=dict(action='resume',revision=1))
        self.demo.put('order/held',dict(status='held',filled=2,remaining=0),parameters=dict(kind='entry',bot=identifier,ticker='T',revision=1,price=60))
        prior=self.demo.get('order/held');body['squares'][0]['maximum_cents']=58
        response=self.client.post('/demo/bots/'+identifier+'/configure',json=dict(body,expected_settings_revision=1));self.assertEqual(response.status_code,200,response.text)
        bot=self.client.get('/demo/workspace').json()['bots'][0]
        self.assertEqual((bot['revision'],bot['settings_revision'],bot['desired']),(1,2,'running'))
        self.assertEqual(bot['config']['squares'][0]['maximum_cents'],58);self.assertEqual(self.demo.get('order/held'),prior)

    def test_square_loss_override_can_change_live_and_blank_restores_bot_setting(self):
        import time
        body=config(loss_mode='manual',loss_cents=55);body['squares'][0]['loss_prevention_cents']=60
        self.assertEqual(self.client.post('/demo/bots',json=body).status_code,409)
        self.demo.put('health',dict(state='ready',at=time.time(),features=['square_loss_prevention_v1']))
        response=self.client.post('/demo/bots',json=body);self.assertEqual(response.status_code,200,response.text);identifier=response.json()['id']
        self.client.post('/demo/bots/'+identifier+'/control',json=dict(action='resume',revision=1))
        body['squares'][0].pop('loss_prevention_cents')
        response=self.client.post('/demo/bots/'+identifier+'/configure',json=dict(body,expected_settings_revision=1));self.assertEqual(response.status_code,200,response.text)
        bot=self.client.get('/demo/workspace').json()['bots'][0]
        self.assertEqual((bot['revision'],bot['desired'],bot['config']['loss_cents']),(1,'running',55))
        self.assertIsNone(bot['config']['squares'][0]['loss_prevention_cents'])
        body=config(loss_mode='research');body['squares'][0]['loss_prevention_cents']=58
        response=self.client.post('/demo/bots',json=body);self.assertEqual(response.status_code,200,response.text)

    def test_any_rule_edit_with_positions_preserves_prior_protection_for_active_and_paused_bots(self):
        for desired in ['running','paused']:
            with self.subTest(desired=desired):
                body=config(loss_mode='manual',loss_cents=55)
                body['squares'].append(dict(body['squares'][0],min_price=80,max_price=89,loss_prevention_cents=60))
                self.demo.put('health',dict(state='ready',features=['editable_rules_v1','square_loss_prevention_v1']))
                identifier=self.client.post('/demo/bots',json=body).json()['id']
                if desired=='running':self.client.post('/demo/bots/'+identifier+'/control',json=dict(action='resume',revision=1))
                self.demo.put('order/held-'+identifier,dict(status='held',filled=2,remaining=0),parameters=dict(kind='entry',bot=identifier,ticker='T',revision=1,square=1,price=82))
                prior=self.demo.get('order/held-'+identifier)
                edited=config(loss_mode='manual',loss_cents=70,adjustment_cents=-3)
                edited['squares'][0]['asset']='sports'
                response=self.client.post('/demo/bots/'+identifier+'/configure',json=dict(edited,expected_settings_revision=1))
                self.assertEqual(response.status_code,200,response.text)
                saved=self.demo.get('bot/'+identifier)
                self.assertEqual(saved['progress']['desired'],desired)
                self.assertEqual(saved['parameters']['revision'],2)
                self.assertEqual(saved['parameters']['prior_protection']['1'],[55,60])
                self.assertEqual(self.demo.get('order/held-'+identifier),prior)
                edited['loss_cents']=75
                response=self.client.post('/demo/bots/'+identifier+'/configure',json=dict(edited,expected_settings_revision=2))
                self.assertEqual(response.status_code,200,response.text)
                snapshots=self.demo.get('bot/'+identifier)['parameters']['prior_protection']
                self.assertEqual(snapshots,{'1':[55,60],'2':[70]})

    def test_cycle_roundtrip_capability_and_atomic_offset_recovery(self):
        import threading
        from services.demo.runtime import Worker
        from services.api.tests.test_demo_cycles import entry,book,NOW
        body=config(strategy='buy_low_sell_high',cycle_buy_cents=10,cycle_sell_cents=20,cycle_cutoff_minutes=1)
        self.assertEqual(self.client.post('/demo/bots',json=body).status_code,409)
        self.demo.put('health',dict(state='ready',features=['buy_low_sell_high_v1']))
        response=self.client.post('/demo/bots',json=body);self.assertEqual(response.status_code,200,response.text);identifier=response.json()['id']
        saved=self.client.get('/demo/workspace').json()['bots'][0]
        self.assertEqual((saved['config']['strategy'],saved['config']['cycle_buy_cents'],saved['config']['cycle_sell_cents']),('buy_low_sell_high',10,20))
        self.client.post('/demo/bots/'+identifier+'/control',json=dict(action='resume',revision=1))
        records=[entry(bot=identifier,client_id='yes',side='yes',filled=2,remaining=0),entry(bot=identifier,client_id='no',side='no',filled=2,remaining=0)]
        for order in records:
            data={k:v for k,v in order.items() if k not in ('status','filled','remaining')}
            self.demo.put('order/'+order['client_id'],dict(status='held',filled=2,remaining=0),parameters=data)
        self.demo.put('trigger/'+identifier,{'t/0/'+side:dict(cycle=1,submitted=True,first_at=NOW) for side in ['yes','no']},parameters=dict(revision=1))
        class Ex:
            def call(self,*args,**kwargs):return dict(balance=10160,portfolio_value=0)
            def pages(self,path,key,**params):
                if key=='market_positions' or params.get('status')=='resting':return []
                return [dict(order_id='ex-'+o['client_id'],client_order_id=o['client_id'],status='executed',fill_count_fp='2.00',remaining_count_fp='0.00') for o in records]
        worker=Worker(self.demo,Ex(),threading.Event(),lambda:None);worker.quotes={'t':book()}
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.reconcile()
        self.assertTrue(worker.recovered);self.assertFalse(worker.blocked)
        for side in ['yes','no']:
            row=self.demo.get('order/'+side);self.assertEqual(row['parameters']['offset_quantity'],2)
            self.assertEqual((row['progress']['status'],row['progress']['realized_cents']),('closed',80))
            self.assertEqual(self.demo.get('trigger/'+identifier)['progress']['t/0/'+side]['cycle'],2)
        self.assertEqual(self.demo.active_orders(),[])
        restarted=Worker(self.demo,Ex(),threading.Event(),lambda:None)
        with patch('services.demo.runtime.time.time',return_value=NOW+1):restarted.reconcile()
        self.assertEqual(self.demo.get('trigger/'+identifier)['progress']['t/0/yes']['cycle'],2)
        # Compare-and-update fences both offset legs in one transaction.
        fresh=[entry(client_id='fresh-a',filled=2,remaining=0),entry(client_id='fresh-b',side='no',filled=2,remaining=0)]
        for o in fresh:self.demo.put('order/'+o['client_id'],dict(status='held',filled=2,remaining=0),parameters=o)
        worker.orders=fresh
        with self.store.pool.connection() as c:c.execute("UPDATE research_job SET parameters=parameters||'{\"offset_quantity\":1}'::jsonb WHERE idempotency_key='demo/order/fresh-b'")
        from services.demo.exchange import ExchangeFailure
        with self.assertRaises(ExchangeFailure):worker.apply_cycle_offsets({'fresh-a':2,'fresh-b':2})
        self.assertNotIn('offset_quantity',self.demo.get('order/fresh-a')['parameters'])

    def test_cancel_remains_tracked_until_final_fill_counts_are_reconciled(self):
        import threading
        from services.demo.runtime import Worker
        from services.api.tests.test_demo_cycles import entry,book,NOW
        body=config(strategy='buy_low_sell_high',cycle_cutoff_minutes=1)
        self.demo.put('health',dict(state='ready',features=['buy_low_sell_high_v1']))
        identifier=self.client.post('/demo/bots',json=body).json()['id']
        order=entry(bot=identifier)
        class Ex:
            def cancel(self,*args):return {}
            def call(self,*args,**kwargs):return dict(balance=9980,portfolio_value=20)
            def pages(self,path,key,**params):
                if key=='market_positions':return [dict(ticker='t',position_fp='2.00')]
                if params.get('status')=='resting':return []
                return [dict(order_id='ex-low',client_order_id='low',status='canceled',fill_count_fp='2.00',remaining_count_fp='0.00')]
        worker=Worker(self.demo,Ex(),threading.Event(),lambda:None);worker.orders=[order];worker.quotes={'t':book()}
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.cancel(order,'Cutoff')
        self.assertEqual(self.demo.active_orders()[0]['status'],'cancel_pending')
        with patch('services.demo.runtime.time.time',return_value=NOW+1):worker.reconcile()
        saved=self.demo.get('order/low');self.assertEqual((saved['progress']['status'],saved['progress']['filled']),('held',2))
        self.assertFalse(worker.blocked)

    def test_closed_order_recovery_uses_exchange_evidence_and_preserves_unrelated_history(self):
        import threading
        from services.demo.runtime import Worker
        from services.api.tests.test_demo_cycles import NOW
        from services.demo.exchange import ExchangeFailure
        parameters=dict(client_id='late',kind='entry',ticker='t',quantity=10,bot='saved-bot',revision=1,square=0,price=10,created_at=NOW-900)
        self.demo.put('order/late',dict(status='closed',filled=0,remaining=0,exchange_id='ex-late'),parameters=parameters)
        worker=Worker(self.demo,object(),threading.Event(),lambda:None)
        remote=dict(ticker='t',order_id='ex-late',status='canceled',fill_count_fp='2.00',remaining_count_fp='0.00')
        self.assertTrue(worker.recover_closed_orders({'late':remote},set(),{'t'},NOW))
        saved=self.demo.get('order/late');self.assertEqual(saved['parameters'],parameters)
        self.assertEqual((saved['progress']['status'],saved['progress']['filled']),('held',2))
        self.assertNotIn('realized_cents',saved['progress'])
        self.assertFalse(worker.recover_closed_orders({'late':remote},set(),{'t'},NOW+1))
    def test_research_stop_projects_current_time_cells_and_reuses_immutable_cache(self):
        import threading
        from uuid import uuid4
        from psycopg.types.json import Jsonb
        from services.demo.runtime import Worker
        cells=[dict(hold=dict(price_band_cents='60-70',minutes_before_close=m),loss_prevention=dict(sell_threshold_cents=v)) for m,v in [(15,50),(10,60),(5,70)]]
        with self.store.pool.connection() as c:
            identifier=c.execute("INSERT INTO research_result(stream_key,model_version,fingerprint,asset,report) VALUES(%s,'research-return-window-v2',%s,'btc',%s) RETURNING id",('risk-test-'+uuid4().hex,'d'*64,Jsonb(dict(historical=dict(cells=cells))))).fetchone()['id']
        worker=Worker(self.demo,object(),threading.Event(),lambda:None)
        self.assertEqual(worker.research_stop(identifier,'60-70',12),50)
        from types import SimpleNamespace
        worker.store=SimpleNamespace() # Any subsequent database read would fail.
        self.assertEqual(worker.research_stop(identifier,'60-70',8),60)
        self.assertEqual(worker.research_stop(identifier,'60-70',4),70)
        self.assertEqual(worker.research_stop(identifier,'60-70',5),70)

    def test_shared_cycle_partial_and_complete_exits_keep_each_bots_profit_and_repeat(self):
        import threading
        from services.demo.runtime import Worker
        from services.api.tests.test_demo_cycles import entry,book,NOW
        self.demo.put('health',dict(state='ready',features=['buy_low_sell_high_v1']))
        ids=[self.client.post('/demo/bots',json=config(strategy='buy_low_sell_high',cycle_buy_cents=buy,cycle_sell_cents=sell)).json()['id'] for buy,sell in [(10,20),(6,9)]]
        entries=[entry(bot=ids[0],client_id='a',quantity=3,filled=3,remaining=0),
                 entry(bot=ids[1],client_id='b',price=6,profit_target_cents=9,quantity=5,filled=5,remaining=0)]
        sells=[dict(client_id='sell-'+o['client_id'],kind='exit',exit_role='profit',parent=o['client_id'],bot=o['bot'],revision=1,
            ticker='t',side='yes',price=o['profit_target_cents'],quantity=o['filled'],created_at=NOW,close=NOW+900,status='resting',filled=0,remaining=o['filled']) for o in entries]
        class Ex:
            complete=False
            def call(self,*args,**kwargs):return dict(balance=10000,portfolio_value=0 if self.complete else 500)
            def pages(self,path,key,**params):
                if key=='market_positions':return [] if self.complete else [dict(ticker='t',position_fp='5.00')]
                rows=[]
                for i,o in enumerate(entries+sells):
                    filled=o['quantity'] if i<2 or self.complete else i-1
                    rows.append(dict(ticker='t',order_id='ex-'+o['client_id'],client_order_id=o['client_id'],
                        status='executed' if filled==o['quantity'] else 'resting',fill_count_fp=str(filled),remaining_count_fp=str(o['quantity']-filled)))
                return [r for r in rows if r['status']=='resting'] if params.get('status')=='resting' else rows
        ex=Ex();w=Worker(self.demo,ex,threading.Event(),lambda:None);w.quotes={'t':book()}
        for o in entries+sells:w.save_order(dict(o,filled=0,status='cancel_pending',remaining=0) if o['client_id']=='a' else o)
        for i,identifier in enumerate(ids):self.demo.put('trigger/'+identifier,{'t/0/yes':dict(cycle=1,submitted=i!=0,first_at=NOW)},parameters=dict(revision=1))
        with patch('services.demo.runtime.time.time',return_value=NOW):w.reconcile()
        self.assertFalse(w.blocked);self.assertTrue(w.recovered)
        self.assertTrue(self.demo.get('trigger/'+ids[0])['progress']['t/0/yes']['submitted'])
        self.assertEqual([self.demo.get('order/'+o['client_id'])['parameters']['sold'] for o in entries],[1,2])
        self.assertFalse(w.profit_sell(next(o for o in w.orders if o['client_id']=='a'),book(),NOW))
        ex.complete=True
        with patch('services.demo.runtime.time.time',return_value=NOW+1):w.reconcile()
        self.assertEqual([self.demo.get('order/'+o['client_id'])['progress']['realized_cents'] for o in entries],[30,15])
        self.assertEqual([self.demo.get('trigger/'+i)['progress']['t/0/yes']['cycle'] for i in ids],[2,2])
        metrics=self.client.get('/demo/workspace').json()['metrics']
        self.assertEqual([metrics[i]['realized_cents'] for i in ids],[30,15])
        restarted=Worker(self.demo,ex,threading.Event(),lambda:None)
        with patch('services.demo.runtime.time.time',return_value=NOW+2):restarted.reconcile()
        self.assertEqual([self.demo.get('trigger/'+i)['progress']['t/0/yes']['cycle'] for i in ids],[2,2])

    def test_cross_bot_opposite_fills_offset_atomically_and_remaining_sell_keeps_parent(self):
        import threading
        from services.demo.runtime import Worker
        from services.api.tests.test_demo_cycles import entry,book,NOW
        self.demo.put('health',dict(state='ready',features=['buy_low_sell_high_v1']))
        ids=[self.client.post('/demo/bots',json=config(strategy='buy_low_sell_high',cycle_buy_cents=buy,cycle_sell_cents=sell)).json()['id'] for buy,sell in [(10,20),(6,9)]]
        entries=[entry(bot=ids[0],client_id='yes-a',quantity=3,filled=3,remaining=0),
                 entry(bot=ids[1],client_id='no-b',side='no',price=6,profit_target_cents=9,quantity=2,filled=2,remaining=0)]
        sell=dict(client_id='last-sell',kind='exit',exit_role='profit',parent='yes-a',bot=ids[0],revision=1,ticker='t',side='yes',
            price=20,quantity=1,created_at=NOW,close=NOW+900,status='resting',filled=0,remaining=1)
        class Ex:
            complete=False
            def call(self,*args,**kwargs):return dict(balance=10000,portfolio_value=0 if self.complete else 100)
            def pages(self,path,key,**params):
                if key=='market_positions':return [] if self.complete else [dict(ticker='t',position_fp='1.00')]
                if params.get('status')=='resting':return []
                return [dict(ticker='t',order_id='ex-'+o['client_id'],client_order_id=o['client_id'],status='executed',fill_count_fp=str(o['quantity']),remaining_count_fp='0.00') for o in entries+([sell] if self.complete else [])]
        ex=Ex();w=Worker(self.demo,ex,threading.Event(),lambda:None);w.quotes={'t':book()}
        for o in entries:w.save_order(o)
        for identifier,side in zip(ids,['yes','no']):self.demo.put('trigger/'+identifier,{'t/0/'+side:dict(cycle=1,submitted=True,first_at=NOW)},parameters=dict(revision=1))
        with patch('services.demo.runtime.time.time',return_value=NOW):w.reconcile()
        self.assertTrue(w.recovered);self.assertFalse(w.blocked)
        self.assertEqual([self.demo.get('order/'+o['client_id'])['parameters']['offset_quantity'] for o in entries],[2,2])
        self.assertEqual(self.demo.get('order/no-b')['progress']['realized_cents'],88)
        self.assertEqual(self.demo.get('order/yes-a')['parameters']['sold'],2)
        w.save_order(sell);ex.complete=True
        with patch('services.demo.runtime.time.time',return_value=NOW+1):w.reconcile()
        self.assertEqual(self.demo.get('order/yes-a')['progress']['realized_cents'],90)
        self.assertEqual(self.demo.get('order/last-sell')['parameters']['bot'],ids[0])
        self.assertEqual(self.demo.get('trigger/'+ids[0])['progress']['t/0/yes']['cycle'],2)
        self.assertEqual(self.demo.get('trigger/'+ids[1])['progress']['t/0/no']['cycle'],2)

    def test_cycle_price_rejection_recovers_after_restart_without_shifting_twice(self):
        import threading
        from unittest.mock import Mock
        from services.demo.runtime import Worker
        from services.api.tests.test_demo_cycles import entry,book,NOW
        self.demo.put('health',dict(state='ready',features=['buy_low_sell_high_v1']))
        identifier=self.client.post('/demo/bots',json=config(strategy='buy_low_sell_high',cycle_cutoff_minutes=1)).json()['id']
        key='t/0/yes'
        self.demo.put('trigger/'+identifier,{key:dict(cycle=1,submitted=True,first_at=NOW)},parameters=dict(revision=1))
        first=Worker(self.demo,object(),threading.Event(),lambda:None)
        # Simulate a crash after saving a definitive rejection, before its retry state.
        first.save_order(entry(bot=identifier,status='rejected',remaining=0,rejection_reason='post_only',entry_attempt=0))
        recovered=Worker(self.demo,object(),threading.Event(),lambda:None);recovered.load_bots()
        with patch('services.demo.runtime.time.time',return_value=NOW):recovered.repair_rejected_entries()
        state=self.demo.get('trigger/'+identifier)['progress'][key]
        self.assertEqual((state['retry_buy_cents'],state['retry_sell_cents'],state['attempt']),(8,18,1))
        again=Worker(self.demo,object(),threading.Event(),lambda:None);again.load_bots();again.repair_rejected_entries()
        self.assertEqual(self.demo.get('trigger/'+identifier)['progress'][key],state)
        parent=entry(bot=identifier,client_id='parent',price=8,profit_target_cents=18,filled=3,remaining=0,profit_attempt=1)
        again.save_order(parent)
        rejected=dict(client_id='profit-rejected',kind='exit',exit_role='profit',parent='parent',bot=identifier,revision=1,
            ticker='t',side='yes',price=18,quantity=3,close=NOW+900,created_at=NOW,status='rejected',remaining=0,filled=0,rejection_reason='price_tick')
        again.save_order(rejected)
        final=Worker(self.demo,object(),threading.Event(),lambda:None);final.load_bots()
        with patch('services.demo.runtime.time.time',return_value=NOW):final.repair_rejected_entries()
        self.assertEqual(self.demo.get('order/parent')['parameters']['profit_target_cents'],20)
        final.recovered=True;final.submit=Mock()
        holding=next(o for o in final.orders if o['client_id']=='parent')
        self.assertTrue(final.profit_sell(holding,dict(book(),clock=2),NOW+1))
        retry=final.submit.call_args.args[0];self.assertEqual((retry['price'],retry['quantity']),(20,3))
        self.assertEqual(self.demo.get('order/profit-rejected')['progress']['status'],'rejected')

    def test_fractional_profit_fills_complete_cycle_without_float_dust(self):
        import threading
        from services.demo.runtime import Worker
        from services.api.tests.test_demo_cycles import entry,book,NOW
        body=config(strategy='buy_low_sell_high',cycle_cutoff_minutes=1)
        self.demo.put('health',dict(state='ready',features=['buy_low_sell_high_v1']))
        identifier=self.client.post('/demo/bots',json=body).json()['id']
        parent=entry(bot=identifier,quantity=.8,filled=.8,remaining=0)
        data={k:v for k,v in parent.items() if k not in ('status','filled','remaining')}
        self.demo.put('order/low',dict(status='held',filled=.8,remaining=0),parameters=data)
        for i,filled in enumerate([.1,.7]):self.demo.put('order/high-'+str(i),dict(status='closed',filled=filled,remaining=0),parameters=dict(kind='exit',parent='low',exit_role='profit',price=20))
        self.demo.put('trigger/'+identifier,{'t/0/yes':dict(cycle=1,submitted=True,first_at=NOW)},parameters=dict(revision=1))
        class Ex:
            def call(self,*args,**kwargs):return dict(balance=10008,portfolio_value=0)
            def pages(self,path,key,**params):
                if key=='market_positions' or params.get('status')=='resting':return []
                return [dict(ticker='t',order_id='ex-low',client_order_id='low',status='executed',fill_count_fp='0.80',remaining_count_fp='0.00')]
        worker=Worker(self.demo,Ex(),threading.Event(),lambda:None);worker.quotes={'t':book()}
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.reconcile()
        self.assertEqual(self.demo.get('order/low')['progress']['status'],'closed')
        self.assertEqual(self.demo.get('trigger/'+identifier)['progress']['t/0/yes']['cycle'],2)
