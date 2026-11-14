"""Isolated, owner-confirmed onboarding; all exchange traffic is simulated."""
import json,unittest
from unittest.mock import Mock,patch
from uuid import uuid4
import httpx
from services.live.onboarding import SetupExchange,SetupError,Onboarding,validate_write,public,CONFIRM
from services.api.tests.test_live_execution import signer
from services.api.tests import test_demo_postgres as fixtures
from services.live.store import LiveStore

class SetupTransport(unittest.TestCase):
    def test_only_fixed_fifty_dollar_funding_and_restricted_permissions_allowed(self):
        body=dict(from_subaccount=0,to_subaccount=2,amount_cents=5000,exchange_index=1,client_transfer_id=str(uuid4()))
        validate_write('/portfolio/subaccounts/transfer',body)
        for changed in [dict(amount_cents=5001),dict(from_subaccount=2),dict(to_subaccount=0),dict(amount_cents=True),dict(exchange_index=True),dict(extra=1)]:
            with self.subTest(changed=changed),self.assertRaises(SetupError):validate_write('/portfolio/subaccounts/transfer',dict(body,**changed))
        key=dict(name='Money Tree Trading '+str(uuid4()),subaccount=2,scopes=['read','write::trade'],key_type='ed25519')
        validate_write('/api_keys/generate',key)
        with self.assertRaises(SetupError):validate_write('/api_keys/generate',dict(key,scopes=['read','write']))
    def test_primary_preparation_uses_centicents_and_never_numbered_accounts(self):
        body=dict(source='event_contract',destination='event_contract',source_subaccount=0,destination_subaccount=0,source_exchange_shard=0,destination_exchange_shard=1,amount=500000,client_transfer_id=str(uuid4()))
        validate_write('/portfolio/intra_exchange_instance_transfer',body)
        for change in [dict(amount=500001),dict(amount=500100),dict(destination_subaccount=2),dict(source='margin')]:
            with self.subTest(change=change),self.assertRaises(SetupError):validate_write('/portfolio/intra_exchange_instance_transfer',dict(body,**change))
    def test_no_trade_or_unapproved_post_and_empty_success_is_supported(self):
        ex=SetupExchange.__new__(SetupExchange);ex.signer=signer();seen=[];ex.approved=None
        ex.client=httpx.Client(transport=httpx.MockTransport(lambda r:(seen.append(r),httpx.Response(200,content=b''))[1]))
        try:
            for method,path in [('POST','/portfolio/orders'),('DELETE','/portfolio/orders/a'),('POST','/portfolio/subaccounts')]:
                with self.assertRaises(SetupError):ex.call(method,path,body={})
            self.assertEqual(seen,[])
            self.assertEqual(ex.write('/account/api_usage_level/upgrade',{}),{})
            self.assertIsNone(ex.approved);self.assertEqual(len(seen),1)
        finally:ex.close()
    def test_cash_recovery_reads_the_namespaced_store_key_once(self):
        store=Mock();draft=str(uuid4());expected='onboarding-op/'+draft+'/fund'
        store.get.side_effect=lambda key:dict(progress=dict(body={})) if key==expected else None
        service=Onboarding(store,Mock(),None);service.finish=Mock()
        state=dict(id=draft,busy='fund',account_cents=5000,market_cents=5000)
        service.reconcile(state)
        store.get.assert_called_once_with(expected);service.finish.assert_called_once()
        service.exchange.call.assert_not_called()
    def test_public_progress_never_contains_setup_or_trading_secrets(self):
        result=public(dict(id='safe',private_key='secret',binding='fingerprint',encrypted='secret',body={'private_key':'secret'}))
        self.assertNotIn('secret',json.dumps(result));self.assertNotIn('binding',result)
    def test_basic_account_checks_do_not_request_advanced_subaccount_api(self):
        exchange=Mock();exchange.signer.identifier='setup'
        responses={'/api_keys':dict(api_keys=[dict(api_key_id='setup',scopes=['read','write'])]),'/account/limits':dict(usage_tier='basic'),'/markets':dict(markets=[])}
        exchange.call.side_effect=lambda method,path,**kw:responses[path]
        store=Mock();store.get.return_value=dict(parameters=dict(config=dict(squares=[dict(asset='btc')])))
        snap=Onboarding(store,exchange,None).snapshot('bot')
        self.assertFalse(snap['eligible']);self.assertTrue(snap['can_write'])
        self.assertFalse(any(c.args[1]=='/portfolio/subaccounts/balances' for c in exchange.call.call_args_list))

@unittest.skipUnless(fixtures.URL,'Disposable PostgreSQL is required')
class SetupPostgres(unittest.TestCase):
    setUpClass=classmethod(fixtures.DemoPostgres.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.DemoPostgres.tearDownClass.__func__)
    setUp=fixtures.DemoPostgres.setUp
    tearDown=fixtures.DemoPostgres.tearDown
    def scenario(self,subaccount=2):
        self.live=LiveStore(self.store.pool);self.bot=str(uuid4());self.draft=str(uuid4())
        self.exchange=Mock();self.exchange.signer.identifier='setup-key'
        from services.live.onboarding import fingerprint
        self.live.put('onboarding',dict(id=self.draft,bot=self.bot,binding=fingerprint(self.exchange),subaccount=subaccount,exchange_index=1,busy=None,connected=False))
        self.service=Onboarding(self.live,self.exchange,None)
        self.snapshot=dict(tier='advanced',eligible=True,can_write=True,exchange_index=1,market_running=True,account_cents=0,market_cents=0,primary_market_cents=5000,prepare_cents=0,source_index=None)
        self.service.snapshot=Mock(return_value=self.snapshot)
    def run_action(self,action):return self.service.perform(action,self.bot,self.draft,CONFIRM[action])
    def test_fund_intent_commits_before_wire_and_never_sends_second_fifty(self):
        self.scenario()
        def write(path,body):
            op=self.live.get('onboarding-op/'+self.draft+'/fund')['progress']
            self.assertEqual(op['body'],body);self.assertEqual(op['status'],'intent')
            self.assertEqual(self.live.get('onboarding')['progress']['busy'],'fund');return {}
        self.exchange.write.side_effect=write;self.exchange.call.return_value=dict(balance=5000,portfolio_value=0)
        self.assertEqual(self.run_action('fund')['account_cents'],5000)
        with self.assertRaises(SetupError):self.run_action('fund')
        self.assertEqual(self.exchange.write.call_count,1)
    def test_lost_funding_response_is_resolved_by_cash_without_repeat_write(self):
        self.scenario();self.exchange.write.side_effect=TimeoutError('private upstream content')
        with self.assertRaisesRegex(SetupError,'could not be fully verified'):self.run_action('fund')
        state=self.live.get('onboarding')['progress'];self.assertEqual(state['busy'],'fund')
        state.update(account_cents=5000,market_cents=5000)
        self.service.reconcile(state)
        self.assertIsNone(self.live.get('onboarding')['progress']['busy'])
        with self.assertRaises(SetupError):self.run_action('fund')
        self.assertEqual(self.exchange.write.call_count,1)
        self.assertNotIn('private upstream content',json.dumps(self.live.get('onboarding-op/'+self.draft+'/fund')['progress']))
    def test_ambiguous_account_creation_remains_blocked(self):
        self.scenario(None);self.exchange.write.side_effect=TimeoutError()
        with self.assertRaises(SetupError):self.run_action('create')
        with self.assertRaises(SetupError):self.run_action('create')
        self.assertEqual(self.exchange.write.call_count,1)
    def test_live_mode_and_missing_confirmation_prevent_all_writes(self):
        self.scenario();self.live.put('trial',dict(started=True))
        with self.assertRaises(SetupError):self.run_action('fund')
        with self.assertRaises(SetupError):self.service.perform('fund',self.bot,self.draft,'')
        self.exchange.write.assert_not_called()
    def test_only_verified_restricted_child_key_is_saved(self):
        from cryptography.fernet import Fernet
        self.scenario();self.service.vault=Fernet.generate_key().decode();self.snapshot.update(account_cents=5000,market_cents=5000)
        self.exchange.write.return_value=dict(api_key_id='child',private_key='child-secret')
        encrypted=dict(encrypted='ciphertext',subaccount=2,binding='child-proof')
        with patch('services.live.exchange.verified_connection',return_value=encrypted) as verify:
            result=self.run_action('connect')
        verify.assert_called_once_with('child','child-secret',2,self.service.vault)
        self.assertTrue(result['connected']);self.assertEqual(self.live.get('credentials')['progress'],encrypted)
        body=self.exchange.write.call_args.args[1];self.assertEqual(body['scopes'],['read','write::trade']);self.assertEqual(body['subaccount'],2)
        with self.store.pool.connection() as c:rows=c.execute('SELECT progress FROM research_job').fetchall()
        self.assertNotIn('child-secret',json.dumps([r['progress'] for r in rows]))

    def test_owner_endpoint_redacts_errors_and_keeps_key_out_of_database(self):
        self.scenario()
        payload=dict(action='check',bot=self.bot,key_id='temporary-key',private_key='temporary-private-secret'*8)
        with patch('services.live.onboarding.SetupExchange') as exchange,patch('services.live.onboarding.Onboarding') as onboarding:
            onboarding.return_value.check.return_value=dict(id=self.draft,bot=self.bot)
            response=self.client.post('/live/onboarding',json=payload)
            self.assertEqual(response.status_code,200,response.text)
            self.assertFalse(response.json()['execution_enabled'])
            exchange.return_value.close.assert_called_once()
            onboarding.return_value.check.side_effect=RuntimeError(payload['private_key'])
            response=self.client.post('/live/onboarding',json=payload)
            self.assertEqual(response.status_code,503);self.assertNotIn('temporary-private-secret',response.text)
        self.client.headers.pop('x-csrf-token')
        self.assertEqual(self.client.post('/live/onboarding',json=payload).status_code,403)
