import json,unittest
from unittest.mock import Mock,patch
import httpx
from services.demo.exchange import Exchange,ExchangeFailure
from services.demo.runtime import Worker
from services.api.tests.test_demo_cycles import worker,NOW

class ExchangeBudgets(unittest.TestCase):
    def exchange(self,handler):
        signer=Mock();signer.headers.return_value={}
        return Exchange(signer,client=httpx.Client(transport=httpx.MockTransport(handler)))
    def test_authenticated_budgets_charge_each_batch_item_and_preserve_headroom(self):
        seen=[];clock=[0.]
        def handler(request):
            seen.append(request)
            if request.url.path.endswith('/limits'):
                return httpx.Response(200,json=dict(usage_tier='basic',read=dict(refill_rate=200,bucket_capacity=600),write=dict(refill_rate=100,bucket_capacity=100)))
            return httpx.Response(200,json=dict(default_cost=10,endpoint_costs=[dict(method='DELETE',path='/trade-api/v2/portfolio/events/orders/{order_id}',cost=2)]))
        ex=self.exchange(handler)
        with patch('time.monotonic',side_effect=lambda:clock[0]),patch('time.sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
            self.assertTrue(ex.refresh_limits())
            self.assertEqual(ex.max_entry_batch,8)
            self.assertEqual(ex.entry_batch_capacity(),0)
            self.assertEqual(ex.request_cost('DELETE','/portfolio/events/orders/id'),2)
            clock[0]+=1
            self.assertEqual(ex.entry_batch_capacity(),8)
            ex.call('POST','/portfolio/events/orders/batched',body=dict(orders=[{}]*8))
            self.assertEqual(ex.entry_batch_capacity(),0)
            clock[0]+=.5
            self.assertEqual(ex.entry_batch_capacity(),4)
            self.assertEqual(ex.writes,1)
            ex.call('GET','/portfolio/balance');first=clock[0]
            ex.call('GET','/portfolio/balance')
            self.assertGreaterEqual(clock[0]-first,.999)
        ex.close()
    def test_unverified_budget_does_not_enable_fast_writes(self):
        ex=self.exchange(lambda request:httpx.Response(404,json={}))
        self.assertFalse(ex.refresh_limits())
        self.assertFalse(ex.buckets);self.assertEqual(ex.max_entry_batch,1)
        ex.close()
    def test_batch_transport_keeps_maker_flags_and_never_replays_a_lost_response(self):
        seen=[]
        def handler(request):seen.append(json.loads(request.content));raise httpx.ReadTimeout('lost')
        ex=self.exchange(handler);ex.max_entry_batch=8
        intents=[dict(kind='entry',side=side,ticker='t',client_id=side,price=3,quantity=2,close=NOW+100) for side in ('yes','no')]
        with self.assertRaises(ExchangeFailure) as caught:ex.submit_batch(intents)
        self.assertTrue(caught.exception.ambiguous);self.assertEqual(len(seen),1)
        self.assertTrue(all(o['post_only'] for o in seen[0]['orders']))
        self.assertEqual({o['price'] for o in seen[0]['orders']},{'0.0300','0.9700'})
        ex.close()

class EntryBatches(unittest.TestCase):
    def worker(self):
        w=worker();signer=Mock();signer.headers.return_value={}
        ex=Exchange(signer,client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(500))))
        ex.max_entry_batch=8;ex.entry_batch_capacity=Mock(return_value=8)
        w.exchange=ex;w.submit=Worker.submit.__get__(w,Worker)
        def submit(intents):
            # All durable order intents and claims must precede the network write.
            keys={row[0] for row in w.store.saved}
            self.assertTrue(all('order/'+i['client_id'] in keys for i in intents))
            self.assertTrue(all(w.states[i['bot']][f"{i['ticker']}/{i['square']}/{i['side']}"]['submitted'] for i in intents))
            ex.writes+=1
            return dict(orders=[dict(client_order_id=i['client_id'],order_id='remote-'+i['client_id'],fill_count='0.00',remaining_count=str(i['quantity'])) for i in reversed(intents)])
        ex.submit_batch=Mock(side_effect=submit)
        self.addCleanup(ex.close)
        return w
    def trade(self,w):
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
    def test_both_sides_share_one_write_with_durable_claims_and_id_based_confirmations(self):
        w=self.worker();self.trade(w)
        w.exchange.submit_batch.assert_called_once()
        intents=w.exchange.submit_batch.call_args.args[0]
        self.assertEqual({i['side'] for i in intents},{'yes','no'})
        self.assertTrue(all(i['status']=='resting' and i['exchange_id']=='remote-'+i['client_id'] for i in intents))
        self.assertFalse(w.recovered)
        self.assertEqual(w.shard_reservations,{})
    def test_planning_reserves_cash_and_market_and_bot_limits_for_the_entire_batch(self):
        w=self.worker();w.account['cash_cents']=150;self.trade(w)
        intents=w.exchange.submit_batch.call_args.args[0]
        self.assertLessEqual(sum(i['price']*i['quantity'] for i in intents),150)
        self.assertLessEqual(sum(i['price']*i['quantity'] for i in intents),300)
    def test_missing_confirmation_keeps_only_that_item_uncertain(self):
        w=self.worker()
        def partial(intents):
            i=intents[0]
            return dict(orders=[dict(client_order_id=i['client_id'],order_id='known',fill_count='0',remaining_count=str(i['quantity']))])
        w.exchange.submit_batch.side_effect=partial
        with self.assertRaises(ExchangeFailure):self.trade(w)
        intents=w.exchange.submit_batch.call_args.args[0]
        self.assertEqual([i['status'] for i in intents],['resting','uncertain'])
        self.assertIn('t',w.blocked)
        w.exchange.submit_batch.assert_called_once()
    def test_lost_batch_response_never_replays_either_order(self):
        w=self.worker();w.exchange.submit_batch.side_effect=ExchangeFailure('connection',True)
        with self.assertRaises(ExchangeFailure):self.trade(w)
        intents=w.exchange.submit_batch.call_args.args[0]
        self.assertTrue(all(i['status']=='uncertain' for i in intents))
        self.assertTrue(all(w.states[i['bot']][f"t/0/{i['side']}"]['submitted'] for i in intents))
        w.exchange.submit_batch.assert_called_once()
    def test_malformed_confirmation_cannot_claim_acceptance(self):
        w=self.worker()
        w.exchange.submit_batch.side_effect=lambda intents:dict(orders=[dict(client_order_id=i['client_id'],order_id='missing-counts') for i in intents])
        with self.assertRaises(ExchangeFailure):self.trade(w)
        self.assertTrue(all(i['status']=='uncertain' for i in w.exchange.submit_batch.call_args.args[0]))
    def test_duplicate_client_confirmation_is_uncertain(self):
        w=self.worker()
        def duplicate(intents):
            i=intents[0];row=dict(client_order_id=i['client_id'],order_id='id',fill_count=0,remaining_count=i['quantity'])
            return dict(orders=[row,row])
        w.exchange.submit_batch.side_effect=duplicate
        with self.assertRaises(ExchangeFailure):self.trade(w)
        self.assertTrue(all(i['status']=='uncertain' for i in w.exchange.submit_batch.call_args.args[0]))
    def test_quote_expiring_during_durable_preparation_aborts_without_wire_write(self):
        w=self.worker();original=w.store.put
        def put(key,*args,**kwargs):
            if key.startswith('order/'):w.quotes['t']['at']=NOW-10
            return original(key,*args,**kwargs)
        w.store.put=put;self.trade(w)
        w.exchange.submit_batch.assert_not_called()
        self.assertTrue(all(not m['submitted'] for m in w.states['bot-1'].values()))
        self.assertFalse(w.recovered)
    def test_whole_batch_429_rearms_only_after_known_rejection_with_new_attempt_ids(self):
        w=self.worker();w.exchange.submit_batch.side_effect=ExchangeFailure('rate_limited')
        with self.assertRaises(ExchangeFailure):self.trade(w)
        intents=w.exchange.submit_batch.call_args.args[0]
        self.assertTrue(all(i['status']=='rejected' for i in intents))
        for memory in w.states['bot-1'].values():
            self.assertFalse(memory['submitted']);self.assertEqual(memory['attempt'],1)
        self.assertFalse(w.recovered)
    def test_fill_during_funding_aborts_plan_without_claims_or_wire_orders(self):
        w=self.worker()
        def funding(*args):w.recovered=False;return True
        w.funding.ensure.side_effect=funding;self.trade(w)
        w.exchange.submit_batch.assert_not_called()
        self.assertTrue(all(not m['submitted'] for m in w.states['bot-1'].values()))
    def test_transfer_write_during_planning_invalidates_the_funding_snapshot(self):
        w=self.worker()
        def funding(*args):w.exchange.writes+=1;return True
        w.funding.ensure.side_effect=funding;self.trade(w)
        w.exchange.submit_batch.assert_not_called()
        self.assertEqual(w.shard_reservations,{})
