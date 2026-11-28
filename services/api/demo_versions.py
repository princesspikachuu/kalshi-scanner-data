"""Read-only analysis versions inferred from original saved entry rules."""
import json
import time
import threading
from psycopg.types.json import Jsonb


def infer_versions(bots,orders,events):
    versions={}
    for bot in bots:
        key=bot['key'];config=bot['config'];revision=int(bot['revision'])
        own=[r for r in orders if r['bot']==key and r.get('revision') is not None]
        current=[r for r in own if int(r['revision'])==revision]
        first=min((float(r['first_at']) for r in current),default=None)
        prior=max((float(r['last_at']) for r in own if int(r['revision'])<revision),default=float(bot['created_at']))
        updates=[r for r in events if r['bot']==key and float(r['at'])>=prior and (first is None or float(r['at'])<=first)]
        audited=[r for r in events if r['bot']==key and r.get('details',{}).get('revision')==revision
            and r.get('details',{}).get('rule_revision_changed') is True]
        exact=min(audited,key=lambda r:float(r['at'])) if audited else updates[0] if len(updates)==1 else None
        initial=revision==1
        changed=float(bot['created_at']) if initial else float(exact['at']) if exact else None
        versions[key]=dict(label='Most recent version',revision=revision,
            buy_cents=config.get('cycle_buy_cents') if config.get('strategy')=='buy_low_sell_high' else None,
            sell_cents=config.get('cycle_sell_cents') if config.get('strategy')=='buy_low_sell_high' and config.get('cycle_exit_mode','profit')=='profit' else None,
            exit_mode=config.get('cycle_exit_mode','profit'),hold_threshold_cents=config.get('late_exit_threshold_cents',40),
            changed_at=changed,first_entry_at=first,
            window_start=min((float(r['at']) for r in updates),default=None),
            window_end=max((float(r['at']) for r in updates),default=None),
            evidence='created_with_rules' if initial else 'saved_settings_event' if exact else 'saved_entry_revision')
    return versions


class VersionCatalog:
    def __init__(self,pool):self.pool=pool;self.cached=None;self.expires=0;self.lock=threading.Lock();self.logged=set()
    def invalidate(self):self.expires=0
    def load(self):
        with self.lock:
            if self.cached is not None and time.monotonic()<self.expires:return self.cached
            with self.pool.connection() as c:
                c.execute('SET LOCAL statement_timeout=5000')
                bots=c.execute("""SELECT substring(idempotency_key from 10) AS key,parameters->'config' AS config,
                    (parameters->>'revision')::integer AS revision,extract(epoch FROM created_at) AS created_at
                    FROM research_job WHERE idempotency_key>='demo/bot/' AND idempotency_key<'demo/bot/zzzz'""").fetchall()
                orders=c.execute("""SELECT parameters->>'bot' AS bot,(parameters->>'revision')::integer AS revision,
                    max(coalesce((parameters->>'created_at')::numeric,extract(epoch FROM created_at))) AS last_at,
                    min(coalesce((parameters->>'created_at')::numeric,extract(epoch FROM created_at))) AS first_at
                    FROM research_job WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz'
                      AND parameters->>'kind'='entry'
                    GROUP BY 1,2""").fetchall()
                events=c.execute("""SELECT parameters->>'bot' AS bot,extract(epoch FROM created_at) AS at,
                    coalesce(progress->'details','{}'::jsonb) AS details FROM research_job
                    WHERE idempotency_key>='demo/event/' AND idempotency_key<'demo/event/zzzz'
                      AND parameters->>'kind'='bot_updated' ORDER BY created_at""").fetchall()
            self.cached=infer_versions(bots,orders,events);self.expires=time.monotonic()+60
            for bot in bots:
                version=self.cached.get(bot['key'])
                if version is None:continue
                signature=(bot['key'],version['revision'],version['changed_at'])
                if signature not in self.logged:
                    print(json.dumps(dict(event='demo_analysis_version',bot=bot['key'],name=bot['config'].get('name'),**version)),flush=True)
                    self.logged.add(signature)
            return self.cached


def version_clause(version,versions,alias=''):
    if version not in ('full','latest'):raise ValueError('Invalid analysis version')
    if version=='full':return 'TRUE',[]
    p=alias+'parameters'
    return f"coalesce(({p}->>'revision')::integer,0)=coalesce((%s::jsonb->>({p}->>'bot'))::integer,coalesce(({p}->>'revision')::integer,0))",[Jsonb({key:value['revision'] for key,value in versions.items()})]


def activity_version_clause(version,versions):
    if version=='full' or not versions:return 'TRUE',[]
    revisions={k:v['revision'] for k,v in versions.items()}
    clocks={k:v['changed_at'] or v['first_entry_at'] or v['window_start'] or 0 for k,v in versions.items()}
    # Only this app's immutable order-parent IDs establish transaction ownership.
    return """(parameters->>'bot' IS NULL OR NOT (%s::jsonb ? (parameters->>'bot')) OR EXISTS (
        SELECT 1 FROM research_job o LEFT JOIN research_job b
          ON b.idempotency_key='demo/order/'||(o.parameters->>'parent')
        WHERE o.idempotency_key='demo/order/'||(research_job.progress#>>'{details,client_id}')
          AND o.parameters->>'bot'=research_job.parameters->>'bot'
          AND coalesce((b.parameters->>'revision')::integer,(o.parameters->>'revision')::integer,0)
              =(%s::jsonb->>(research_job.parameters->>'bot'))::integer
        ) OR (parameters->>'kind' NOT IN ('order_intent','order','order_rejected','order_uncertain',
          'fill','fill_recovered','cancel','settlement','realized','position_offset','exit_trigger')
          AND extract(epoch FROM created_at)>=(%s::jsonb->>(parameters->>'bot'))::numeric))""",[Jsonb(revisions),Jsonb(revisions),Jsonb(clocks)]
