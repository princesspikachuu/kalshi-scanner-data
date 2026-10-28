"""Cooperative service loop; caller must explicitly supply configured adapters.

Not started by the API or import, and no hosting configuration is modified.
"""
import time
import json
from .queue import LeaseLost


def serve(campaigns,worker,stop,*,clock=time.monotonic,on_error=lambda code:None,on_tick=lambda:None,idle_wait=lambda:5):
    """stop is a threading.Event, also used for interruptible idle waits.

    The worker's fenced leases recover from interruption/crashes. Keep exception
    text out of public logs. Invalid evidence is explicit in campaign state;
    unexpected I/O is retried by lease recovery, never marked successful.
    """
    while not stop.is_set():
        try:
            on_tick()
            campaigns.schedule_due()
            if not worker.run_once(deadline=clock()+30):stop.wait(max(.1,min(5,idle_wait())))
        except LeaseLost:
            on_error('lease_lost');stop.wait(1)
        except Exception as error:
            # Code locations and allowlisted exception types identify the failing
            # path without printing exception messages, SQL, URLs or credentials.
            names={'ValueError','TypeError','KeyError','IndexError','MemoryError',
                   'OperationalError','PoolTimeout','ArchiveInvalid','DatasetLimit',
                   'EvidenceConflict','CoverageIncomplete','InvalidOperation'}
            frames=[];trace=error.__traceback__
            while trace is not None:
                module=trace.tb_frame.f_globals.get('__name__','')
                if module.startswith('services.research.'):
                    frames.append(dict(module=module,line=trace.tb_lineno))
                trace=trace.tb_next
            on_error(json.dumps(dict(event='collection_step_failed',
                error_type=type(error).__name__ if type(error).__name__ in names else 'unexpected',
                frames=frames[-6:]),sort_keys=True))
            stop.wait(5)
