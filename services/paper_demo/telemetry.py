"""Bounded operational counters. Never retain URLs, query values or credentials."""
import contextvars,functools,re,resource,threading,time
from pathlib import Path

SCOPE=contextvars.ContextVar('paper_request_scope',default='shared')
SENT=contextvars.ContextVar('paper_request_sent',default=False)

def request_sent():SENT.set(True)

def endpoint(path):
    if not isinstance(path,str):return 'other'
    if path in ('/series','/markets','/events','/markets/trades','/series/fee_changes',
                '/events/fee_changes','/incentive_programs','/milestones','/exchange/status',
                '/api_keys','/account/limits'):return path
    if re.fullmatch(r'/markets/[^/]+/orderbook',path):return '/markets/:ticker/orderbook'
    if re.fullmatch(r'/markets/[^/]+',path):return '/markets/:ticker'
    if re.fullmatch(r'/series/[^/]+',path):return '/series/:series'
    if path.startswith('/live_data/milestone/'):return '/live_data/milestone/:id'
    return 'other'

class RequestMetrics:
    def __init__(self):self.lock=threading.Lock();self.cells={};self.started=time.monotonic()
    def record(self,path,scope,status,seconds,sent):
        code=str(status)
        if code not in ('blocked','error') and not re.fullmatch('[1-5][0-9][0-9]',code):code='other'
        key=(endpoint(path),scope if scope in ('shared','discovery','fees','complete_set','weather','sports','hourly','market_maker','settlement') else 'other',code)
        with self.lock:
            # Fixed endpoint/scope/status cardinality; malformed errors cannot
            # grow the registry or expose a market identifier.
            if key not in self.cells and len(self.cells)>=128:key=('other','other','other')
            cell=self.cells.setdefault(key,dict(calls=0,requests=0,elapsed_ms=0.,max_ms=0.))
            cell['calls']+=1;cell['requests']+=int(sent);cell['elapsed_ms']+=seconds*1000
            cell['max_ms']=max(cell['max_ms'],seconds*1000)
    def drain(self):
        with self.lock:
            now=time.monotonic();seconds=now-self.started;cells=self.cells;self.cells={};self.started=now
        return dict(window_seconds=seconds,endpoints=[dict(endpoint=p,scope=s,status=code,**v) for (p,s,code),v in cells.items()])

REQUESTS=RequestMetrics()

def measure_request(fn):
    @functools.wraps(fn)
    def wrapped(self,*args,**kwargs):
        index=1 if fn.__name__=='call' else 0
        path=args[index] if len(args)>index else kwargs.get('path','other')
        started=time.monotonic();token=SENT.set(False);status='200'
        try:return fn(self,*args,**kwargs)
        except Exception as exc:
            status=getattr(exc,'status',None) or ('blocked' if not SENT.get() else 'error')
            raise
        finally:
            REQUESTS.record(path,SCOPE.get(),status,time.monotonic()-started,SENT.get())
            SENT.reset(token)
    return wrapped

async def scoped(name,coroutine):
    token=SCOPE.set(name)
    try:return await coroutine
    finally:SCOPE.reset(token)

class ProcessMetrics:
    def __init__(self):self.wall=time.monotonic();self.cpu=time.process_time()
    def sample(self):
        now=time.monotonic();cpu=time.process_time();elapsed=now-self.wall
        value=dict(window_seconds=elapsed,cpu_seconds=cpu-self.cpu,cpu_cores=(cpu-self.cpu)/elapsed if elapsed else None,
            peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
        try:
            import os
            value['rss_bytes']=int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
        except (OSError,ValueError,IndexError):value['rss_bytes']=None
        self.wall,self.cpu=now,cpu
        return value
