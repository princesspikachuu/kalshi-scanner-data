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
    def test_pending_transfer_does_not_block_verified_cash_on_other_shards(self):
        store,exchange,funding=self.setup();funding.ensure(2,90,1000,{})
        self.assertTrue(funding.ensure(0,90,1000,{}))
        self.assertFalse(funding.ensure(0,9500,10000,{})) # Pending source debit stays reserved.
        self.assertFalse(funding.ensure(0,90,1000,{0:10000}))
        self.assertFalse(funding.ensure(2,90,1000,{}))
        self.assertEqual(len([c for c in exchange.calls if c[0]=='POST']),1)
        self.assertEqual(funding.waits[2]['available_cents'],0)
        self.assertEqual(store.data['funding']['status'],'pending')
    def test_completed_transfer_is_not_stuck_when_current_cash_has_already_changed(self):
        store,exchange,funding=self.setup();funding.ensure(2,90,1000,{})
        original=exchange.call
        def changed_cash(method,path,**kw):
            result=original(method,path,**kw)
            if path=='/portfolio/subaccounts/balances':
                for row in result['subaccount_balances']:
                    if row['exchange_index']==2:row['balance']='0.25'
            return result
        exchange.call=changed_cash;funding.poll_at=0
        self.assertFalse(funding.pending())
        self.assertEqual(store.data['funding']['status'],'complete')
        self.assertEqual(funding.balances[2],25)
        self.assertEqual(len([c for c in exchange.calls if c[0]=='POST']),1)
        self.assertEqual(len(store.events),1)
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

class FundingCorrections(unittest.TestCase):
    def test_confirmation_progresses_without_any_order_candidates(self):
        from services.demo.runtime import Worker
        store=Store();exchange=Exchange(store);funding=ShardFunding(store,exchange)
        funding.ensure(2,90,1000,{})
        worker=Worker(store,exchange,threading.Event(),lambda:None)
        self.assertIsNone(worker.funding)
        worker.poll_funding()
        self.assertEqual(store.data['funding']['status'],'complete')
        self.assertEqual(len([c for c in exchange.calls if c[0]=='POST']),1)

    def test_completed_record_clears_alert_left_by_a_crash(self):
        store=Store();store.data['funding']=dict(status='complete',body={})
        store.alert('funding','Demo collateral transfer confirmation is incomplete.')
        funding=ShardFunding(store,Exchange(store))
        self.assertFalse(funding.poll())
        self.assertNotIn('funding',store.alerts)

    def test_history_search_advances_past_the_first_thousand_without_reposting(self):
        store=Store();exchange=Exchange(store);exchange.lose_response=True
        funding=ShardFunding(store,exchange)
        with self.assertRaises(ExchangeFailure):funding.ensure(2,90,1000,{})
        body=store.data['funding']['body'];original=exchange.call;seen=[]
        def paged(method,path,**kw):
            if path=='/portfolio/intra_exchange_instance_transfers':
                page=int(kw.get('params',{}).get('cursor',0));seen.append(page)
                if page==6:
                    exchange.funded=True
                    return dict(transfers=[dict(body,transfer_id='transfer-one',amount='10.0000',status='complete')])
                return dict(transfers=[],cursor=str(page+1))
            return original(method,path,**kw)
        exchange.call=paged
        funding.poll_at=0;self.assertTrue(funding.poll())
        funding.poll_at=0;self.assertFalse(funding.poll())
        self.assertEqual(seen,list(range(7)))
        self.assertEqual(store.data['funding']['status'],'complete')
        self.assertEqual(len([c for c in exchange.calls if c[0]=='POST']),1)

    def test_lookup_failure_keeps_reservations_and_allows_already_funded_shards(self):
        store=Store();exchange=Exchange(store);funding=ShardFunding(store,exchange)
        funding.ensure(2,90,1000,{})
        original=exchange.call
        def unavailable(method,path,**kw):
            if path.endswith('/transfer-one'):raise ExchangeFailure('connection')
            return original(method,path,**kw)
        exchange.call=unavailable;funding.poll_at=0
        self.assertTrue(funding.ensure(0,90,1000,{}))
        self.assertFalse(funding.ensure(0,9500,10000,{}))
        self.assertFalse(funding.ensure(2,90,1000,{}))
        self.assertEqual(store.data['funding']['status'],'pending')
        self.assertEqual(len([c for c in exchange.calls if c[0]=='POST']),1)

    def test_individual_404_falls_back_to_matching_client_history(self):
        store=Store();exchange=Exchange(store);funding=ShardFunding(store,exchange)
        funding.ensure(2,90,1000,{})
        body=store.data['funding']['body'];exchange.funded=True
        exchange.history=[dict(body,transfer_id='transfer-one',amount='10.0000',status='complete')]
        original=exchange.call
        def missing(method,path,**kw):
            if path.endswith('/transfer-one'):raise ExchangeFailure('exchange_rejected',status=404)
            return original(method,path,**kw)
        exchange.call=missing;funding.poll_at=0
        self.assertFalse(funding.poll())
        self.assertEqual(store.data['funding']['status'],'complete')
        self.assertEqual(len([c for c in exchange.calls if c[0]=='POST']),1)

    def test_resting_limits_reserve_price_not_full_contract_and_keep_manual_orders(self):
        from services.demo.funding import resting_reservation
        base=dict(remaining_count_fp='10.25',yes_price_dollars='0.6000',no_price_dollars='0.4000')
        self.assertEqual(resting_reservation(dict(base,book_side='bid')),615)
        self.assertEqual(resting_reservation(dict(base,book_side='ask')),410)
        self.assertEqual(resting_reservation(dict(base,action='buy',side='no')),410)
        self.assertEqual(resting_reservation(dict(base,action='sell',side='no')),615)
        self.assertEqual(resting_reservation(dict(base,book_side='bid',subaccount_number=1)),0)
        self.assertEqual(resting_reservation(dict(remaining_count_fp='10.25')),1025)
    def test_split_donors_can_fund_one_entry_with_one_durable_transfer_at_a_time(self):
        store=Store()
        class Ex:
            def call(self,method,path,**kw):
                if method=='GET':return dict(subaccount_balances=[dict(subaccount_number=0,exchange_index=i,balance=b) for i,b in [(0,'6.00'),(2,'5.00'),(3,'0.00')]])
                self.body=kw['body'];return dict(transfer_id='one')
        exchange=Ex();funding=ShardFunding(store,exchange)
        self.assertFalse(funding.ensure(3,1000,1000,{}))
        self.assertEqual(exchange.body['amount'],60000)
        self.assertEqual(exchange.body['source_exchange_shard'],0)
    def test_insufficient_cash_message_has_amounts_and_is_throttled(self):
        store=Store();exchange=Exchange(store);funding=ShardFunding(store,exchange)
        with patch('services.demo.funding.time.time',return_value=100):
            funding.ensure(2,90,1000,{0:10000})
            message=store.alerts['funding-cash-2']
            self.assertIn('$0.90',message);self.assertIn('$100.00',message)
            funding.ensure(2,95,1000,{0:10000})
            self.assertEqual(store.alerts['funding-cash-2'],message)
        with patch('services.demo.funding.time.time',return_value=131):
            funding.ensure(2,90,1000,{})
        self.assertIn('funding',store.data)
