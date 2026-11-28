import unittest
from datetime import datetime, timezone

from tools.favorites_worker_alerts import evaluate, event_start


NOW = 1_795_820_000


def iso(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def snapshot(now=NOW):
    return dict(now=now, events=[], memory=[[now, .5]], logs=[])


class FavoritesWorkerAlertsTests(unittest.TestCase):
    def test_short_oom_detected_by_event_id_and_only_reported_once(self):
        state = {}
        row = dict(id='evt-oom', type='server_failed', timestamp=iso(NOW-5),
                   details={'reason': {'oomKilled': {'memoryLimit': '2Gi'}}})
        available = dict(id='evt-recovered', type='server_available', timestamp=iso(NOW-4))
        first = evaluate(state, dict(snapshot(), events=[row, available, row]))
        failure = next(alert for alert in first if alert['signal'] == 'render_worker_crash')
        self.assertEqual(failure['count'], 1)
        self.assertTrue(failure['events'][0]['oom'])
        second = evaluate(state, dict(snapshot(NOW+60), events=[row]))
        self.assertNotIn('render_worker_crash', {alert['signal'] for alert in second})

    def test_failed_source_leaves_watermark_and_extended_overlap(self):
        state = {}
        evaluate(state, snapshot())
        evaluate(state, dict(snapshot(NOW+4000), events=None))
        self.assertEqual(state['event_end'], NOW)
        self.assertEqual(event_start(state, NOW+4000), NOW-900)

    def test_memory_escalates_during_one_incident_and_gaps_do_not_resolve(self):
        state = {}
        moderate = [[NOW-i*60, .80] for i in range(15)]
        first = evaluate(state, dict(snapshot(), memory=moderate))
        self.assertEqual(next(a['tier'] for a in first if a['signal']=='render_memory_pressure'), 1)
        second = evaluate(state, dict(snapshot(NOW+60), memory=moderate+[[NOW+60, .96]]))
        self.assertEqual(next(a['tier'] for a in second if a['signal']=='render_memory_pressure'), 3)
        evaluate(state, dict(snapshot(NOW+500), memory=[]))
        self.assertEqual(state['signals']['render_memory_pressure']['tier'], 3)

    def test_stalled_discovery_freshness_settlement_and_low_activity_are_independent(self):
        logs = []
        for i in range(17):
            at = iso(NOW-i*60)
            logs.extend((
                dict(timestamp=at, event='paper_monitoring_capacity', admitting=False, reason='memory'),
                dict(timestamp=at, event='favorites_trading_diagnostics', folder='favorites',
                     running_bots=2, active_markets=3, fresh_active_books=0),
                dict(timestamp=at, event='favorites_quote_lifecycle', telemetry_started_at=NOW-4000,
                     window_seconds=300, submitted_orders=18, first_filled_events=0),
            ))
        logs.extend((
            dict(timestamp=iso(NOW), event='shadow_pipeline_cost'),
            dict(timestamp=iso(NOW), event='paper_position_settlement_poll_health',
                 held_by_folder={'favorites': 2}, oldest_favorites=[{'expired_seconds': 3600}]),
        ))
        signals = {row['signal'] for row in evaluate({}, dict(snapshot(), logs=logs))}
        self.assertEqual(signals, {'favorites_discovery_interrupted', 'favorites_books_stale',
                                  'favorites_settlement_backlog', 'favorites_low_activity'})
