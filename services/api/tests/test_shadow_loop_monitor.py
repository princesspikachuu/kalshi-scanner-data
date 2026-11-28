import asyncio,time,unittest
from services.paper_demo.shadow.loop_monitor import LoopMonitor

class LoopDiagnostics(unittest.IsolatedAsyncioTestCase):
    async def test_reports_blocking_call_stack_without_frame_locals(self):
        records=[];monitor=LoopMonitor(threshold=.015,interval=.005,report_interval=0,emit=records.append,cpu_reader=lambda:{'nr_throttled':2})
        monitor.start();pulse=asyncio.create_task(monitor.heartbeat())
        try:
            await asyncio.sleep(.01)
            def blocked_execution():
                secret_value='must never be recorded'
                time.sleep(.06)
            blocked_execution()
            self.assertTrue(any(any(f['function']=='blocked_execution' for f in r['frames']) for r in records))
            self.assertNotIn('must never be recorded',str(records))
            self.assertTrue(all(set(f)=={'file','function','line'} for r in records for f in r['frames']))
        finally:
            monitor.stop();pulse.cancel();await asyncio.gather(pulse,return_exceptions=True)
    async def test_waiting_async_tasks_do_not_count_as_blocked_loop(self):
        records=[];monitor=LoopMonitor(threshold=.04,interval=.005,report_interval=0,emit=records.append,cpu_reader=lambda:{})
        monitor.start();pulse=asyncio.create_task(monitor.heartbeat())
        try:
            await asyncio.sleep(.08);self.assertEqual(records,[])
        finally:
            monitor.stop();pulse.cancel();await asyncio.gather(pulse,return_exceptions=True)
