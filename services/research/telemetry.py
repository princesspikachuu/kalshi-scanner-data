"""Bounded process-local timing aggregates; never record request contents or errors."""
from contextlib import contextmanager
from functools import wraps
import math
import re
from threading import Lock
import time

_meter=None

class Meter:
    def __init__(self,sink,*,interval=30,clock=time.monotonic):
        self.sink,self.interval,self.clock=sink,interval,clock
        self.started=clock();self.lock=Lock();self.stages={};self.counters={}

    def observe(self,stage,seconds,failed=False):
        if not re.fullmatch(r'[a-z][a-z_.]{0,63}',stage) or not math.isfinite(seconds):return
        with self.lock:
            if stage not in self.stages and len(self.stages)>=64:return
            row=self.stages.setdefault(stage,dict(count=0,errors=0,total_ms=0,max_ms=0))
            milliseconds=max(0,seconds*1000)
            row['count']+=1;row['errors']+=int(failed)
            row['total_ms']+=milliseconds;row['max_ms']=max(row['max_ms'],milliseconds)
        self.flush()

    def count(self,name,value):
        if not re.fullmatch(r'[a-z][a-z_.]{0,63}',name) or type(value) not in (int,float) or not math.isfinite(value) or value<0:return
        with self.lock:
            if name not in self.counters and len(self.counters)>=64:return
            self.counters[name]=self.counters.get(name,0)+value

    def flush(self,*,force=False):
        with self.lock:
            now=self.clock()
            if (not force and now-self.started<self.interval) or not (self.stages or self.counters):return
            payload=dict(event='collection_timings_v1',window_seconds=round(now-self.started,3),
                stages={k:{field:round(value,3) for field,value in row.items()} for k,row in self.stages.items()},counters=self.counters)
            self.stages={};self.counters={};self.started=now
        try:self.sink(payload)
        except Exception:pass  # Observability can never fail a collection checkpoint.


def configure(sink=None,**kwargs):
    global _meter
    _meter=Meter(sink,**kwargs) if sink is not None else None
    return _meter


@contextmanager
def timing(stage):
    meter=_meter
    if meter is None:yield;return
    start=meter.clock();failed=True
    try:
        yield
        failed=False
    finally:meter.observe(stage,meter.clock()-start,failed)


def timed(stage):
    def decorate(function):
        @wraps(function)
        def wrapped(*args,**kwargs):
            with timing(stage):return function(*args,**kwargs)
        return wrapped
    return decorate


def count(name,value):
    if _meter is not None:_meter.count(name,value)
