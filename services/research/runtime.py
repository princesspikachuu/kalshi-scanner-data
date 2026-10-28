"""Explicit deployment entry point. Import and --check-config perform no I/O."""
from contextlib import ExitStack,contextmanager
from dataclasses import dataclass,field
import math
import json
import os
import re
import signal
import sys
from threading import Event

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from .archive import ArchiveStore
from .budget import ReadBudget
from .campaigns import CampaignStore,CampaignWorker
from .evidence import EvidenceWorker,KalshiEvidence
from .inventory import InventoryWorker
from .kalshi import KalshiInventory
from .queue import ResearchQueue
from .r2 import R2Objects
from .runner import serve


class ConfigurationError(ValueError):pass


@dataclass(frozen=True)
class WorkerSettings:
    database_url:str=field(repr=False)
    account_id:str=field(repr=False)
    bucket:str=field(repr=False)
    access_key_id:str=field(repr=False)
    secret_access_key:str=field(repr=False)
    read_rate:float
    read_capacity:int
    endpoint_cost:int
    enabled:bool=False
    acceptance:str='off'
    operator_action:str='off'
    runtime_verifiers:dict=field(default_factory=dict,repr=False)

    @classmethod
    def from_env(cls,env=None):
        env=os.environ if env is None else env
        def required(name):
            value=env.get(name,'')
            if not isinstance(value,str) or not value.strip() or value!=value.strip():raise ConfigurationError('Missing or invalid '+name)
            return value
        database=required('DATABASE_URL')
        if not database.startswith(('postgres://','postgresql://')):raise ConfigurationError('Invalid DATABASE_URL')
        account=required('R2_ACCOUNT_ID');bucket=required('R2_BUCKET')
        if not re.fullmatch('[0-9a-f]{32}',account):raise ConfigurationError('R2_ACCOUNT_ID must contain only the 32-character account ID')
        if not re.fullmatch('[a-z0-9][a-z0-9-]{1,61}[a-z0-9]',bucket):raise ConfigurationError('Invalid R2_BUCKET')
        access=required('R2_ACCESS_KEY_ID');secret=required('R2_SECRET_ACCESS_KEY')
        try:
            rate=float(required('KALSHI_READ_RATE'))
            capacity=int(required('KALSHI_READ_CAPACITY'));cost=int(required('KALSHI_ENDPOINT_COST'))
            if not math.isfinite(rate) or not 0<rate<=100000 or not 1<=cost<=capacity<=100000:raise ValueError()
        except ValueError:raise ConfigurationError('Invalid Kalshi application read budget') from None
        enabled=env.get('COLLECTION_ENABLED','false')
        if enabled not in ('true','false'):raise ConfigurationError('COLLECTION_ENABLED must be true or false')
        acceptance=env.get('STAGING_ACCEPTANCE','off')
        if acceptance not in ('off','r2-v1','database-v1') or (enabled=='true' and acceptance!='off'):
            raise ConfigurationError('Invalid STAGING_ACCEPTANCE or collection must be disabled')
        operator=env.get('STAGING_OPERATOR_ACTION','off')
        if operator not in ('off','prepare-roles-v1','activate-roles-v1') or (operator!='off' and (enabled=='true' or acceptance!='off')):
            raise ConfigurationError('Invalid STAGING_OPERATOR_ACTION or disable collection and diagnostics')
        verifiers={}
        if operator=='activate-roles-v1':
            from services.api.operations import validate_runtime_verifiers
            try:
                verifiers=json.loads(env.get('STAGING_RUNTIME_VERIFIERS',''))
                validate_runtime_verifiers(verifiers)
            except Exception:raise ConfigurationError('Invalid private runtime verifier configuration') from None
        elif env.get('STAGING_RUNTIME_VERIFIERS',''):
            raise ConfigurationError('Clear private runtime verifiers outside activation')
        return cls(database,account,bucket,access,secret,rate,capacity,cost,enabled=='true',acceptance,operator,verifiers)


@contextmanager
def termination(stop):
    """Stop taking work, finish/checkpoint the current bounded step, then clean up."""
    previous={}
    try:
        for name in (signal.SIGTERM,signal.SIGINT):
            previous[name]=signal.signal(name,lambda *_:stop.set())
        yield
    finally:
        for name,handler in previous.items():signal.signal(name,handler)


def run(settings,stop):
    # Disabled staging deploys do not construct SDK/DB clients or schedule/fetch work.
    if not settings.enabled:
        if settings.operator_action!='off':
            from services.api.operations import prepare_runtime_roles,activate_runtime_roles
            try:
                receipt=(activate_runtime_roles(settings.database_url,settings.runtime_verifiers)
                         if settings.operator_action=='activate-roles-v1' else prepare_runtime_roles(settings.database_url))
                print(json.dumps(receipt,sort_keys=True),flush=True)
            except Exception:
                print('Staging operator action failed; no retry; collection remains disabled',file=sys.stderr,flush=True)
        if settings.acceptance!='off':
            from .acceptance import run_check
            try:
                print(json.dumps(run_check(settings,settings.acceptance),sort_keys=True),flush=True)
            except Exception:
                # One bounded attempt per process, then idle rather than a crash/retry loop.
                print('Staging acceptance failed; collection remains disabled',file=sys.stderr,flush=True)
        while not stop.is_set():stop.wait(30)
        return
    from .acceptance import audit_database
    if not audit_database(settings.database_url)['privilege_boundary_ready']:
        raise ConfigurationError('Research runtime database privileges are not isolated')
    with ExitStack() as stack:
        pool=ConnectionPool(settings.database_url,min_size=1,max_size=2,open=False,timeout=5,
            kwargs={'row_factory':dict_row,'connect_timeout':5,'options':'-c statement_timeout=30000'})
        stack.callback(pool.close);pool.open(wait=True,timeout=5)
        # Runtime pre-deploy commands verify an operator-applied schema, never migrate.
        with pool.connection() as c:
            if not c.execute("SELECT to_regclass('research_campaign_result') IS NOT NULL AS ready").fetchone()['ready']:
                raise ConfigurationError('Apply the committed migrations before starting collection')
        objects=R2Objects.connect(account_id=settings.account_id,bucket=settings.bucket,
            access_key_id=settings.access_key_id,secret_access_key=settings.secret_access_key)
        stack.callback(objects.client.close)
        archives=ArchiveStore(objects,cache_bytes=16*1024*1024);queue=ResearchQueue(pool);budget=ReadBudget(pool)
        budget.configure(settings.read_rate,settings.read_capacity,allow_update=True)
        inventory=stack.enter_context(KalshiInventory());evidence=stack.enter_context(KalshiEvidence(archives=archives))
        worker=CampaignWorker(pool,archives,
            InventoryWorker(queue,archives,inventory,budget,endpoint_cost=settings.endpoint_cost),
            EvidenceWorker(queue,archives,evidence,budget,endpoint_cost=settings.endpoint_cost),parallelism=4)
        from .heartbeat import WorkerHeartbeat
        heartbeat=WorkerHeartbeat(pool)
        print('Collection enabled; worker ready',flush=True)
        print(f'Collection pacing: {settings.read_rate:g} public reads/sec, burst {settings.read_capacity}; retained recent candle batches; inventory/evidence concurrency 4',flush=True)
        from .telemetry import configure
        meter=configure(lambda data:print(json.dumps(data,sort_keys=True,separators=(',',':')),flush=True))
        campaigns=CampaignStore(pool)
        try:serve(campaigns,worker,stop,on_tick=heartbeat.beat,idle_wait=campaigns.next_wait,on_error=lambda code:print(code,file=sys.stderr,flush=True))
        finally:
            meter.flush(force=True);configure()


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description='Pocket Analytics research worker')
    parser.add_argument('--check-config',action='store_true',help='Validate names/format only; no hosted connections')
    args=parser.parse_args(argv)
    try:
        settings=WorkerSettings.from_env()
        if args.check_config:
            print('Worker configuration format valid; connections not tested');return 0
        stop=Event()
        with termination(stop):run(settings,stop)
        return 0
    except ConfigurationError as error:
        print(str(error),file=sys.stderr);return 2
    except Exception:
        # SDK/PG exceptions can include credentials, hostnames or provider diagnostics.
        print('Worker startup failed; verify private configuration and service availability',file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
