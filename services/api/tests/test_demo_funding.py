import unittest,threading
from unittest.mock import patch
from services.demo.funding import ShardFunding
from services.demo.exchange import ExchangeFailure

class Store:
    def __init__(self):self.data={};self.events=[];self.alerts={}
    def get(self,key):return {'progress':self.data[key].copy()} if key in self.data else None
    def put(self,key,data,**kw):self.data[key]=data.copy()
    def event(self,kind,message,**kw):self.events.append((kind,kw))
    def alert(self,key,message,critical=False):self.alerts[key]=message
    def clear_alert(self,key):self.alerts.pop(key,None)
class Exchange:
    def __init__(self,store):self.store=store;self.calls=[];self.funded=False;self.lose_response=False;self.history=[]
    def call(self,method,path,**kw):
        self.calls.append((method,path,kw))
        if path=='/portfolio/subaccounts/balances':return {'subaccount_balances':[{'subaccount_number':0,'exchange_index':0,'balance':'90.00' if self.funded else '100.00'},{'subaccount_number':0,'exchange_index':2,'balance':'10.00' if self.funded else '0.00'},{'subaccount_number':1,'exchange_index':3,'balance':'9999.00'}]}
        if method=='POST':
            assert self.store.data['funding']['status']=='intent'
            assert kw['body']['amount']==100000 # $10 = 100,000 centicents.
            if self.lose_response:raise ExchangeFailure('connection',True)
            return {'transfer_id':'transfer-one'}
        if path.endswith('/transfers'):return {'transfers':self.history}
        if path=='/portfolio/intra_exchange_instance_transfers':return {'transfers':self.history}
        if path.endswith('/transfer-one'):
            body=self.store.data['funding']['body'];self.funded=True
            return {'transfer':dict(body,transfer_id='transfer-one',amount='10.0000',status='complete')}
        raise AssertionError(path)
class Funding(unittest.TestCase):
    def setup(self):
        store=Store();exchange=Exchange(store);return store,exchange,ShardFunding(store,exchange)
    def test_prefunding_is_durable_primary_only_and_uses_correct_amount_units(self):
        store,exchange,funding=self.setup()
        self.assertFalse(funding.ensure(2,90,1000,{}))
        body=store.data['funding']['body']
        self.assertEqual((body['source'],body['destination'],body['source_exchange_shard'],body['destination_exchange_shard'],body['amount']),('event_contract','event_contract',0,2,100000))
        self.assertEqual(len([c for c in exchange.calls if c[0]=='POST']),1)
    def test_pending_transfer_is_verified_before_an_order_can_use_it(self):
        store,exchange,funding=self.setup();funding.ensure(2,90,1000,{})
        self.assertFalse(funding.ensure(2,90,1000,{}))
        funding.poll_at=0
        self.assertTrue(funding.ensure(2,90,1000,{}))
        self.assertEqual(store.data['funding']['status'],'complete')
        self.assertEqual(store.events[0][0],'funding_transfer')
        self.assertEqual(len([c for c in exchange.calls if c[0]=='POST']),1)
    def test_ambiguous_transfer_survives_restart_without_duplicate_write(self):
        store,exchange,funding=self.setup();exchange.lose_response=True
        with self.assertRaises(ExchangeFailure):funding.ensure(2,90,1000,{})
        self.assertEqual(store.data['funding']['status'],'uncertain')
        funding=ShardFunding(store,exchange)
        self.assertFalse(funding.ensure(2,90,1000,{}))
        self.assertEqual(len([c for c in exchange.calls if c[0]=='POST']),1)
    def test_existing_resting_orders_and_numbered_subaccounts_are_not_swept(self):
        store,exchange,funding=self.setup()
        self.assertFalse(funding.ensure(2,90,1000,{0:10000}))
        self.assertFalse(any(c[0]=='POST' for c in exchange.calls))
        self.assertNotIn(3,funding.balances)
    def test_sufficient_shard_cash_uses_cached_reads_and_no_transfers(self):
        store,exchange,funding=self.setup();exchange.funded=True
        self.assertTrue(funding.ensure(2,90,1000,{}));self.assertTrue(funding.ensure(2,90,1000,{}))
        self.assertEqual(len(exchange.calls),1)
    def test_a_lost_response_is_recovered_by_client_id_and_verified_balances(self):
        store,exchange,funding=self.setup();exchange.lose_response=True
        with self.assertRaises(ExchangeFailure):funding.ensure(2,90,1000,{})
        body=store.data['funding']['body'];exchange.funded=True
        exchange.history=[dict(body,transfer_id='transfer-one',amount='10.0000',status='complete')]
        funding=ShardFunding(store,exchange)
        self.assertTrue(funding.ensure(2,90,1000,{}))
        self.assertEqual(len([c for c in exchange.calls if c[0]=='POST']),1)

class CategoryShardFunding(unittest.TestCase):
    def test_weather_can_use_default_shard_and_sports_can_move_funds_back_from_crypto(self):
        for destination in [0,3]:
            with self.subTest(destination=destination):
                store=Store()
                class Ex:
                    def __init__(self):self.writes=[]
                    def call(self,method,path,**kw):
                        if method=='GET':return {'subaccount_balances':[{'subaccount_number':0,'exchange_index':2,'balance':'100.00'}]}
                        self.writes.append(kw['body']);return {'transfer_id':'id'}
                exchange=Ex();funding=ShardFunding(store,exchange)
                self.assertFalse(funding.ensure(destination,100,1000,{2:1000}))
                body=exchange.writes[0]
                self.assertEqual((body['source_exchange_shard'],body['destination_exchange_shard']),(2,destination))
                self.assertEqual(body['amount'],100000)
