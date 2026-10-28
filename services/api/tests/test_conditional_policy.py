"""Current-main policy regression cases, pinned with model SOURCE.json."""
import unittest
from services.research.models.conditional_v2 import fit_threshold, policy_cells, replay


def item(i, bid, won, entry=95):
    close = 86400*i+1200
    return {'event': f'E{i}', 'key': (f'D{i}', f'T{i}', 10), 'bid': bid,
            'won': won, 'entry': entry, 'close_ts': close, 'decision_ts': close-300}


def examples():
    return [item(i, (55 if i%2 else 65) if i<=14 else (40 if i%2 else 65),
                 int(i%2==0 or i==19)) for i in range(1,21)]


class LossPolicyTests(unittest.TestCase):
    def test_threshold_fitted_only_on_earlier_events_and_gap_sale_uses_actual_bid(self):
        items=examples()
        h,l=policy_cells({('SERIES',10,'90-100',5):items}, {items[-2]['key']})
        p=h[0]
        self.assertEqual(p['threshold_cents'],60)
        self.assertEqual(p['training_events'],14)
        self.assertEqual(p['covered_observations'],6)
        self.assertEqual(p['early_exits'],3)
        self.assertEqual(p['missed_recoveries'],1)
        self.assertEqual(p['total_delta_cents'],14) # 38 + 38 - 62, never fill at 60
        self.assertEqual(l[0]['total_delta_cents'],-62)
        for x in items[14:]: x['won']=1
        changed,_=policy_cells({('SERIES',10,'90-100',5):items})
        self.assertEqual(changed[0]['threshold_cents'],60)
        self.assertEqual(changed[0]['total_delta_cents'],-186)

    def test_future_overlapping_events_cannot_borrow_training_outcomes(self):
        items=examples()
        items[14]['decision_ts']=items[13]['close_ts']-1
        h,_=policy_cells({('SERIES',10,'90-100',5):items})
        self.assertEqual(h[0]['covered_observations'],5)
        self.assertEqual(h[0]['total_delta_cents'],-24)

    def test_zero_bid_and_profit_taking_are_never_executed(self):
        p=replay([item(1,0,0),item(2,96,0),item(3,40,0)],99)
        self.assertEqual(p['early_exits'],1)
        self.assertEqual(p['total_delta_cents'],38)

    def test_correlated_series_do_not_double_count_event(self):
        items=examples()
        h,_=policy_cells({('A',10,'90-100',5):items,('B',10,'90-100',5):items})
        self.assertEqual(h[0]['covered_observations'],6)
        self.assertEqual(h[0]['early_exits'],3)

    def test_no_latest_membership_never_invents_latest_roi_adjustment(self):
        h,l=policy_cells({('SERIES',10,'90-100',5):examples()})
        self.assertEqual(l[0]['threshold_cents'],h[0]['threshold_cents'])
        self.assertEqual(l[0]['covered_observations'],0)
        self.assertEqual(l[0]['total_delta_cents'],0)
        self.assertFalse(l[0]['latest_membership_known'])

    def test_an_older_latest_collection_never_uses_future_historical_outcomes(self):
        items=examples()
        keys={x['key'] for x in items[:10]}
        _,latest=policy_cells({('SERIES',10,'90-100',5):items},keys)
        before=latest[0].copy()
        self.assertEqual(before['covered_observations'],3)
        self.assertLess(before['training_cutoff_ts'],items[9]['close_ts'])
        for x in items[10:]:x['won']=1-x['won']
        _,after=policy_cells({('SERIES',10,'90-100',5):items},keys)
        self.assertEqual(before,after[0])

    def test_fitted_crossing_no_unobserved_price_bridge_or_above_entry_threshold(self):
        self.assertEqual(fit_threshold([item(1,55,0),item(2,65,1)]),60)
        self.assertIsNone(fit_threshold([item(1,35,0),item(2,65,1)]))
        self.assertIsNone(fit_threshold([item(1,55,0,50),item(2,65,1,50)]))
        self.assertIsNone(fit_threshold([item(1,55,1),item(2,65,0)]))

if __name__=='__main__':unittest.main()
