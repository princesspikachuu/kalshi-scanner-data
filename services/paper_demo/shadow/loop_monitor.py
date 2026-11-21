"""Bounded, read-only stall diagnostics; never inspect frame locals or secrets."""
import asyncio,gc,json,sys,threading,time
from pathlib import Path


def cpu_counters():
    try:
        return {k:int(v) for k,v in (line.split() for line in Path('/sys/fs/cgroup/cpu.stat').read_text().splitlines())
                if k in ('usage_usec','nr_periods','nr_throttled','throttled_usec')}
    except (OSError,ValueError):return {}

class LoopMonitor:
    def __init__(self,*,threshold=1.,interval=.1,report_interval=15.,emit=None,cpu_reader=cpu_counters):
        self.threshold,self.interval,self.report_interval=threshold,interval,report_interval
        self.emit=emit or (lambda value:print(json.dumps(value),flush=True))
        self.cpu_reader=cpu_reader;self.stopped=threading.Event();self.last_pulse=time.monotonic()
        self.thread_id=threading.get_ident();self.thread=None;self.last_report=-1e9
        self.gc_started=None;self.last_gc_ms=0.;self.total_gc_ms=0.;self.cpu_before=cpu_reader()
    def gc_event(self,phase,info):
        if phase=='start':self.gc_started=time.monotonic()
        elif self.gc_started is not None:
            self.last_gc_ms=(time.monotonic()-self.gc_started)*1000
            self.total_gc_ms+=self.last_gc_ms;self.gc_started=None
    def start(self):
        gc.callbacks.append(self.gc_event)
        self.thread=threading.Thread(target=self.watch,name='paper-loop-monitor',daemon=True);self.thread.start()
    async def heartbeat(self):
        while not self.stopped.is_set():
            self.last_pulse=time.monotonic()
            await asyncio.sleep(self.interval)
    def watch(self):
        while not self.stopped.wait(self.interval):
            now=time.monotonic();delay=now-self.last_pulse
            if delay<self.threshold or now-self.last_report<self.report_interval:continue
            self.last_report=now;frame=sys._current_frames().get(self.thread_id);frames=[]
            while frame is not None and len(frames)<8:
                frames.append(dict(file=Path(frame.f_code.co_filename).name,function=frame.f_code.co_name,line=frame.f_lineno));frame=frame.f_back
            del frame
            cpu=self.cpu_reader();delta={k:max(0,v-self.cpu_before.get(k,v)) for k,v in cpu.items()};self.cpu_before=cpu
            self.emit(dict(event='shadow_loop_stall',heartbeat_delay_seconds=delay,frames=frames,
                gc_active=self.gc_started is not None,last_gc_ms=self.last_gc_ms,total_gc_ms=self.total_gc_ms,
                cpu_counter_delta=delta,real_orders_enabled=False))
    def stop(self):
        self.stopped.set()
        if self.thread:self.thread.join(timeout=.5)
        if self.gc_event in gc.callbacks:gc.callbacks.remove(self.gc_event)
