"""Cooperative service loop; caller must explicitly supply configured adapters.

Not started by the API or import, and no hosting configuration is modified.
"""
import time
from .queue import LeaseLost


def serve(campaigns,worker,stop,*,clock=time.monotonic,on_error=lambda code:None,on_tick=lambda:None):
    """stop is a threading.Event, also used for interruptible idle waits.

    The worker's fenced leases recover from interruption/crashes. Keep exception
    text out of public logs. Invalid evidence is explicit in campaign state;
    unexpected I/O is retried by lease recovery, never marked successful.
    """
    while not stop.is_set():
        try:
            on_tick()
            campaigns.schedule_due()
            if not worker.run_once(deadline=clock()+30):stop.wait(5)
        except LeaseLost:
            on_error('lease_lost');stop.wait(1)
        except Exception:
            on_error('collection_step_failed');stop.wait(5)
