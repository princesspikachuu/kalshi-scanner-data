"""Operational counters are bounded, scope-aware and contain no request secrets."""
import asyncio,json,unittest
from unittest.mock import patch
from services.paper_demo import telemetry as t

class RequestTelemetry(unittest.IsolatedAsyncioTestCase):
    async def test_threaded_requests_keep_scope_and_distinguish_blocked_attempts(self):
        metrics=t.RequestMetrics()
        class Client:
            @t.measure_request
            def call(self,method,path,params=None):
                if params and params.get('blocked'):raise ValueError('secret-provider-body')
                t.request_sent();return {'private':'never recorded'}
        async def work():
            c=Client();await asyncio.to_thread(c.call,'GET','/markets/SECRET-TICKER',{'token':'secret'})
            with self.assertRaises(ValueError):await asyncio.to_thread(c.call,method='GET',path='/markets/SECRET-TICKER',params={'blocked':True})
        with patch.object(t,'REQUESTS',metrics):await t.scoped('market_maker',work())
        result=metrics.drain();rows=result['endpoints']
        self.assertEqual(sum(r['requests'] for r in rows),1);self.assertEqual(sum(r['calls'] for r in rows),2)
        self.assertEqual({r['scope'] for r in rows},{'market_maker'})
        self.assertEqual({r['status'] for r in rows},{'200','blocked'})
        self.assertNotIn('SECRET',json.dumps(result));self.assertNotIn('secret',json.dumps(result))
        self.assertEqual(metrics.drain()['endpoints'],[])

    async def test_cardinality_remains_bounded_for_untrusted_paths_and_statuses(self):
        m=t.RequestMetrics()
        for i in range(1000):m.record('/unknown/'+str(i),'scope-'+str(i),i,.01,True)
        result=m.drain()
        self.assertLessEqual(len(result['endpoints']),129)
        self.assertEqual(sum(r['requests'] for r in result['endpoints']),1000)
        self.assertEqual({r['endpoint'] for r in result['endpoints']},{'other'})
