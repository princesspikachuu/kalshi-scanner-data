import json
import unittest
from services.research.telemetry import Meter,configure,timed,count

class TelemetryTests(unittest.TestCase):
    def tearDown(self):configure()
    def test_aggregates_bounded_numeric_fields_without_exception_or_argument_content(self):
        now=[0];emitted=[];meter=configure(emitted.append,clock=lambda:now[0],interval=30)
        @timed('provider.http')
        def call(secret):
            now[0]+=2
            raise RuntimeError(secret)
        with self.assertRaises(RuntimeError):call('private-sentinel')
        count('dataset.raw_bytes',1000);now[0]=31;meter.flush()
        self.assertEqual(emitted[0]['stages']['provider.http'],dict(count=1,errors=1,total_ms=2000,max_ms=2000))
        self.assertEqual(emitted[0]['counters']['dataset.raw_bytes'],1000)
        self.assertNotIn('private-sentinel',json.dumps(emitted));meter.flush(force=True);self.assertEqual(len(emitted),1)
        for i in range(100):meter.observe('bad/'+str(i),1)
        self.assertEqual(meter.stages,{})
    def test_disabled_and_broken_sink_cannot_change_collection_outcome(self):
        @timed('dataset.publish')
        def saved():return 123
        self.assertEqual(saved(),123)
        meter=configure(lambda _:(_ for _ in ()).throw(ValueError('private')),interval=0)
        self.assertEqual(saved(),123);meter.flush(force=True)
