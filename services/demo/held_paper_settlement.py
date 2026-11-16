"""Explicit held-paper payout plans and fenced atomic persistence.

No startup hook, discovery, exchange order client, clock advancement or bot
initialization. Callers first fetch fresh public outcomes and preserve verified
reconciliation evidence in R2. Financial originals are never deleted.
"""
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
import math
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

from psycopg.types.json import Jsonb
from services.paper_demo.shadow.checkpoint_codec import pack_checkpoint, unpack_checkpoint
from services.paper_demo.shadow.core import Engine
from services.paper_demo.shadow.state import restore
from services.demo.maintenance import read_verified

CHECKPOINT = 'demo/shadow/checkpoint'
PREFIX = 'demo/shadow/settlement-recovery/'
RUNTIME_LOCK = 723741931
MODE_LOCK = 723741941
MAX_MARKETS = 256
MAX_LOTS = 5000


def frozen(value):
    return json.loads(json.dumps(value, default=str))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     default=str).encode()).hexdigest()


def held(env):
    required = dict(MT_STORAGE_RECOVERY_HOLD='true', COLLECTION_ENABLED='false',
                    RUNTIME_DB_PROFILE='research', WORKER_ROLE='collector',
                    MT_CONTROL_BACKUP_HELD_WORKER='true',
                    MT_CONTROL_BACKUP_V2_ENABLED='true',
                    MT_DIAGNOSTIC_RETENTION_HELD_WORKER='false',
                    MT_DIAGNOSTIC_RETENTION_ENABLED='false')
    if any(env.get(k) != v for k, v in required.items()) or env.get('RECOVERY_DATABASE_URL'):
        raise ValueError('held_paper_settlement_environment_required')


def portfolios(data):
    yield 'convexity', data
    experiments = data.get('experiments', {})
    if len(experiments) > 64:
        raise ValueError('portfolio_capacity')
    for folder, value in experiments.items():
        if folder.startswith('_'):
            continue
        if not isinstance(value, dict) or not isinstance(value.get('engine'), dict):
            raise ValueError('invalid_portfolio_state')
        yield folder, value['engine']


def pending_markets(payload, now):
    if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
        raise ValueError('invalid_recovery_time')
    data = unpack_checkpoint(payload)
    needed = set()
    for _, state in portfolios(data):
        if now < state['now'] or len(state['wallet']['lots']) > MAX_LOTS:
            raise ValueError('invalid_recovery_boundary')
        for lot in state['wallet']['lots']:
            quantity = Decimal(lot['quantity'])
            if not quantity.is_finite() or quantity <= 0 or lot['side'] not in ('yes', 'no'):
                raise ValueError('invalid_saved_lot')
            market = state['markets'][lot['ticker']]
            close = market['close']
            if isinstance(close, bool) or not isinstance(close, (int, float)) or not math.isfinite(close):
                raise ValueError('invalid_close_boundary')
            if market.get('paid'):
                raise ValueError('paid_market_has_inventory')
            if close <= now:
                needed.add(lot['ticker'])
    if len(needed) > MAX_MARKETS:
        raise ValueError('settlement_market_capacity')
    return needed


class Capture:
    def __init__(self, path, folder, rows):
        self.path, self.folder, self.rows = path, folder, rows

    def log(self, now, kind, wallet, **fields):
        event = dict(time=now, event=kind, cash=str(wallet.cash), **fields)
        if self.folder != 'convexity':
            event.update(folder_id=self.folder, experiment_kind=kind)
        self.rows.append(frozen(event))


def build_plan(payload, outcomes, *, now):
    """Produce a new checkpoint and normal audit/reports without database I/O.

    Only closed inventory with a fresh authoritative final yes/no outcome is
    eligible. Unknown checkpoint and strategy fields are preserved byte-for-byte
    at the decoded-value level. Downtime-affected cycles remain excluded.
    """
    needed = pending_markets(payload, now)
    if not needed or set(outcomes) != needed:
        raise ValueError('exact_closed_inventory_outcomes_required')
    for ticker, evidence in outcomes.items():
        if (not isinstance(evidence, dict) or evidence.get('ticker') != ticker
                or evidence.get('status') not in ('finalized', 'settled')
                or evidence.get('result') not in ('yes', 'no')
                or isinstance(evidence.get('fetched_at'), bool)
                or not isinstance(evidence.get('fetched_at'), (int, float))
                or not math.isfinite(evidence['fetched_at'])
                or not -5 <= now - evidence['fetched_at'] <= 300):
            raise ValueError('final_venue_outcome_required')
    data = deepcopy(unpack_checkpoint(payload))
    events = []
    affected = []
    with TemporaryDirectory(prefix='mt-held-settlement-') as directory:
        path = Path(directory)
        with open(path / 'stdout.txt', 'w') as output, redirect_stdout(output):
            for folder, state in portfolios(data):
                targets = sorted({lot['ticker'] for lot in state['wallet']['lots']} & needed)
                if not targets:
                    continue
                original = deepcopy(state)
                audit = Capture(path, folder, events)
                engine = Engine(audit)
                engine.wall_clock = lambda: now
                # restore is used only on an isolated copy. Undo its restart-only
                # changes for unrelated orders/stats; no fleet is instantiated.
                restore(engine, SimpleNamespace(bots={}, halted=set(), owner=lambda _: None), state)
                for ticker, stat in engine.wallet.stats.items():
                    stat.valid = state['wallet']['stats'].get(ticker, {}).get('valid', True)
                for ident, order in engine.orders.items():
                    order.status = state['orders'][ident]['status']
                    order.reserved = Decimal(state['orders'][ident]['reserved'])
                engine.now = now
                for ticker in targets:
                    evidence = outcomes[ticker]
                    # No queued action may run during downtime recovery. Only
                    # pending/resting orders on this closed market are cancelled.
                    for order in engine.orders.values():
                        if order.ticker == ticker and order.status in ('pending', 'resting'):
                            order.status, order.reserved = 'cancelled', Decimal(0)
                            engine.log('CANCELLED', order, reason='closed market payout recovery')
                    engine.wallet.stat(ticker).valid = False
                    engine.markets[ticker].update(settlement_confirmation='production_rest',
                        yes_payout_confirmed='1' if evidence['result'] == 'yes' else '0')
                    engine.settled.add(ticker)
                    engine.log('SETTLEMENT_RECOVERED', ticker=ticker,
                        reason='production REST finalized result; held paper payout recovery')
                    engine.complete_settlement(ticker, Decimal(engine.markets[ticker]['yes_payout_confirmed']))
                credit = sum((Decimal(lot['quantity']) * (Decimal(1) if
                    outcomes[lot['ticker']]['result'] == lot['side'] else Decimal(0))
                    for lot in original['wallet']['lots'] if lot['ticker'] in targets), Decimal(0))
                if abs(engine.wallet.cash - Decimal(original['wallet']['cash']) - credit) > Decimal('1e-18'):
                    raise ValueError('settlement_credit_mismatch')
                if engine.wallet.deposits != Decimal(original['wallet']['deposits']):
                    raise ValueError('settlement_deposit_mutation')
                state['wallet']['cash'] = str(engine.wallet.cash)
                state['wallet']['lots'] = [lot for lot in original['wallet']['lots'] if lot['ticker'] not in targets]
                for ticker in targets:
                    stats = engine.wallet.stat(ticker)
                    old_stats = original['wallet']['stats'].get(ticker, {})
                    if stats.fees_paid != Decimal(old_stats.get('fees_paid', '0')):
                        raise ValueError('settlement_fee_total_mutation')
                    state['wallet']['stats'][ticker] = dict(old_stats, **frozen(asdict(stats)))
                    state['markets'][ticker] = engine.markets[ticker]
                for ident, order in engine.orders.items():
                    if order.ticker in targets and original['orders'][ident]['status'] in ('pending', 'resting'):
                        state['orders'][ident].update(status='cancelled', reserved='0')
                state['pending'] = [action for action in original['pending']
                                    if original['orders'][action[3]]['ticker'] not in targets]
                state['settled'] = sorted(engine.settled)
                state['now'] = now
                affected.append(dict(folder=folder, markets=len(targets),
                    lots=sum(lot['ticker'] in targets for lot in original['wallet']['lots']),
                    payout=str(credit)))
    proposed = pack_checkpoint(data, binary=True)
    if len(events) > 10000:
        raise ValueError('settlement_audit_capacity')
    return dict(format='held-paper-settlement-plan-v1', source_sha256=digest(payload),
                proposed_sha256=digest(proposed), proposed=proposed,
                outcomes=frozen(outcomes), events=events, affected=affected, at=now)


def validate_runtime(connection):
    role = connection.execute("SELECT current_database(),current_user,rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
    if tuple(role) != ('pocket_staging', 'pocket_research_runtime', False, False, False, False, False):
        raise ValueError('restricted_paper_runtime_required')


def commit_plan(connection, objects, plan, expected, reference, *, env):
    """Verify a durable exact plan, then CAS checkpoint and audits atomically.

    Connection must be idle/autocommit; both normal runtime and trading-mode
    advisory fences are acquired nonblocking inside the short transaction.
    Repeated execution is recognized by an immutable operation receipt.
    """
    held(env)
    if not -5 <= time.time() - plan['at'] <= 300:
        raise ValueError('fresh_settlement_plan_required')
    if digest(expected) != plan['source_sha256'] or digest(plan['proposed']) != plan['proposed_sha256']:
        raise ValueError('plan_identity_mismatch')
    # No network I/O while holding SQL locks. This object also preserves the
    # complete before-image, outcomes, intended audits and reconciliation link.
    proof = read_verified(objects, reference)
    if proof.get('format') != 'held-paper-settlement-evidence-v1' or proof.get('plan') != plan or proof.get('before') != expected:
        raise ValueError('verified_before_image_and_plan_required')
    if not proof.get('reconciliation_reference'):
        raise ValueError('financial_reconciliation_reference_required')
    reconciliation = read_verified(objects, proof['reconciliation_reference'])
    if (reconciliation.get('format') != 'current-paper-financial-reconciliation-v1'
            or reconciliation.get('financial_state_changed') is not False
            or reconciliation.get('venue', {}).get('recorded_outcome_mismatches') != 0
            or reconciliation.get('venue', {}).get('recorded_outcomes_not_final') != 0
            or not reconciliation.get('replay')
            or not all(v.get('replay_matches_checkpoint') and v.get('recorded_fees_match_saved_totals')
                       for v in reconciliation['replay'].values())):
        raise ValueError('verified_financial_reconciliation_required')
    baseline = read_verified(objects, reconciliation['checkpoint_reference'])
    if baseline.get('progress') != expected:
        raise ValueError('reconciliation_checkpoint_mismatch')
    # Rebuild locally from saved inputs, not from caller-controlled proposed
    # balances/audit rows. This also rejects a truncated or modified plan.
    rebuilt = build_plan(expected, plan['outcomes'], now=plan['at'])
    if rebuilt != plan:
        raise ValueError('settlement_plan_rebuild_mismatch')
    planned_state = unpack_checkpoint(plan['proposed'])
    if not connection.autocommit or connection.info.transaction_status != 0:
        raise ValueError('idle_autocommit_connection_required')
    key = PREFIX + digest(plan)
    with connection.transaction():
        connection.execute("SET LOCAL statement_timeout='5s'")
        connection.execute("SET LOCAL lock_timeout='1s'")
        connection.execute("SET LOCAL idle_in_transaction_session_timeout='10s'")
        validate_runtime(connection)
        for lease in (RUNTIME_LOCK, MODE_LOCK):
            if not connection.execute('SELECT pg_try_advisory_xact_lock(%s)', (lease,)).fetchone()[0]:
                raise ValueError('paper_runtime_or_mode_fence_busy')
        existing = connection.execute('SELECT progress FROM research_job WHERE idempotency_key=%s', (key,)).fetchone()
        if existing:
            if existing[0].get('proposed_sha256') != plan['proposed_sha256']:
                raise ValueError('operation_receipt_mismatch')
            return dict(already_applied=True, operation_key=key)
        current = connection.execute('SELECT id,progress FROM research_job WHERE idempotency_key=%s FOR UPDATE', (CHECKPOINT,)).fetchone()
        if not current or current[1] != expected:
            raise ValueError('checkpoint_changed')
        connection.execute('UPDATE research_job SET progress=%s,finished_at=clock_timestamp() WHERE id=%s',
                           (Jsonb(plan['proposed']), current[0]))
        insert = """INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                    VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())"""
        for event in plan['events']:
            params = dict(kind='EXPERIMENT' if event.get('folder_id') else event['event'],
                          ticker=event.get('ticker'), time=event['time'])
            connection.execute(insert, (uuid4(), Jsonb(params), Jsonb(event), 'demo/shadow/event/' + str(uuid4())))
            if event['event'] == 'CYCLE_REPORT':
                report = json.loads(event['details']);report['at'] = event['time']
                folder = event.get('folder_id')
                report_parameters = {}
                if not folder:
                    report['bot_revision'] = planned_state['markets'][report['ticker']].get('bot_revision', 1)
                    report_parameters = dict(time=event['time'], bot_id=report.get('bot_id'))
                report_key = ('demo/experiment/report/' + folder + '/' if folder else 'demo/shadow/report/') + report['ticker']
                written = connection.execute(insert + " ON CONFLICT(idempotency_key) DO UPDATE SET progress=excluded.progress,finished_at=clock_timestamp() WHERE research_job.progress->>'final' IS DISTINCT FROM 'true'",
                                             (uuid4(), Jsonb(report_parameters), Jsonb(report), report_key))
                if written.rowcount != 1:
                    raise ValueError('existing_final_report_conflict')
        receipt = dict(format='held-paper-settlement-committed-v1', source_sha256=plan['source_sha256'],
                       proposed_sha256=plan['proposed_sha256'], evidence_reference=reference,
                       affected=plan['affected'], at=plan['at'])
        connection.execute(insert, (uuid4(), Jsonb({}), Jsonb(receipt), key))
    return dict(already_applied=False, operation_key=key)
