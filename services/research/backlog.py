"""Saved-data analysis, independent of request lifetime; cooperative category turns."""
from dataclasses import replace
import json
from time import monotonic
from uuid import UUID,uuid5
from psycopg.types.json import Jsonb
from .queue import ResearchQueue,LeaseLost
from .datasets import DatasetStore,decoded_dataset,prepare_dataset,CollectionInterrupted
from .evidence import plan_from_receipt
from .normalize import batch_from_dict
from .reports import ReportStore
from .sample import select_preview_candidates


def saved_tickers(pool,day):
    """Union actual saved membership, including removed requests and other categories."""
    from .report_inputs import report_dataset
    with pool.connection() as c:
        ids=c.execute('''SELECT DISTINCT ds.id FROM research_campaign_day d
            JOIN research_campaign r ON r.id=d.campaign_id
            JOIN research_dataset ds ON ds.day=d.day AND ds.stream_key IN (
                'campaign-'||replace(r.id::text,'-',''),
                'campaign-candles-'||replace(r.id::text,'-',''),
                'campaign-sample-'||replace(r.id::text,'-','')) WHERE d.day=%s''',(day,)).fetchall()
    result=set()
    for row in ids:
        with pool.connection() as c:data=c.execute('SELECT id,fingerprint,payload FROM research_dataset WHERE id=%s',(row['id'],)).fetchone()
        result.update(v['ticker'] for v in report_dataset(data)['payload']['candidates'])
    return result


class AnalysisBacklog:
    """One HTTP page per turn; every saved cohort, without reviving removed requests."""
    def __init__(self,owner):
        self.owner=owner;self.pool=owner.pool;self.queue=owner.queue;self.archives=owner.archives
        self.asset=None;self.turn_started=0;self.cached=None;self.bootstrap_at=0

    def collecting(self):
        with self.pool.connection() as c:
            return bool(c.execute("""SELECT 1 FROM research_campaign r JOIN research_job j ON j.id=r.job_id
                WHERE j.status IN ('queued','running')
                AND NOT coalesce((j.progress->>'removed_from_queue')::boolean,false) LIMIT 1""").fetchone())

    def bootstrap(self):
        if monotonic()-self.bootstrap_at<30:return
        with self.pool.connection() as c:
            rows=c.execute("""SELECT ds.id,r.asset,r.id AS campaign_id,ds.day FROM research_dataset ds
                JOIN research_campaign r ON ds.stream_key IN ('campaign-candles-'||replace(r.id::text,'-',''),
                    'campaign-'||replace(r.id::text,'-',''))
                JOIN research_summary s ON s.dataset_id=ds.id
                LEFT JOIN research_job a ON a.idempotency_key='analysis-source/'||ds.id::text
                WHERE a.id IS NULL AND NOT(s.summary->'resources' ? 'trades')
                AND NOT EXISTS(SELECT 1 FROM research_campaign_day cd JOIN research_summary cs ON cs.dataset_id=cd.dataset_id
                    WHERE cd.campaign_id=r.id AND cd.day=ds.day AND cs.summary->'resources' ? 'trades')
                ORDER BY ds.id LIMIT 50""").fetchall()
        for row in rows:
            self.queue.enqueue(row['asset'],dict(collector='saved-analysis-v1',source_dataset=row['id'],
                source_campaign=str(row['campaign_id']),day=row['day'].isoformat()),'analysis-source/'+str(row['id']))
        self.bootstrap_at=monotonic() if len(rows)<50 else 0

    def _source(self,job):
        identifier=job['parameters']['source_dataset']
        if self.cached and self.cached[0]==identifier:return self.cached[1]
        with self.pool.connection() as c:
            data=c.execute('SELECT id,fingerprint,payload FROM research_dataset WHERE id=%s',(identifier,)).fetchone()
            campaign=c.execute('SELECT * FROM research_campaign WHERE id=%s',(UUID(job['parameters']['source_campaign']),)).fetchone()
        data=decoded_dataset(data);payload=data['payload'];manifest=self.archives.read(payload['manifest'])
        batch=batch_from_dict(manifest['batch']);tickers=[v['ticker'] for v in payload['candidates']]
        plan=plan_from_receipt(batch,payload['manifest'],campaign['config']['lookback_seconds'],('candles','trades'),selected_tickers=tickers)
        result=(campaign,plan,tickers)
        self.cached=(identifier,result)
        return result

    def run_once(self,*,deadline):
        if self.collecting():return False
        self.bootstrap()
        with self.pool.connection() as c:
            assets=[r['asset'] for r in c.execute("""SELECT DISTINCT asset FROM research_job
                WHERE idempotency_key>='analysis-source/' AND idempotency_key<'analysis-source0'
                AND status IN ('queued','running') AND attempts<max_attempts ORDER BY asset""").fetchall()]
        if not assets:return False
        if self.asset not in assets or monotonic()-self.turn_started>=60:
            self.asset=next((a for a in assets if self.asset is not None and a>self.asset),assets[0]);self.turn_started=monotonic()
        job=self.queue.claim(seconds=120,collector='saved-analysis-v1',asset=self.asset)
        if job is None:return False
        try:self.step(job,deadline)
        except CollectionInterrupted:self.queue.yield_job(job['id'],job['lease_token'],1)
        except Exception:
            self.queue.fail(job['id'],job['lease_token'],'saved_analysis_retry',delay_seconds=30)
            raise
        return True

    def step(self,job,deadline):
        campaign,plan,tickers=self._source(job)
        index=job['progress'].get('scope_index',0)
        if self.collecting():raise CollectionInterrupted('Collection preempts analysis')
        if index<len(plan.scopes):
            scope=plan.scopes[index]
            original=self.queue.get(uuid5(campaign['id'],scope.key))
            if original and original['status']=='succeeded':child=original
            else:
                child=self.queue.enqueue(job['asset'],scope.parameters(),'analysis-read/'+scope.key)
                if child['status']!='succeeded':
                    child=self.queue.claim(job_id=child['id'])
                    if child is None:
                        self.queue.yield_job(job['id'],job['lease_token'],1);return
                    # Recheck immediately before any provider work.
                    if self.collecting():
                        self.queue.yield_job(child['id'],child['lease_token']);raise CollectionInterrupted('Collection preempts analysis')
                    result=self.owner.evidence_worker.step(child,deadline=deadline)
                    if result['state'] in ('partial','throttled'):
                        self.queue.yield_job(child['id'],child['lease_token'],result['retry_after'])
                    if self.queue.get(child['id'])['status']!='succeeded':
                        self.queue.yield_job(job['id'],job['lease_token'],max(1,result['retry_after']));return
            with self.pool.connection() as c:
                self.queue._owned(c,job['id'],job['lease_token'])
                c.execute("UPDATE research_job SET progress=progress||jsonb_build_object('scope_index',%s) WHERE id=%s",(index+1,job['id']))
            self.queue.yield_job(job['id'],job['lease_token']);return
        attempts=[]
        for scope in plan.scopes:
            child=self.queue.get(uuid5(campaign['id'],scope.key))
            if child is None or child['status']!='succeeded':
                with self.pool.connection() as c:child=c.execute('SELECT * FROM research_job WHERE idempotency_key=%s',('analysis-read/'+scope.key,)).fetchone()
            attempts.append((child,self.queue.page_evidence(child['id'])))
        guard=self.owner._work_guard(job)
        def cancelled():return self.collecting() or guard()
        prepared=prepare_dataset(plan,attempts,self.archives,lambda jid:(self.queue.get(jid),self.queue.page_evidence(jid)),
            collected_tickers=tickers,cancelled=cancelled)
        if cancelled():raise CollectionInterrupted('Collection preempts analysis')
        self.queue.heartbeat(job['id'],job['lease_token'],600)
        dataset=DatasetStore(self.pool).publish('analysis-'+job['asset'],prepared)
        result=ReportStore(self.pool).publish_campaign('analysis-source-'+str(job['parameters']['source_dataset']),job['asset'],[dataset],
            publication=dict(complete=True,revision=1,reported_sections=1,total_sections=1))
        with self.pool.connection() as c:
            self.queue._owned(c,job['id'],job['lease_token'])
            c.execute("UPDATE research_job SET progress=progress||%s WHERE id=%s",(Jsonb(dict(dataset_id=dataset,result_id=result)),job['id']))
        self.queue.finish(job['id'],job['lease_token'])
        print(json.dumps(dict(event='saved_day_analysis_complete',asset=job['asset'],day=job['parameters']['day'],markets=len(tickers))),flush=True)
