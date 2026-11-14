"""Live transport, loss accounting and failed-write guards, without real orders."""
import unittest,json,threading
from unittest.mock import Mock,MagicMock,patch
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding,PrivateFormat,NoEncryption
import httpx
from services.live.exchange import LiveExchange,LiveConnectionError
from services.demo.exchange import DemoSigner,PATH,PUBLIC_ACTIVITY_ROOT
from services.live.risk import loss_state,RiskBlocked,initialize_trial
from services.live.fees import zero_maker_fees
from services.api.tests.test_demo_cycles import entry

def signer():
    pem=ed25519.Ed25519PrivateKey.generate().private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption()).decode()
    return DemoSigner('11111111-1111-1111-1111-111111111111',pem)
class LiveTransport(unittest.TestCase):
    def exchange(self,handler,**kwargs):return LiveExchange(signer(),2,client=httpx.Client(transport=httpx.MockTransport(handler)),**kwargs)
    def test_portfolio_reads_force_isolated_subaccount(self):
        seen=[]
        ex=self.exchange(lambda r:(seen.append(r),httpx.Response(200,json=dict(balance=5000)))[1])
        try:ex.call('GET','/portfolio/balance',params=dict(subaccount=0))
        finally:ex.close()
        self.assertEqual(seen[0].url.params['subaccount'],'2');self.assertTrue(str(seen[0].url).startswith(PUBLIC_ACTIVITY_ROOT));self.assertIn('kalshi-access-key',seen[0].headers)
    def test_transfers_primary_access_and_unguarded_posts_are_blocked(self):
        ex=self.exchange(lambda r:self.fail('No network write expected'))
        ex.scope_verified=True
        for method,path,body in [('POST','/portfolio/subaccounts/transfer',{}),('POST','/portfolio/intra_exchange_instance_transfer',{}),('POST','/portfolio/events/orders',{})]:
            with self.subTest(path=path),self.assertRaises(LiveConnectionError):ex.call(method,path,body=body)
        ex.close()
    def test_unrestricted_or_unknown_key_restriction_is_rejected(self):
        for status,text in [(200,'{}'),(403,'permission denied'),(401,'restricted subaccount')]:
            calls=[]
            def respond(r):
                calls.append(r)
                return httpx.Response(200,json=dict(balance=5000)) if len(calls)==1 else httpx.Response(status,text=text)
            ex=self.exchange(respond)
            try:
                with self.subTest(status=status),self.assertRaises(LiveConnectionError):ex.verify_scope()
                self.assertFalse(ex.scope_verified)
            finally:ex.close()
    def test_positive_restriction_proof_and_submit_run_guard_before_wire(self):
        seen=[];guard=Mock()
        def respond(r):
            seen.append(r)
            if r.method=='POST':return httpx.Response(201,json=dict(order_id='accepted',remaining_count=1,fill_count=0))
            if r.url.params.get('subaccount')=='0':return httpx.Response(403,text='this API key is restricted to a single sub-account')
            return httpx.Response(200,json=dict(balance=5000))
        ex=self.exchange(respond,order_guard=guard)
        try:
            self.assertTrue(ex.verify_scope());result=ex.submit(entry(quantity=1,price=3))
            guard.assert_called_once();body=json.loads(seen[-1].content)
            self.assertEqual(body['subaccount'],2);self.assertTrue(body['post_only']);self.assertEqual(body['count'],'1.00')
            self.assertEqual(result['fill_count'],0);self.assertNotIn('reduce_only',body)
        finally:ex.close()
    def test_rejected_order_guard_sends_no_post(self):
        seen=[];guard=Mock(side_effect=RiskBlocked('blocked'))
        ex=self.exchange(lambda r:(seen.append(r),httpx.Response(200,json={}))[1],order_guard=guard);ex.scope_verified=True
        try:
            with self.assertRaises(RiskBlocked):ex.submit(entry(quantity=1,price=3))
            self.assertEqual(seen,[]);self.assertIsNone(ex.guarded_body)
        finally:ex.close()
    def test_market_data_is_unsigned(self):
        seen=[];ex=self.exchange(lambda r:(seen.append(r),httpx.Response(200,json=dict(markets=[])))[1])
        try:ex.call('GET','/markets')
        finally:ex.close()
        self.assertNotIn('kalshi-access-key',seen[0].headers)
class LossBudget(unittest.TestCase):
    def test_active_and_held_cost_reserved_and_realized_credits_not_double_counted(self):
        orders=[dict(kind='entry',price=3,remaining=1,filled=0,status='resting'),dict(kind='entry',price=3,remaining=0,filled=1,sold=0,status='held'),dict(kind='entry',price=3,remaining=0,filled=1,sold=1,status='closed',realized_cents=97)]
        state=loss_state(5000,2500,orders)
        self.assertEqual(state['available_cents'],5091);self.assertEqual(state['reserved_cents'],6);self.assertFalse(state['stopped'])
    def test_fifty_percent_cutoff_includes_worst_case_open_risk(self):
        self.assertTrue(loss_state(5000,2500,[dict(kind='entry',realized_cents=-2497),dict(kind='entry',price=3,remaining=1,status='resting')])['stopped'])
    def test_restart_cannot_replace_account_binding(self):
        store=Mock();store.get.side_effect=[dict(progress=dict(trial_cap_cents=5000,loss_limit_cents=2500)),dict(progress=dict(binding='old'))]
        with self.assertRaises(RiskBlocked):initialize_trial(store,Mock(),'new')
    def test_more_than_fifty_dollars_never_initializes_trial(self):
        store=Mock();store.get.side_effect=[dict(progress=dict(trial_cap_cents=5000,loss_limit_cents=2500)),None]
        ex=Mock();ex.pages.return_value=[];ex.call.return_value=dict(balance=5001,portfolio_value=0)
        with self.assertRaises(RiskBlocked):initialize_trial(store,ex,'binding')
        store.put.assert_not_called()
class Fees(unittest.TestCase):
    def exchange(self,event_rows=(),series_rows=(),fee='quadratic'):
        ex=Mock();ex.public_get.side_effect=[dict(series=dict(fee_type=fee)),dict(series_fee_change_arr=list(series_rows)),dict(event_fee_changes=list(event_rows),cursor='')];return ex
    def test_zero_fee_series_with_no_overrides_passes(self):self.assertTrue(zero_maker_fees(self.exchange(),'S','E',1800000000))
    def test_event_and_scheduled_series_maker_fees_block_entries(self):
        for ex in [self.exchange(event_rows=[dict(scheduled_ts='2026-01-01T00:00:00Z',fee_type_override='quadratic_with_maker_fees')]),self.exchange(series_rows=[dict(scheduled_ts='2026-01-01T00:00:00Z',fee_type='quadratic_with_maker_fees')]),self.exchange(fee='unknown')]:
            with self.assertRaises(RiskBlocked):zero_maker_fees(ex,'S','E',1800000000)

class SharedQuantity(unittest.TestCase):
    def test_fifty_dollar_plan_matches_executor_for_both_sides(self):
        from services.trading.allocation import contracts
        from services.api.live_bots import sizing
        config=dict(bid_percent=1,market_percent=2,bot_percent=3,cycle_buy_cents=3)
        self.assertEqual(sizing(config,dict(trial_cap_cents=5000))['contracts_per_bid'],16)
        first=contracts(config,3,5000,cash=4200,market=0,bot=0,peers=2)
        second=contracts(config,3,5000,cash=4200-first*3,market=first*3,bot=first*3,peers=1)
        self.assertEqual((first,second),(16,16))

class LiveWorkerWiring(unittest.TestCase):
    def test_worker_checks_public_activity_and_backup_before_enabling_entry(self):
        from services.live.runtime import LiveWorker
        import time
        for backup_ok in (True,False):
            store=MagicMock();trial=dict(entry_claimed=False,binding='binding')
            store.get.return_value=dict(progress=trial)
            mode=dict(mode='live',requested='live',pilot_bot='bot')
            store.pool.connection.return_value.__enter__.return_value.execute.return_value.fetchone.return_value=dict(progress=mode)
            stop=threading.Event();exchange=Mock()
            w=LiveWorker(store,exchange,stop,lambda:None,'binding');w.recovered=True;w.last_reconcile=time.time()
            w.restore_market_activity=Mock();w.load_bots=Mock();w.reconcile=Mock();w.discover=Mock();w.stream=Mock();w.health=Mock();w.close_stream=Mock()
            w.probe_market_activity=Mock();w.refresh_market_activity=Mock();w.service_urgent_exits=Mock()
            w.trade=Mock(side_effect=lambda **kwargs:stop.set())
            with self.subTest(backup_ok=backup_ok),patch('services.live.runtime.initialize_trial',return_value=trial),patch('services.live.runtime.read_mode',return_value=mode),patch('services.demo.maintenance.object_store'),patch('services.demo.maintenance.backup',side_effect=None if backup_ok else RuntimeError('backup failed')):
                w.loop()
            w.probe_market_activity.assert_called_once();w.refresh_market_activity.assert_called_once()
            w.trade.assert_called_once_with(allow_entries=backup_ok);w.service_urgent_exits.assert_called_once()
            if not backup_ok:self.assertEqual(w.health.call_args.args[0],'attention')
    def test_large_configured_bid_is_clamped_to_one_yes_contract_for_pilot(self):
        from services.live.runtime import LiveWorker
        import time
        store=MagicMock();store.get.return_value=dict(progress=dict(entry_claimed=False))
        w=LiveWorker(store,Mock(),threading.Event(),lambda:None,'binding')
        w.quotes={'t':dict(open=time.time()-10,close=time.time()+890,series='S')};w.fee_verified={'t':time.time()}
        with patch('services.live.runtime.read_mode',return_value=dict(mode='live')),patch('services.demo.runtime.Worker.submit',return_value=True) as send:
            w.submit(entry(quantity=500,side='yes'));self.assertEqual(send.call_args.args[0]['quantity'],1)
            send.reset_mock();w.submit(entry(quantity=500,side='no'));send.assert_not_called()

class PilotShardFunding(unittest.TestCase):
    def test_aggregate_cash_does_not_fund_a_different_exchange_index(self):
        from services.live.runtime import TrialFunding
        w=Mock();w.account=dict(cash_cents=4200);w.exchange.call.return_value=dict(balance=0)
        self.assertFalse(TrialFunding(w).ensure(2,48,48,{}))
        w.exchange.call.assert_called_once_with('GET','/portfolio/balance',params=dict(exchange_index=2))
        w.store.alert.assert_called_once();self.assertIn('exchange index 2',w.funding_message)
    def test_only_one_contracts_cash_is_required_during_pilot(self):
        from services.live.runtime import TrialFunding
        w=Mock();w.account=dict(cash_cents=4200);w.exchange.call.return_value=dict(balance=3)
        self.assertTrue(TrialFunding(w).ensure(2,48,48,{}));self.assertIsNone(w.funding_message)
