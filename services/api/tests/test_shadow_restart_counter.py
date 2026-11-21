"""Rolling paper-worker restart counter and authenticated dashboard endpoint."""
import unittest
from unittest.mock import Mock

from services.demo.worker_restarts import KEY,MAX_EVENTS,record_worker_start,summarize
from services.api.tests import test_demo_postgres as fixture


class FakeStore:
    def __init__(self):
        self.rows={}
    def get(self,key):
        return {'progress':self.rows[key]} if key in self.rows else None
    def put(self,key,progress):
        self.rows[key]=progress


class RestartCounterTests(unittest.TestCase):
    def test_first_start_is_baseline_then_each_restart_is_counted(self):
        db=FakeStore()
        first=record_worker_start(db,now=100000)
        self.assertEqual(first['restarts_24h'],0)
        self.assertFalse(first['full_window'])
        self.assertTrue(first['tracked'])
        self.assertEqual(record_worker_start(db,100060)['restarts_24h'],1)
        self.assertEqual(record_worker_start(db,100120)['restarts_24h'],2)
        # At this instant the two earlier restarts and this new one are still in the window.
        self.assertEqual(record_worker_start(db,100000+86400+1)['restarts_24h'],3)
        self.assertTrue(summarize(db.get(KEY)['progress'],100000+86400+1)['full_window'])
        self.assertEqual(summarize(db.get(KEY)['progress'],100120+86400+1)['restarts_24h'],1)
        self.assertEqual(summarize(db.get(KEY)['progress'],100000+2*86400+2)['restarts_24h'],0)

    def test_unknown_is_not_misreported_as_zero_and_stale_events_age_out(self):
        self.assertIsNone(summarize(None,100000)['restarts_24h'])
        db=FakeStore()
        db.put(KEY,dict(tracking_since=100,last_started_at=2000,
                        recent_restarts=[100,101,86500,86501]))
        result=summarize(db.get(KEY)['progress'],86502)
        self.assertEqual(result['restarts_24h'],2)
        self.assertEqual(db.get(KEY)['progress']['recent_restarts'],[100,101,86500,86501])
        self.assertTrue(result['full_window'])

    def test_extreme_restarts_preserve_bounded_row_and_mark_lower_bound(self):
        db=FakeStore()
        db.put(KEY,dict(tracking_since=1000,last_started_at=1001,
                        recent_restarts=[1002+i*.01 for i in range(MAX_EVENTS)]))
        report=record_worker_start(db,now=1050)
        self.assertEqual(len(db.rows[KEY]['recent_restarts']),MAX_EVENTS)
        self.assertEqual(report['restarts_24h'],MAX_EVENTS)
        self.assertTrue(report['lower_bound'])
        self.assertFalse(report['full_window'])
        self.assertFalse(summarize(db.rows[KEY],now=87500)['lower_bound'])

    def test_invalid_record_fails_to_unknown_not_zero(self):
        self.assertIsNone(summarize(dict(tracking_since='invalid',recent_restarts=[1]),1000)['restarts_24h'])


@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL is required')
class RestartEndpointTests(fixture.DemoPostgres):
    def test_endpoint_is_authenticated_and_does_not_scan_history(self):
        first=self.client.get('/demo/shadow/restarts')
        self.assertEqual(first.status_code,200)
        self.assertFalse(first.json()['tracked'])
        self.assertIsNone(first.json()['restarts_24h'])
        record_worker_start(self.demo,now=100000)
        record_worker_start(self.demo,now=100500)
        with self.demo.pool.connection() as c:
            keys=c.execute("SELECT idempotency_key FROM research_job WHERE idempotency_key LIKE 'demo/shadow/worker-%'").fetchall()
        self.assertEqual(len(keys),1)
        # Use an old timestamp to verify that the API uses current wall time.
        self.assertEqual(self.client.get('/demo/shadow/restarts').json()['restarts_24h'],0)
        self.assertEqual(self.client.get('/demo/shadow/restarts?extra=1').status_code,422)
        self.assertEqual(self.client.get('/demo/shadow/restarts',
                         headers={'x-pocket-proxy':'wrong'}).status_code,403)


if __name__=='__main__':
    unittest.main()
