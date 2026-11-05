"""One-time, audited rollout requested for the running low/high bots."""
import json,time
from datetime import datetime,timezone
from uuid import uuid4
from psycopg.types.json import Jsonb

ROLLOUT='demo/rollout/late-threshold-hold-20261105'

def apply_entry_window_rollout(store):
    """Called under the worker fence; controls, versions and audit commit together."""
    from .engine import protective_threshold
    changed=[]
    with store.pool.connection() as c:
        if c.execute('SELECT 1 FROM research_job WHERE idempotency_key=%s',(ROLLOUT,)).fetchone():return []
        rows=c.execute("""SELECT idempotency_key,parameters FROM research_job
            WHERE idempotency_key>='demo/bot/' AND idempotency_key<'demo/bot/zzzz'
            AND parameters#>>'{config,strategy}'='buy_low_sell_high'
            AND progress->>'desired'='running' AND NOT coalesce((progress->>'archived')::boolean,false)
            ORDER BY idempotency_key FOR UPDATE""").fetchall()
        def insert(key,data,parameters):
            c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())""",
                (uuid4(),Jsonb(parameters),Jsonb(data),key))
        for row in rows:
            parameters=dict(row['parameters']);old=parameters['config'];identifier=row['idempotency_key'].split('/')[-1]
            changes=dict(cycle_buy_cents=3,cycle_entry_minutes=5,cycle_repeat=False,cycle_exit_mode='late_threshold',
                late_exit_minutes=5,late_exit_threshold_cents=40,late_exit_reprice_cents=5,require_active_market=True,loss_mode='off',loss_cents=None)
            config=dict(old,**changes)
            if all(old.get(k)==v for k,v in changes.items()):continue
            prior=dict(parameters.get('prior_protection',{}))
            prior[str(parameters['revision'])]=[protective_threshold(old,s) for s in old['squares']]
            parameters.update(config=config,prior_protection=prior,
                settings_revision=parameters.get('settings_revision',parameters['revision'])+1,revision=parameters['revision']+1)
            c.execute('UPDATE research_job SET parameters=%s WHERE idempotency_key=%s',(Jsonb(parameters),row['idempotency_key']))
            # Existing inventory adopts the new exit policy without relabeling
            # its entry revision or changing any saved fill or profit history.
            exit_policy={k:config[k] for k in ('cycle_exit_mode','late_exit_minutes','late_exit_threshold_cents','late_exit_reprice_cents')}
            adopted=c.execute("""UPDATE research_job SET parameters=parameters||%s
                WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz'
                AND parameters->>'bot'=%s AND parameters->>'kind'='entry'
                AND parameters->>'entry_strategy'='buy_low_sell_high'
                AND progress->>'status' NOT IN ('closed','rejected')""",(Jsonb(exit_policy),identifier)).rowcount
            now=datetime.now(timezone.utc).isoformat()
            details=dict(rule_revision_changed=True,revision=parameters['revision'],settings_revision=parameters['settings_revision'],
                changed_fields=sorted(k for k,v in changes.items() if old.get(k)!=v),old_cycle_entry_minutes=old.get('cycle_entry_minutes'),
                old_cycle_repeat=old.get('cycle_repeat',True),cycle_entry_minutes=5,cycle_repeat=False,
                old_cycle_buy_cents=old['cycle_buy_cents'],old_cycle_sell_cents=old['cycle_sell_cents'],
                cycle_buy_cents=config['cycle_buy_cents'],cycle_sell_cents=config['cycle_sell_cents'],exit_mode='late_threshold',hold_threshold_cents=40)
            insert('demo/event/'+str(uuid4()),dict(kind='bot_updated',message='Buy 3c in first five minutes; hold, with conditional final-five-minute maker exits below 40c',
                bot=identifier,ticker=None,details=details,time=now,critical=False),dict(kind='bot_updated',bot=identifier,ticker=None,time=now))
            changed.append(dict(bot=identifier,name=config['name'],revision=parameters['revision'],adopted_entry_orders=adopted))
        insert(ROLLOUT,dict(at=time.time(),bots=changed),dict(kind='authorized_entry_policy_rollout'))
    print(json.dumps(dict(event='demo_entry_policy_rollout',count=len(changed),entry_minutes=5,repeat=False,exit_mode='late_threshold',hold_threshold=40,bots=changed)),flush=True)
    return changed
