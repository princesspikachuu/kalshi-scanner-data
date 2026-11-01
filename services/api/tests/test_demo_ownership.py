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
