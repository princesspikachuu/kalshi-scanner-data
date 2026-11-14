"""Regression checks for bounded, lossless shadow archive selection.

These checks do not open a database or call R2.
"""
import unittest

from services.demo import shadow_archive_recovery as recovery


class ShadowArchiveCandidateQueryTests(unittest.TestCase):
    def test_candidate_sql_uses_indexable_order_and_allowlist(self):
        sql = recovery.CANDIDATES
        self.assertIn("ORDER BY created_at, id LIMIT %s", sql)
        self.assertNotIn("ORDER BY idempotency_key", sql)
        self.assertIn("created_at<to_timestamp(%s)", sql)
        self.assertIn("AND NOT (progress ? 'archive')", sql)
        self.assertIn("status='succeeded'", sql)
        self.assertIn("idempotency_key LIKE %s", sql)
        self.assertIn("progress->>'event'=ANY(%s::text[])", sql)
        self.assertEqual(sql.count("%s"), 6)
        for event in recovery.SAFE_EVENT_KINDS:
            self.assertIn("'" + event + "'", sql)

    def test_event_predicate_matches_allowlist_exactly(self):
        sql = recovery.CANDIDATES
        predicate = sql.split("AND progress->>'event' IN (", 1)[1].split(")", 1)[0]
        import re
        names = re.findall(r"'([A-Z_]+)'", predicate)
        self.assertEqual(set(names), set(recovery.SAFE_EVENT_KINDS))
        self.assertEqual(len(names), len(set(names)))

    def test_recovery_safety_fences_remain(self):
        self.assertIn("FOR UPDATE SKIP LOCKED", recovery.LOCKED_CANDIDATES)
        self.assertIn("mt_reclaim_shadow_diagnostics", recovery.SCOPED_RECLAIM_SQL)
        self.assertGreaterEqual(recovery.MIN_AGE_HOURS, 6)
        self.assertLessEqual(recovery.MAX_BATCH, 150)


if __name__ == "__main__":
    unittest.main()
