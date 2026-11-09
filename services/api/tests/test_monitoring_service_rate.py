"""Queue estimates use completed burst work without hiding lag or hard limits."""
import unittest
from services.paper_demo.shadow.monitoring import MonitoringBudget

class CommittedServiceRate(unittest.TestCase):
    def mixed(self):
        b=MonitoringBudget()
        for i in range(10):b.observe(100+i/100,0,.01,90,input_count=1)
        b.observe(101,600,.01,.3,input_count=512)
        return b
    def test_tiny_checkpoint_batches_do_not_exaggerate_burst_queue_cost(self):
        b=self.mixed();s=b.limits(101)
        self.assertEqual(s['processing_p95_ms'],90)
        self.assertAlmostEqual(s['estimated_queue_seconds'],.18)
        self.assertTrue(s['admitting']);self.assertEqual(s['total'],32)
        self.assertEqual(s['service_sample_inputs'],512)
    def test_includes_database_commit_time_in_observed_per_input_cost(self):
        b=MonitoringBudget();b.observe(100,600,.01,(100+150)/500,input_count=500)
        self.assertAlmostEqual(b.limits(100)['estimated_queue_seconds'],.3)
    def test_recent_slowdown_overrides_faster_old_throughput(self):
        b=MonitoringBudget();b.observe(100,0,.01,.1,input_count=512)
        b.observe(106,600,.01,2,input_count=512)
        self.assertAlmostEqual(b.limits(106)['estimated_queue_seconds'],1.2)
        self.assertFalse(b.limits(106)['admitting'])
    def test_old_slowdown_remains_conservative_during_recovery(self):
        b=MonitoringBudget();b.observe(100,0,.01,2,input_count=512)
        b.observe(106,600,.01,.1,input_count=512)
        self.assertAlmostEqual(b.limits(106)['estimated_queue_seconds'],.63)
        self.assertFalse(b.limits(106)['admitting'])
    def test_missing_or_insufficient_fresh_burst_evidence_uses_original_fallback(self):
        for count in (None,1,32,64):
            b=MonitoringBudget();b.observe(100,600,.01,2,input_count=count)
            self.assertEqual(b.limits(100)['queue_cost_basis'],'p95 per-input fallback')
            self.assertFalse(b.limits(100)['admitting'])
        b=self.mixed();b.observe(107,600,.01,.1,input_count=1)
        self.assertEqual(b.limits(107)['queue_cost_basis'],'p95 per-input fallback')
        self.assertFalse(b.limits(107)['admitting']);self.assertFalse(b.limits(118)['admitting'])
    def test_hard_backlog_lag_processing_and_provider_guards_still_apply(self):
        for backlog,lag,cost,cooldown in ((2001,.01,.01,0),(0,3,.01,0),(0,.01,101,0),(0,.01,.01,1)):
            b=MonitoringBudget();b.observe(100,backlog,lag,cost,cooldown,input_count=512)
            self.assertFalse(b.limits(100)['admitting'])
    def test_service_history_is_bounded(self):
        b=MonitoringBudget()
        for i in range(700):b.observe(100+i/1000,0,.01,.2,input_count=512)
        self.assertEqual(len(b.service_samples),600)
