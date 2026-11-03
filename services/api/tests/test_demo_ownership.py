import unittest
from services.demo.ownership import describe,needs_recovery
from services.api.tests.test_demo_engine import NOW

class OwnershipDetails(unittest.TestCase):
    def test_ended_market_without_live_orders_is_informational_but_keeps_discrepancy(self):
        q={'t':dict(status='closed',close=NOW-900,result='')}
        result=describe({'t'},{'t':2},{},q,[],[],NOW)
        self.assertTrue(result['t']['informational']);self.assertEqual(result['t']['reason'],'awaiting_settlement')
        self.assertEqual((result['t']['expected_contracts'],result['t']['exchange_contracts']),(2,0))
    def test_open_or_uncertain_orders_remain_actionable_even_when_market_ended(self):
        q={'t':dict(status='closed',close=NOW-900)}
        for order in [dict(ticker='t',remaining=1,status='resting'),dict(ticker='t',remaining=0,status='uncertain'),dict(ticker='t',remaining=0,status='cancel_pending')]:
            self.assertFalse(describe({'t'},{'t':2},{},q,[order],[],NOW)['t']['informational'])
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
        for bad in [dict(local[0],filled=1),dict(local[0],remaining=1),
                    dict(local[0],status='resting'),dict(local[0],status='cancel_pending')]:
            self.assertEqual(proof('T',[bad],q,0,0,[],[],[],NOW),[])
