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
    def test_maximum_overrides_adjustment_but_never_crosses(self):
        self.assertEqual(entry_price(config(maximum_cents=62),quote(),'yes'),62)
        self.assertIsNone(entry_price(config(maximum_cents=65),quote(),'yes'))
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
        self.assertEqual(exit_price(quote(),'yes'),61)
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
