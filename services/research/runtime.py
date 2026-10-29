"""Explicit deployment entry point. Import and --check-config perform no I/O."""
from contextlib import ExitStack,contextmanager
from dataclasses import dataclass,field,replace
import math
import json
import os
import re
import signal
import sys
from threading import Event,Thread

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
    role:str='combined'

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
        role=env.get('WORKER_ROLE','combined')
        if role not in ('combined','split','collector','processor'):raise ConfigurationError('Invalid WORKER_ROLE')
        return cls(database,account,bucket,access,secret,rate,capacity,cost,enabled=='true',acceptance,operator,verifiers,role)


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
    if settings.role=='split':return run_split(settings,stop)
    from .acceptance import audit_database
    if not audit_database(settings.database_url)['privilege_boundary_ready']:
        raise ConfigurationError('Research runtime database privileges are not isolated')
    with ExitStack() as stack:
        pool=ConnectionPool(settings.database_url,min_size=1,max_size=6 if settings.role=='combined' else (4 if settings.role=='collector' else 2),open=False,timeout=5,
            kwargs={'row_factory':dict_row,'connect_timeout':5,'options':'-c statement_timeout=30000'})
        stack.callback(pool.close);pool.open(wait=True,timeout=5)
        # Runtime pre-deploy commands verify an operator-applied schema, never migrate.
        with pool.connection() as c:
            if not c.execute("SELECT to_regclass('research_campaign_result') IS NOT NULL AS ready").fetchone()['ready']:
                raise ConfigurationError('Apply the committed migrations before starting collection')
        objects=R2Objects.connect(account_id=settings.account_id,bucket=settings.bucket,
            access_key_id=settings.access_key_id,secret_access_key=settings.secret_access_key)
        stack.callback(objects.client.close)
        archives=ArchiveStore(objects,cache_bytes=(16 if settings.role=='combined' else 4)*1024*1024)
        queue=ResearchQueue(pool)
        if settings.role=='processor':
            # Paper service never constructs provider clients or executes
            # research assembly, report publication, or saved-data analysis.
            from services.paper.worker import PaperWorker
            worker=PaperWorker(pool,archives)
        else:
            budget=ReadBudget(pool)
            from .kalshi_auth import signer_from_env
            signer=signer_from_env(os.environ)
            inventory=stack.enter_context(KalshiInventory(signer=signer));evidence=stack.enter_context(KalshiEvidence(archives=archives,signer=signer))
            if signer is not None:
                allowance=inventory.account_allowance();ceiling=allowance['requests_per_second']*.9
                capacity=min(12,allowance['burst_capacity'],max(1,int(ceiling)))
                budget.configure(ceiling,capacity,allow_update=True,preserve_capacity=True)
                budget.authenticated(ceiling,signer.key_id,capacity)
                print(json.dumps(dict(event='authenticated_kalshi_allowance',tier=allowance['usage_tier'],
                    allowed_requests_per_second=allowance['requests_per_second'],target_ceiling=ceiling)),flush=True)
            else:budget.configure(settings.read_rate,settings.read_capacity,allow_update=True)
            worker=CampaignWorker(pool,archives,
                InventoryWorker(queue,archives,inventory,budget,endpoint_cost=settings.endpoint_cost),
                EvidenceWorker(queue,archives,evidence,budget,endpoint_cost=settings.endpoint_cost),parallelism=12,stop=stop,
                role=settings.role,preview_limit=300 if settings.role=='collector' else 100)
            worker.background_analysis=True
            from .reuse import VerifiedReads
            worker.inventory_worker.reuse=worker.evidence_worker.reuse=VerifiedReads(pool,archives)
        from .heartbeat import WorkerHeartbeat,DayProgress
        heartbeat=WorkerHeartbeat(pool)
        print(f'Collection enabled; {settings.role} worker ready',flush=True)
        if settings.role!='processor':print(f'Collection pacing: shared budget; retained recent candle batches; inventory/evidence concurrency 12',flush=True)
        from .telemetry import configure
        meter=configure(lambda data:print(json.dumps(data,sort_keys=True,separators=(',',':')),flush=True))
        campaigns=CampaignStore(pool,collection_limit=300)
        progress=DayProgress(pool,lambda data:print(json.dumps(data,default=str,sort_keys=True),flush=True))
        def tick():
            heartbeat.beat();progress.emit()
        worker.on_work_tick=tick
        analysis_thread=None
        if settings.role=='collector':
            # This is a SECOND execution lane within the existing collection
            # service, not a new Render service or paper-processing resource.
            # Evidence downloads and saved-data assembly can overlap; costly
            # report analysis yields whenever collection or paper is active.
            from .processing import ProcessingWorker
            research=ProcessingWorker(pool,archives,stop=stop)
            def run_research():
                serve(campaigns,research,stop,on_tick=tick,idle_wait=lambda:1,
                    schedule=False,on_error=lambda code:print(code,file=sys.stderr,flush=True))
            analysis_thread=Thread(target=run_research,name='collection-data-and-analysis',daemon=True)
            analysis_thread.start()
        try:
            serve(campaigns,worker,stop,on_tick=tick,idle_wait=(lambda:1) if settings.role=='processor' else campaigns.next_wait,
                schedule=settings.role!='processor',on_error=lambda code:print(code,file=sys.stderr,flush=True))
        finally:
            if analysis_thread is not None:
                stop.set()
                analysis_thread.join(timeout=10)
            meter.flush(force=True);configure()


def _child(settings,stop):
    # Spawned processes build independent SDK clients, caches and DB pools.
    # The paper-only processor never constructs provider clients or research workers.
    try:run(settings,stop)
    except Exception:
        print(f'{settings.role} worker exited; private error details suppressed',file=sys.stderr,flush=True)
        raise SystemExit(1) from None


def run_split(settings,stop):
    """Two isolated processes on one instance; leases survive either one's exit.

    The same role settings can also be run on independent Render services. Keep
    the aggregate database pool at six connections for the initial split.
    """
    import multiprocessing
    import time
    context=multiprocessing.get_context('spawn');children=[];shared_stop=context.Event()
    try:
        for role in ('collector','processor'):
            child=context.Process(target=_child,args=(replace(settings,role=role),shared_stop),name='research-'+role)
            child.start();children.append(child)
        print('Split enabled: collection/data/analysis service and paper-only service; shared durable queue',flush=True)
        while not stop.is_set():
            if any(not child.is_alive() for child in children):
                raise RuntimeError('Split worker process exited')
            stop.wait(1)
    finally:
        shared_stop.set()
        deadline=time.monotonic()+100
        for child in children:child.join(max(0,deadline-time.monotonic()))
        for child in children:
            if child.is_alive():child.terminate()
        for child in children:child.join(5)


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
