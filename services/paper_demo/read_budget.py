"""One conservative REST budget shared by production data clients in a worker."""
import threading
import time
from services.demo.exchange import ExchangeFailure

class ReadBudget:
    def __init__(self,interval=.2):
        self.interval=interval;self.next_read=0.;self.blocked_until=0.;self.lock=threading.Lock()
    def wait(self):
        with self.lock:
            now=time.monotonic()
            if now<self.blocked_until:raise ExchangeFailure('paper_data_rate_limited')
            if now<self.next_read:time.sleep(self.next_read-now)
            if time.monotonic()<self.blocked_until:raise ExchangeFailure('paper_data_rate_limited')
            self.next_read=time.monotonic()+self.interval
    def remaining(self):
        with self.lock:return max(0.,self.blocked_until-time.monotonic())
    def reject(self,seconds=30):
        with self.lock:self.blocked_until=max(self.blocked_until,time.monotonic()+seconds)

PRODUCTION_READS=ReadBudget(interval=1/3)  # Three REST reads/sec across discovery and fees.
