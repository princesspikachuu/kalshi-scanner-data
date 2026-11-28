"""A single worker process dispatches one trading environment at a time."""
import os,time,json,traceback
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
from .mode import read_mode

def run(stop):
    while not stop.is_set():
        try:
            with ConnectionPool(os.environ['DATABASE_URL'],min_size=1,max_size=1,kwargs=dict(row_factory=dict_row,connect_timeout=5)) as pool:
                mode=read_mode(pool).get('mode')
            if mode in ('demo','draining_demo'):
                from services.demo.runtime import run as execute
            elif mode=='live':
                from services.live.runtime import run as execute
            else:
                print(json.dumps(dict(event='trading_mode_invalid',execution_enabled=False)),flush=True)
                stop.wait(5);continue
            execute(stop)
        except Exception as error:
            # Never print provider bodies, decrypted keys, or connection strings.
            print(json.dumps(dict(event='trading_router_recovery',error_type=type(error).__name__,code=getattr(error,'code',None),status=getattr(error,'status',None),frames=[dict(function=f.name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)[-4:]])),flush=True)
            stop.wait(5)
