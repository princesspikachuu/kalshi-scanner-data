"""REST pacing cannot block the trading loop's cooldown reads or 429 updates."""
import threading,time,unittest
from unittest.mock import patch
from services.paper_demo.read_budget import ReadBudget
from services.demo.exchange import ExchangeFailure

class NonblockingReadBudget(unittest.TestCase):
    def test_sleeping_rest_waiter_does_not_hold_cooldown_lock(self):
        budget=ReadBudget(interval=.1);budget.next_read=time.monotonic()+1
        sleeping=threading.Event();release=threading.Event();updated=threading.Event();errors=[];remaining=[]
        def sleep(_):sleeping.set();release.wait(2)
        def wait():
            try:budget.wait()
            except ExchangeFailure as exc:errors.append(exc.code)
        def cooldown():
            budget.reject(30);remaining.append(budget.remaining());updated.set()
        with patch('services.paper_demo.read_budget.time.sleep',side_effect=sleep):
            waiter=threading.Thread(target=wait);reader=threading.Thread(target=cooldown)
            waiter.start()
            try:
                self.assertTrue(sleeping.wait(1));reader.start()
                self.assertTrue(updated.wait(1),'Cooldown read/update blocked behind a sleeping REST waiter')
                self.assertGreater(remaining[0],29)
            finally:
                release.set();waiter.join(2)
                if reader.ident is not None:reader.join(2)
        self.assertEqual(errors,['paper_data_rate_limited'])
        self.assertFalse(waiter.is_alive());self.assertFalse(reader.is_alive())
    def test_concurrent_callers_still_observe_the_shared_pacing(self):
        budget=ReadBudget(interval=.01);admissions=[]
        def read():budget.wait();admissions.append(time.monotonic())
        threads=[threading.Thread(target=read) for _ in range(5)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(2)
        self.assertEqual(len(admissions),5)
        times=sorted(admissions)
        # Pacing is checked using monotonic time inside the same shared lock.
        self.assertTrue(all(b-a>=.009 for a,b in zip(times,times[1:])))
