import unittest,json,threading
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.fernet import Fernet
import httpx
from services.api.demo_models import BotConfig
from services.demo.engine import candidates,entry_price,exit_price,quantity,wire_order
from services.demo.exchange import DemoSigner,Exchange,ExchangeFailure,encrypt_credentials,credentials
from services.demo.runtime import Worker

NOW=1800000000

def config(**kw):
    return BotConfig(name='Test',squares=[dict(asset='btc',min_price=60,max_price=69,min_minutes=0,max_minutes=5)],**kw).model_dump()
def bot(**kw):return dict(id='bot-1',config=config(**kw),revision=1,desired='running')
def quote(**kw):return dict(bid=60,ask=65,close=NOW+200,at=NOW,series='KXBTC15M',**kw)
class Rules(unittest.TestCase):
    def test_multisquare_one_shared_config(self):
        c=config();c['squares'].append(dict(c['squares'][0],min_price=70,max_price=79))
        self.assertEqual(len(BotConfig(**c).squares),2)
        self.assertRaises(ValueError,BotConfig,**dict(c,squares=[c['squares'][0]]*2))
    def test_bid_and_ask_qualification_independent_of_price_reference(self):
        q=quote();states={}
        result=candidates([bot(qualification='bid',price_reference='ask',adjustment_cents=-2)],{'t':q},states,NOW)
        self.assertEqual(result[0]['price'],63)
        c=bot(qualification='ask',price_reference='bid',adjustment_cents=1)
        self.assertEqual(candidates([c],{'t':q},{},NOW)[0]['price'],61)
    def test_no_side_is_evaluated_automatically(self):
        q=quote();q.update(bid=31,ask=35)
        result=candidates([bot()],{'t':q},{},NOW)
        self.assertEqual(result[0]['side'],'no');self.assertEqual(result[0]['price'],68)
    def test_maximum_caps_normal_bids_without_suppressing_lower_prices(self):
        self.assertEqual(entry_price(config(maximum_cents=62),quote(),'yes'),62)
        self.assertEqual(entry_price(config(maximum_cents=96),quote(),'yes'),64)
        self.assertEqual(entry_price(config(maximum_cents=65),quote(),'yes'),64)
        self.assertEqual(entry_price(config(maximum_cents=96,adjustment_cents=-5),quote(),'yes'),60)
        self.assertIsNone(entry_price(config(maximum_cents=96,adjustment_cents=1),quote(),'yes'))
        q=quote();q.update(bid=31,ask=35)
        self.assertEqual(entry_price(config(maximum_cents=96),q,'no'),68)
    def test_minimum_filters_without_replacing_calculated_bid(self):
        self.assertEqual(entry_price(config(minimum_cents=60,maximum_cents=96),quote(),'yes'),64)
        self.assertEqual(entry_price(config(minimum_cents=64,maximum_cents=96),quote(),'yes'),64)
        self.assertIsNone(entry_price(config(minimum_cents=65,maximum_cents=96),quote(),'yes'))
        q=quote();q.update(bid=31,ask=35)
        self.assertEqual(entry_price(config(minimum_cents=60,maximum_cents=96),q,'no'),68)
        self.assertIsNone(entry_price(config(minimum_cents=69,maximum_cents=96),q,'no'))
        self.assertEqual(entry_price(config(minimum_cents=None),quote(),'yes'),64)
        self.assertIsNone(entry_price(config(minimum_cents=60,maximum_cents=96,adjustment_cents=1),quote(),'yes'))
        self.assertRaises(ValueError,config,minimum_cents=97,maximum_cents=96)
        self.assertRaises(ValueError,config,minimum_cents=0)
        self.assertRaises(ValueError,config,minimum_cents=100)
    def test_minimum_recovery_does_not_require_leaving_qualifying_window(self):
        b=bot(minimum_cents=64);states={};q=quote();q['ask']=64
        self.assertEqual(candidates([b],{'t':q},states,NOW),[])
        q['ask']=65
        self.assertEqual(candidates([b],{'t':q},states,NOW)[0]['price'],64)
    def test_below_minimum_diagnostic_names_actual_reason(self):
        b=bot(minimum_cents=65);worker=Worker(FakeStore(),object(),threading.Event(),lambda:None)
        worker.bots=[b];worker.quotes={'t':quote()}
        info=worker.entry_diagnostics(NOW)[b['id']]
        self.assertEqual(info['minimum_blocked'],1);self.assertIn('below the minimum',info['message'])
        self.assertEqual(info['maker_blocked'],0)
    def test_submitted_condition_requires_genuine_reentry(self):
        b=bot();states={};q=quote()
        first=candidates([b],{'t':q},states,NOW)[0]
        states[b['id']][first['key']]['submitted']=True
        self.assertEqual(candidates([b],{'t':q},states,NOW),[])
        q['ask']=75;candidates([b],{'t':q},states,NOW)
        q['ask']=65;again=candidates([b],{'t':q},states,NOW)[0]
        self.assertEqual(again['cycle'],2)
    def test_stale_and_blocked_quotes_do_not_enter(self):
        q=quote();q['at']=NOW-6
        self.assertEqual(candidates([bot()],{'t':q},{},NOW),[])
        self.assertEqual(candidates([bot()],{'t':quote()},{},NOW,{'t'}),[])
    def test_first_time_then_expected_return_priority(self):
        a=bot();b=bot();b['id']='other';a['config']['squares'][0]['expected_roi']=2;b['config']['squares'][0]['expected_roi']=5
        result=candidates([a,b],{'t':quote()},{},NOW)
        self.assertEqual(result[0]['bot'],'other')
    def test_percentage_limits_reduce_size(self):
        self.assertEqual(quantity(config(),60,10000,10000,250,950),0)
        self.assertEqual(quantity(config(),60,10000,10000,0,0),1)
        self.assertEqual(quantity(config(),60,10000,30,0,0),0)
    def test_v2_single_yes_book_maps_all_four_actions(self):
        base=dict(ticker='t',client_id='id',price=65,quantity=2,close=NOW+100)
        for outcome,kind,expected_side,expected_price in [('yes','entry','bid','0.6500'),('no','entry','ask','0.3500'),('yes','exit','ask','0.6500'),('no','exit','bid','0.3500')]:
            payload=wire_order(dict(base,side=outcome,kind=kind))
            self.assertEqual(payload['side'],expected_side);self.assertEqual(payload['price'],expected_price)
            self.assertTrue(payload['post_only']);self.assertNotIn('reduce_only',payload)
            self.assertEqual(payload['expiration_time'],NOW+100)
        self.assertEqual(exit_price(quote(),'yes'),66)
    def test_manual_threshold_requires_value(self):
        self.assertRaises(ValueError,config,loss_mode='manual')

class Transport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pem=rsa.generate_private_key(public_exponent=65537,key_size=2048).private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    def test_credentials_are_encrypted_and_not_production_fallback(self):
        key=Fernet.generate_key().decode();sealed=encrypt_credentials(key,'demo-id',self.pem)
        self.assertNotIn('PRIVATE KEY',sealed)
        class Store:
            def get(self,key):return dict(progress=dict(encrypted=sealed))
        signer=credentials(Store(),dict(DEMO_VAULT_KEY=key))
        self.assertEqual(signer.identifier,'demo-id')
        self.assertTrue(signer.headers('POST','/trade-api/v2/portfolio/events/orders')['KALSHI-ACCESS-SIGNATURE'])
    def test_transport_uses_fixed_demo_endpoint_and_no_ambiguous_retry(self):
        seen=[]
        def handler(request):seen.append(str(request.url));raise httpx.ReadTimeout('private details')
        exchange=Exchange(DemoSigner('key',self.pem),client=httpx.Client(transport=httpx.MockTransport(handler)))
        with self.assertRaises(ExchangeFailure) as error:exchange.call('POST','/portfolio/events/orders',body={})
        self.assertTrue(error.exception.ambiguous);self.assertEqual(len(seen),1)
        self.assertTrue(seen[0].startswith('https://external-api.demo.kalshi.co/'))
    def test_paginated_reconciliation_never_accepts_truncation(self):
        def handler(request):return httpx.Response(200,json=dict(orders=[],cursor='same'))
        ex=Exchange(DemoSigner('key',self.pem),client=httpx.Client(transport=httpx.MockTransport(handler)))
        with patch('services.demo.exchange.time.sleep'):
            self.assertRaises(ExchangeFailure,list,ex.pages('/portfolio/orders','orders'))

class FakeStore:
    def __init__(self):self.saved=[];self.events=[]
    def put(self,key,data,parameters=None):self.saved.append((key,data,parameters))
    def event(self,kind,message,**kw):self.events.append(kind)
class WorkerRecovery(unittest.TestCase):
    def test_durable_intent_precedes_network_and_timeout_never_resubmits(self):
        store=FakeStore()
        class Ex:
            def submit(self,intent):
                assert store.saved[0][0]=='order/one'
                raise ExchangeFailure('connection',True)
        worker=Worker(store,Ex(),threading.Event(),lambda:None)
        order=dict(client_id='one',kind='entry',bot='b',ticker='t',side='yes',price=65,quantity=2,close=NOW,status='intent',remaining=0,filled=0)
        with self.assertRaises(ExchangeFailure):worker.submit(order)
        self.assertEqual(store.saved[-1][1]['status'],'uncertain');self.assertIn('t',worker.blocked)
        self.assertFalse(worker.recovered);self.assertIn('order_uncertain',store.events)
    def test_preserved_orders_are_not_canceled_by_worker_shutdown(self):
        class Socket:
            def close(self):pass
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None);worker.socket=Socket();worker.quotes={'t':quote()}
        worker.close_stream();self.assertEqual(worker.quotes['t']['at'],0);self.assertEqual(worker.store.events,[])

class RecoveryPreservesBids(unittest.TestCase):
    def test_stale_reconnect_does_not_cancel_resting_valid_bid(self):
        b=bot();worker=Worker(FakeStore(),object(),threading.Event(),lambda:None)
        worker.bots=[b];q=quote();q['at']=0;worker.quotes={'t':q}
        worker.orders=[dict(kind='entry',bot=b['id'],revision=1,ticker='t',side='yes',square=0,remaining=1,filled=0,close=NOW+200,status='resting')]
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.trade()
        self.assertEqual(worker.store.events,[])
    def test_fresh_invalid_condition_cancels_bid(self):
        b=bot();worker=Worker(FakeStore(),object(),threading.Event(),lambda:None);worker.bots=[b];q=quote();q['ask']=75;worker.quotes={'t':q}
        order=dict(kind='entry',bot=b['id'],revision=1,ticker='t',side='yes',square=0,remaining=1,filled=0,close=NOW+200,status='resting');worker.orders=[order]
        with patch.object(worker,'cancel') as cancel,patch('services.demo.runtime.time.time',return_value=NOW):
            worker.trade();cancel.assert_called_once()

class ArchiveIntegrity(unittest.TestCase):
    def test_verified_roundtrip_and_tamper_rejection(self):
        from services.demo.maintenance import put_verified,read_verified
        import io
        class Objects:
            bucket='private'
            def __init__(self):self.client=self;self.objects={}
            def put_object(self,**kw):self.objects[kw['Key']]=kw['Body']
            def get_object(self,**kw):
                data=self.objects[kw['Key']];return dict(ContentLength=len(data),Body=io.BytesIO(data))
        objects=Objects();payload=[dict(id='one',parameters={'kind':'fill'},progress={'details':{'price':65}})]
        reference=put_verified(objects,'events',payload)
        self.assertEqual(read_verified(objects,reference),payload)
        objects.objects[reference['key']]=objects.objects[reference['key']][:-1]+b'X'
        self.assertRaises(ValueError,read_verified,objects,reference)

class SupportedDemoKeys(unittest.TestCase):
    def test_default_ed25519_key_signs_rest_and_websocket_correctly(self):
        import base64
        from cryptography.hazmat.primitives.asymmetric import ed25519
        key=ed25519.Ed25519PrivateKey.generate()
        pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        signer=DemoSigner(' demo-key ',pem)
        for path in ['/trade-api/v2/portfolio/balance?subaccount=0','/trade-api/ws/v2']:
            headers=signer.headers('GET',path)
            self.assertEqual(headers['KALSHI-ACCESS-KEY'],'demo-key')
            key.public_key().verify(base64.b64decode(headers['KALSHI-ACCESS-SIGNATURE']),(headers['KALSHI-ACCESS-TIMESTAMP']+'GET'+path.split('?')[0]).encode())
    def test_rsa_pkcs1_and_pkcs8_and_mobile_line_formatting(self):
        from services.demo.exchange import normalize_pem
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        for format in [serialization.PrivateFormat.TraditionalOpenSSL,serialization.PrivateFormat.PKCS8]:
            pem=key.private_bytes(serialization.Encoding.PEM,format,serialization.NoEncryption()).decode()
            for text in [pem,pem.replace('\n','\\n'),'\ufeff'+pem.replace('\n','\r\n'),pem.replace('\n',' '),'```text\n'+pem+'```']:
                self.assertEqual(DemoSigner('id',text).key.public_key().public_numbers(),key.public_key().public_numbers())
    def test_ed25519_encrypted_storage_roundtrip(self):
        from cryptography.hazmat.primitives.asymmetric import ed25519
        key=ed25519.Ed25519PrivateKey.generate();pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        vault=Fernet.generate_key().decode();sealed=encrypt_credentials(vault,'id',pem)
        class Store:
            def get(self,key):return dict(progress=dict(encrypted=sealed))
        self.assertIsInstance(credentials(Store(),dict(DEMO_VAULT_KEY=vault)).key,ed25519.Ed25519PrivateKey)
    def test_feedback_does_not_echo_private_input(self):
        from services.demo.exchange import CredentialInputError
        with self.assertRaises(CredentialInputError) as error:DemoSigner('id','secret-invalid-data')
        self.assertNotIn('secret-invalid-data',str(error.exception))

class RejectionDiagnostics(unittest.TestCase):
    def test_error_body_is_bounded_and_only_safe_code_and_reason_escape(self):
        signer=type('Signer',(),{'headers':lambda *a:{}})()
        ex=Exchange(signer,client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(400,json={'error':{'code':'invalid_order','message':'post-only would cross: PRIVATE PROVIDER DETAIL'}}))))
        with self.assertRaises(ExchangeFailure) as caught:ex.call('POST','/portfolio/events/orders',body={})
        error=caught.exception
        self.assertEqual((error.status,error.provider_code,error.reason),(400,'invalid_order','post_only'))
        self.assertFalse(error.ambiguous)
        self.assertNotIn('PRIVATE',str(error.__dict__))
    def test_cancel_routes_by_ticker_to_correct_exchange_shard(self):
        seen=[];signer=type('Signer',(),{'headers':lambda *a:{}})()
        ex=Exchange(signer,client=httpx.Client(transport=httpx.MockTransport(lambda request:(seen.append(request) or httpx.Response(200,json={'reduced_by':'1.00'})))))
        ex.cancel('order-id','KXBTC15M-TEST')
        self.assertEqual(seen[0].url.params['market_ticker'],'KXBTC15M-TEST')
        self.assertEqual(seen[0].url.params['exchange_index'],'-1')
    def test_health_distinguishes_stale_quotes_and_spending_limits(self):
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None)
        b=bot();worker.bots=[b];worker.quotes={'t':quote()};worker.account={'equity_cents':10000,'cash_cents':0}
        self.assertEqual(worker.entry_diagnostics(NOW)[b['id']]['budget_blocked'],1)
        worker.quotes['t']['at']=NOW-6
        info=worker.entry_diagnostics(NOW)[b['id']]
        self.assertEqual(info['fresh'],0);self.assertIn('streaming',info['message'])

class CategoryRouting(unittest.TestCase):
    def test_both_hourly_weather_variants_daily_weather_and_sports_qualify_and_route(self):
        from services.demo.runtime import quote as parse_quote
        cases=[('weather','KXTEMPNYCH',0),('weather','KXTEMPNYCHS',0),('weather_daily','KXHIGHNY',0),('sports','KXNFLGAME',0),('sports','KXNBAGAME',3),('sports','KXATPMATCH',3)]
        for asset,series,index in cases:
            with self.subTest(asset=asset,series=series):
                b=bot();b['config']['squares'][0]['asset']=asset
                raw={'ticker':series+'-TEST','yes_bid_dollars':'0.6000','yes_ask_dollars':'0.6500','close_time':NOW+200,'exchange_index':index,'status':'active'}
                ticker,q=parse_quote(raw,NOW)
                options=candidates([b],{ticker:q},{},NOW)
                self.assertEqual(len(options),1)
                intent=dict(options[0],kind='entry',client_id='test',quantity=1,close=q['close'],exchange_index=q['exchange_index'])
                self.assertEqual(wire_order(intent)['exchange_index'],index)
                self.assertTrue(wire_order(intent)['post_only'])
    def test_rest_discovery_cannot_replace_stream_prices_or_borrow_their_freshness(self):
        raw=dict(ticker='t',yes_bid_dollars='0.0100',yes_ask_dollars='0.0200',close_time=NOW+300,exchange_index=2)
        class Ex:
            def call(self,*args,**kw):return {'markets':[raw]}
        for age in (1,30):
            worker=Worker(FakeStore(),Ex(),threading.Event(),lambda:None)
            worker.bots=[bot()];worker.quotes={'t':dict(quote(),at=NOW-age)}
            with patch('services.demo.runtime.time.time',return_value=NOW):worker.discover()
            self.assertEqual((worker.quotes['t']['bid'],worker.quotes['t']['ask'],worker.quotes['t']['at']),(60,65,NOW-age))
            self.assertEqual(worker.quotes['t']['close'],NOW+300)
            self.assertEqual(worker.quotes['t']['exchange_index'],2)
        worker.quotes={}
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.discover()
        self.assertEqual(worker.quotes['t']['at'],0)
        self.assertEqual(candidates(worker.bots,worker.quotes,{},NOW),[])

    def test_every_configured_series_is_scanned_while_existing_positions_are_refreshed(self):
        from services.research.reports import SERIES
        class Ex:
            def __init__(self):self.calls=[]
            def call(self,method,path,**kw):self.calls.append(kw['params']);return {'markets':[]}
        ex=Ex();worker=Worker(FakeStore(),ex,threading.Event(),lambda:None)
        worker.bots=[bot()];worker.orders=[{'ticker':'held'}]
        # Ten series exposed a permanent skipped-slot bug when both tasks shared
        # one counter; include all actual categories in a second pass as well.
        for configured in [set('S'+str(i) for i in range(10)),set().union(SERIES['weather'],SERIES['weather_daily'],SERIES['sports'])]:
            ex.calls=[];worker.series_index=0;worker.discovery_turn=0
            with patch.dict(SERIES,btc=configured),patch('services.demo.runtime.time.time',return_value=NOW):
                for _ in range(len(configured)+1+(len(configured)//4)):worker.discover()
            observed={p['series_ticker'] for p in ex.calls if 'series_ticker' in p}
            self.assertEqual(observed,configured)
            self.assertTrue(any('tickers' in p for p in ex.calls))

class ProtectiveThresholds(unittest.TestCase):
    def worker(self,side='yes',bid=55,ask=59,mode='manual'):
        b=bot(loss_mode=mode,**({'loss_cents':60} if mode=='manual' else {}))
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None);worker.bots=[b]
        q=quote();q.update(bid=bid,ask=ask);worker.quotes={'t':q}
        worker.orders=[dict(client_id='held-entry',kind='entry',bot=b['id'],revision=1,ticker='t',side=side,square=0,price=65,quantity=1,remaining=0,filled=1,sold=0,close=NOW+200,status='held')]
        return worker
    def test_stream_yields_on_first_crossing_before_later_low_quote(self):
        worker=self.worker(bid=55,ask=61)
        worker.subscription={'t'}
        messages=[dict(type='orderbook_snapshot',sid=2,seq=1,sending_ts_ms=NOW*1000,msg=dict(market_ticker='t',clock=1,yes_dollars_fp=[['0.50','1']],no_dollars_fp=[['0.46','1']])),
            dict(type='orderbook_delta',sid=2,seq=2,sending_ts_ms=NOW*1000,msg=dict(market_ticker='t',clock=2,ts_ms=NOW*1000,side='no',price_dollars='0.98',delta_fp='1'))]
        class Socket:
            def recv(self,**kw):
                if not messages:raise TimeoutError
                return json.dumps(messages.pop(0))
        worker.socket=Socket()
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.stream()
        self.assertEqual(worker.quotes['t']['ask'],54)
        self.assertEqual(len(messages),1)
        self.assertTrue(worker.orders[0]['exit_triggered'])
        with patch.object(worker,'submit') as submit,patch('services.demo.runtime.time.time',return_value=NOW):worker.trade()
        self.assertEqual(submit.call_args.args[0]['price'],55)
        self.assertEqual(worker.store.events.count('exit_trigger'),1)

    def test_manual_exit_triggers_on_current_ask_without_waiting_for_two_cents(self):
        worker=self.worker()
        with patch.object(worker,'submit') as submit,patch('services.demo.runtime.time.time',return_value=NOW):worker.trade()
        intent=submit.call_args.args[0]
        self.assertEqual((intent['kind'],intent['side'],intent['price']),('exit','yes',60))
        self.assertIn('exit_trigger',worker.store.events)
    def test_no_exit_uses_no_quote_rather_than_yes_quote(self):
        worker=self.worker(side='no',bid=41,ask=45)
        with patch.object(worker,'submit') as submit,patch('services.demo.runtime.time.time',return_value=NOW):worker.trade()
        self.assertEqual(submit.call_args.args[0]['price'],60)
    def test_above_threshold_and_disabled_protection_do_not_exit(self):
        for worker in [self.worker(ask=61),self.worker(mode='off')]:
            with patch.object(worker,'submit') as submit,patch('services.demo.runtime.time.time',return_value=NOW):worker.trade()
            submit.assert_not_called()

class AskEntryProtection(unittest.TestCase):
    def test_wide_bid_ask_gap_does_not_trigger_a_bid_based_stop(self):
        b=bot(loss_mode='manual',loss_cents=55,maximum_cents=96)
        b['config']['squares'][0].update(min_price=90,max_price=99)
        q=quote();q.update(bid=1,ask=99)
        self.assertTrue(candidates([b],{'t':q},{},NOW))
    def test_entry_skips_when_current_ask_already_meets_the_exit_trigger(self):
        b=bot(loss_mode='manual',loss_cents=55)
        b['config']['squares'][0].update(min_price=40,max_price=69)
        q=quote();q.update(bid=1,ask=50)
        self.assertEqual(candidates([b],{'t':q},{},NOW),[])
        b['config']['loss_mode']='off'
        self.assertTrue(candidates([b],{'t':q},{},NOW))
    def test_condition_can_enter_if_ask_recovers_without_leaving_the_selected_window(self):
        b=bot(loss_mode='manual',loss_cents=65);states={};q=quote()
        self.assertEqual(candidates([b],{'t':q},states,NOW),[])
        q['ask']=66
        self.assertEqual(len(candidates([b],{'t':q},states,NOW)),1)
    def test_resting_entry_cancels_when_fresh_ask_already_violates_exit_rule(self):
        b=bot(loss_mode='manual',loss_cents=65)
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None);worker.bots=[b];worker.quotes={'t':quote()}
        worker.orders=[dict(kind='entry',bot=b['id'],revision=1,ticker='t',side='yes',square=0,remaining=1,filled=0,close=NOW+200,status='resting')]
        with patch.object(worker,'cancel') as cancel,patch('services.demo.runtime.time.time',return_value=NOW):worker.trade()
        cancel.assert_called_once()

class DownwardExitRatchet(unittest.TestCase):
    def test_ask_reference_and_ratchet_for_both_outcomes(self):
        q=quote();q.update(bid=1,ask=54)
        self.assertEqual(exit_price(q,'yes'),55)
        q['ask']=60;self.assertEqual(exit_price(q,'yes',55),55)
        q['ask']=50;self.assertEqual(exit_price(q,'yes',55),51)
        q.update(bid=46,ask=99);self.assertEqual(exit_price(q,'no'),55)
        q['bid']=40;self.assertEqual(exit_price(q,'no',55),55)
        q['bid']=50;self.assertEqual(exit_price(q,'no',55),51)
        q['ask']=99;self.assertIsNone(exit_price(q,'yes'))
        self.assertEqual(exit_price(q,'yes',55),55)
    def worker(self,ask=60):
        b=bot(loss_mode='manual',loss_cents=55)
        w=Worker(FakeStore(),object(),threading.Event(),lambda:None);w.bots=[b];q=quote();q.update(bid=min(40,ask-1),ask=ask);w.quotes={'t':q}
        parent=dict(client_id='entry',kind='entry',bot=b['id'],revision=1,ticker='t',side='yes',square=0,price=96,quantity=1,remaining=0,filled=1,sold=0,close=NOW+200,status='held',exit_triggered=True,exit_reference='ask',exit_ceiling_cents=55)
        child=dict(client_id='exit',parent='entry',kind='exit',bot=b['id'],ticker='t',side='yes',price=55,remaining=1,filled=0,status='resting')
        w.orders=[parent,child];return w,parent,child
    def test_rising_ask_does_not_cancel_or_raise_the_resting_exit(self):
        w,parent,child=self.worker(60)
        with patch.object(w,'cancel') as cancel,patch.object(w,'submit') as submit,patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        cancel.assert_not_called();submit.assert_not_called();self.assertEqual(parent['exit_ceiling_cents'],55)
    def test_lower_price_is_persisted_before_cancel_and_not_raised_between_replace_steps(self):
        w,parent,child=self.worker(50)
        with patch.object(w,'cancel') as cancel,patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        self.assertEqual(parent['exit_ceiling_cents'],51);cancel.assert_called_once()
        self.assertEqual(w.store.saved[-1][2]['exit_ceiling_cents'],51)
        w.orders=[parent];w.quotes['t']['ask']=65
        with patch.object(w,'submit') as submit,patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        self.assertEqual(submit.call_args.args[0]['price'],51)
    def test_legacy_bid_only_trigger_is_reset_without_changing_completed_sales(self):
        w,parent,child=self.worker(99);w.orders=[parent];parent.pop('exit_reference');w.recovered=True
        w.legacy_exit_evidence={'entry':dict(threshold=55,quote=dict(bid=1,ask=99))}
        with patch('services.demo.runtime.time.time',return_value=NOW):self.assertFalse(w.upgrade_legacy_exits())
        self.assertFalse(parent['exit_triggered']);self.assertEqual(parent['exit_reference'],'ask');self.assertNotIn('exit_ceiling_cents',parent)
        self.assertIn('exit_policy_updated',w.store.events)

    def test_rebound_between_cancel_and_replace_never_raises_or_crosses_maker_limit(self):
        w,parent,child=self.worker(65);w.orders=[parent];w.quotes['t'].update(bid=60,ask=65)
        with patch.object(w,'submit') as submit,patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        submit.assert_not_called();self.assertEqual(parent['exit_ceiling_cents'],55)
        self.assertTrue(w.entry_diagnostics(NOW)[parent['bot']]['exit_waiting'])
