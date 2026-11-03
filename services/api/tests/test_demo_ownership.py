import unittest
from services.demo.ownership import describe,needs_recovery
from services.api.tests.test_demo_engine import NOW

class OwnershipDetails(unittest.TestCase):
    def test_ended_market_without_live_orders_is_informational_but_keeps_discrepancy(self):
        q={'t':dict(status='closed',close=NOW-900,result='')}
        result=describe({'t'},{'t':2},{},q,[],[],NOW)
        self.assertTrue(result['t']['informational']);self.assertEqual(result['t']['reason'],'awaiting_settlement')
        self.assertEqual((result['t']['expected_contracts'],result['t']['exchange_contracts']),(2,0))
    def test_ended_markets_are_informational_unless_exchange_still_has_resting_orders(self):
        q={'t':dict(status='closed',close=NOW-900)}
        for order in [dict(ticker='t',remaining=1,status='resting'),dict(ticker='t',remaining=0,status='uncertain'),dict(ticker='t',remaining=0,status='cancel_pending')]:
            self.assertTrue(describe({'t'},{'t':2},{},q,[order],[],NOW)['t']['informational'])
        self.assertFalse(describe({'t'},{'t':2},{},q,[],[dict(ticker='t')],NOW)['t']['informational'])
        self.assertFalse(describe({'t'},{'t':2},{},{'t':dict(status='active',close=NOW+60)},[],[],NOW)['t']['informational'])
    def test_missing_expired_market_is_retained_without_inventing_a_settlement(self):
        value=describe({'t'},{'t':2},{},{},[],[],NOW,{'t':dict(market_end=NOW-900)})['t']
        self.assertTrue(value['informational']);self.assertEqual(value['reason'],'market_unavailable')
        self.assertNotIn('payout',value)
    def test_late_fills_require_matching_saved_order_and_do_not_rewrite_realized_history(self):
        p=dict(kind='entry',ticker='t',quantity=10);s=dict(status='closed',filled=0,exchange_id='id')
        raw=dict(ticker='t',order_id='id',status='canceled',fill_count_fp='2.00',remaining_count_fp='0.00')
        self.assertTrue(needs_recovery(p,s,raw))
        for state in [dict(s,realized_cents=0),dict(s,reset_closed=True),dict(s,filled=2)]:self.assertFalse(needs_recovery(p,state,raw))
        self.assertFalse(needs_recovery(p,s,dict(raw,ticker='other')))
        self.assertFalse(needs_recovery(p,s,dict(raw,fill_count_fp='11.00')))


class EmptyFinalizedIntentProof(unittest.TestCase):
    def test_finalized_zero_exposure_unfilled_intents(self):
        from services.demo.ownership import verified_empty_finalized_intents as proof
        local=[dict(ticker='T',client_id='local-1',status='uncertain',filled=0,remaining=0),
               dict(ticker='T',client_id='local-2',status='intent',filled=0,remaining=0)]
        q=dict(status='finalized',close=NOW-3600)
        self.assertEqual(proof('T',local,q,0,0,[],[],[],NOW),['local-1','local-2'])
        self.assertEqual(proof('T',[dict(local[0],status='cancel_pending',remaining=2)],dict(q,status='closed'),0,0,[],[],[],NOW),['local-1'])
        self.assertEqual(proof('T',local,q,0,0,[],[],[dict(ticker='T',order_id='unexplained')],NOW),[])
        history=[dict(ticker='T',order_id='manual-1')]
        self.assertEqual(proof('T',local,q,0,0,[],history,[dict(ticker='T',order_id='manual-1')],NOW),[])
        self.assertEqual(proof('T',local,q,0,0,[dict(ticker='T',order_id='manual-1')],[],[],NOW),[])
        self.assertEqual(proof('T',local,q,0,0,[],[dict(ticker='T',client_order_id='local-1')],[],NOW),[])

    def test_never_clear_pending_or_filled_exposure(self):
        from services.demo.ownership import verified_empty_finalized_intents as proof
        local=[dict(ticker='T',client_id='local-1',status='uncertain',filled=0,remaining=0)]
        q=dict(status='finalized',close=NOW-3600)
        for invalid in [dict(q,status='active'),dict(q,close=NOW+20),dict(q,close=NOW-30)]:
            self.assertEqual(proof('T',local,invalid,0,0,[],[],[],NOW),[])
        self.assertEqual(proof('T',local,q,1,0,[],[],[],NOW),[])
        self.assertEqual(proof('T',local,q,0,1,[],[],[],NOW),[])
        for bad in [dict(local[0],filled=1),dict(local[0],status='held')]:
            self.assertEqual(proof('T',[bad],q,0,0,[],[],[],NOW),[])


class SharedMarketLedger(unittest.TestCase):
    def test_two_bots_net_into_one_exchange_position_with_attributed_lots(self):
        from services.demo.ownership import market_ledger
        local=[
            dict(ticker='T',client_id='buy-a',exchange_id='exchange-a',bot='a',kind='entry',
                 side='yes',status='held',filled=5,sold=2,remaining=0,price=60),
            dict(ticker='T',client_id='buy-b',exchange_id='exchange-b',bot='b',kind='entry',
                 side='no',status='held',filled=4,sold=1,remaining=0,price=35),
            dict(ticker='T',client_id='sell-a',bot='a',kind='exit',parent='buy-a',
                 side='yes',status='resting',filled=0,remaining=3,price=65)]
        value=market_ledger(local,{'T':0},{'T':0},
            [dict(ticker='T',client_order_id='sell-a',order_id='remote-sell')],{'T'},
            {'a':'A Bot','b':'B Bot'})['T']
        self.assertTrue(value['shared_by_bots'])
        self.assertEqual((value['expected_contracts'],value['exchange_contracts'],value['difference_contracts']),(0,0,0))
        self.assertEqual({b['name']:b['net_contracts'] for b in value['bots']},{'A Bot':3,'B Bot':-3})
        self.assertEqual(value['unowned_order_count'],0)
        self.assertEqual(value['order_count'],3)
        self.assertEqual(next(o for o in value['orders'] if o['client_id']=='sell-a')['parent'],'buy-a')

    def test_unowned_exchange_orders_never_assigned_to_a_bot(self):
        from services.demo.ownership import market_ledger
        entry=dict(ticker='T',client_id='known',bot='a',kind='entry',side='yes',
                   status='held',filled=1,sold=0,remaining=0)
        value=market_ledger([entry],{'T':1},{'T':3},
            [dict(ticker='T',client_order_id='manual',order_id='manual-1',status='resting')],{'T'})['T']
        self.assertEqual(value['difference_contracts'],2)
        self.assertEqual(value['unowned_order_count'],1)
        self.assertEqual(value['unowned_orders'][0]['exchange_id'],'manual-1')
        self.assertEqual(value['bots'][0]['net_contracts'],1)

    def test_only_short_fully_owned_order_snapshot_races_are_routine(self):
        from services.demo.ownership import market_ledger,transient_sync
        entry=dict(ticker='T',client_id='one',bot='b',kind='entry',side='yes',
                   status='held',filled=1,sold=0,remaining=0)
        value=market_ledger([entry],{'T':1},{'T':0},[],{'T'})['T']
        self.assertTrue(transient_sync(value,NOW,NOW-1,NOW-3,NOW-30))
        self.assertFalse(transient_sync(value,NOW,NOW-1,NOW-8,NOW-30))
        self.assertFalse(transient_sync(value,NOW,NOW-13,NOW-3,NOW-30))
        self.assertFalse(transient_sync(value,NOW,NOW-1,NOW-3,0))
        self.assertFalse(transient_sync(dict(value,unconfirmed_order_count=1),NOW,NOW-1,NOW-3,NOW-30))
        self.assertFalse(transient_sync(dict(value,unowned_order_count=1),NOW,NOW-1,NOW-3,NOW-30))
        self.assertFalse(transient_sync(dict(value,difference_contracts=0),NOW,NOW-1,NOW-3,NOW-30))

    def test_protective_price_crossing_is_latched_during_ownership_verification(self):
        import threading
        from services.demo.runtime import Worker
        from services.api.tests.test_demo_engine import FakeStore,bot,quote
        b=bot(loss_mode='manual',loss_cents=66)
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None)
        worker.bots=[b];worker.quotes={'T':quote()};worker.blocked={'T'}
        order=dict(client_id='one',kind='entry',bot=b['id'],revision=1,ticker='T',side='yes',
                   square=0,filled=1,sold=0,remaining=0,price=60,status='held')
        worker.orders=[order]
        self.assertTrue(worker.observe_exit_triggers('T',NOW))
        self.assertTrue(order['exit_triggered'])
        self.assertIn('exit_trigger',worker.store.events)
