"""Overlapping loads select complete close-time evidence once, with immutable inputs."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import json
import unittest
from services.research.cumulative import select_windows,prepare_category
from services.research.inventory import digest
from services.research.queue import EvidenceConflict
from test_reports import dataset


def window(identifier,start='2026-10-01T00:00:00+00:00',end='2026-10-02T00:00:00+00:00'):
    return dict(dataset_id=identifier,start_at=start,end_at=end)


class CumulativeTests(unittest.TestCase):
    def test_overlay_preserves_old_outside_partial_refresh_and_half_open_boundaries(self):
        rows=[window(1),window(2,'2026-10-01T12:00:00+00:00','2026-10-01T18:00:00+00:00')]
        selected=select_windows(rows)
        self.assertEqual([r['dataset_id'] for r in selected],[1,2,1])
        self.assertEqual(selected[0]['end_at'],selected[1]['start_at'])
        self.assertEqual(select_windows(list(reversed(rows))+rows),selected)
        self.assertEqual(select_windows(selected),selected)
        old=dataset(1,won=False);new=dataset(2,won=True)
        p=json.loads(prepare_category('btc',[old,new],selected,3).payload_json)
        self.assertEqual(p['historical']['candidate_count'],1)
        self.assertTrue(all(c['hold']['wins']==c['hold']['sampled_markets'] for c in p['historical']['cells']))
        self.assertFalse(p['latest_membership_known']);self.assertIsNone(p['latest']['candidate_count'])
        self.assertEqual([d['fingerprint'] for d in p['datasets']],[old['fingerprint'],new['fingerprint']])

    def test_newer_empty_window_removes_stale_candidates_inside_but_keeps_outside(self):
        old=dataset(1,won=False);new=dataset(2);new['payload']['candidates']=[];new['payload']['records']=[];new['fingerprint']=digest(new['payload'])
        original=deepcopy(old)
        manifest=select_windows([window(1),window(2,'2026-10-01T12:00:00+00:00','2026-10-01T18:00:00+00:00')])
        p=json.loads(prepare_category('btc',[old,new],manifest,2).payload_json)
        self.assertEqual(p['historical']['candidate_count'],0);self.assertEqual(p['historical']['cells'],[])
        self.assertEqual(old,original)
        outside=select_windows([window(1),window(2,'2026-10-01T13:00:00+00:00','2026-10-01T18:00:00+00:00')])
        p=json.loads(prepare_category('btc',[old,new],outside,3).payload_json)
        self.assertEqual(p['historical']['candidate_count'],1)

    def test_fully_replaced_inputs_are_not_required_and_identical_replay_is_immutable(self):
        selected=select_windows([window(1),window(2)])
        self.assertEqual(selected,[window(2)])
        a=prepare_category('btc',[dataset(2)],selected,2)
        b=prepare_category('btc',[dataset(2)],selected,2)
        self.assertEqual(a,b)
        with self.assertRaises(EvidenceConflict):prepare_category('btc',[],selected,2)
        with self.assertRaises(EvidenceConflict):prepare_category('btc',[dataset(1)],selected,2)
        with self.assertRaises(ValueError):prepare_category('btc',[dataset(2)],[window(2),window(1)],2)

    def test_disjoint_dates_retain_complete_cohort_and_gaps_are_not_filled(self):
        selected=select_windows([window(1),window(2,'2026-10-03T00:00:00+00:00','2026-10-04T00:00:00+00:00')])
        p=json.loads(prepare_category('btc',[dataset(1),dataset(2,day=3)],selected,2).payload_json)
        self.assertEqual(p['historical']['candidate_count'],2)
        self.assertEqual(len(p['selection']['windows']),2)
        for cell in p['historical']['cells']:
            self.assertEqual(cell['hold']['sampled_markets'],cell['loss_prevention']['sampled_markets'])

    def test_equal_id_overlapping_reuse_is_deterministic_and_invalid_ranges_fail(self):
        selected=select_windows([window(1),window(1,'2026-10-01T12:00:00+00:00','2026-10-03T00:00:00+00:00')])
        self.assertEqual(selected,[window(1,end='2026-10-03T00:00:00+00:00')])
        for row in [window(0),window(True),window(1,end='2026-10-01T00:00:00+00:00')]:
            with self.assertRaises(ValueError):select_windows([row])
