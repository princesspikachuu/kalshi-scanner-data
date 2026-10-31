"""One-time, resumable model upgrades from frozen saved evidence; no provider I/O."""
import json
from .queue import ResearchQueue,EvidenceConflict
from .reports import MODEL,ReportStore,PreparedReport,prepare_report_stream,report_fingerprint,MAX_REPORT_BYTES
from .datasets import CollectionInterrupted
from . import report_jobs

COLLECTOR='report-window-upgrade-v2'
class WindowRebuild:
    def __init__(self,pool,cancelled):self.pool,self.cancelled=pool,cancelled;self.queue=ResearchQueue(pool);self.bootstrapped=False
    def run_once(self):
        if not self.bootstrapped:
            with self.pool.connection() as c:
                c.execute("""INSERT INTO research_job(id,idempotency_key,asset,parameters,max_attempts)
                    SELECT gen_random_uuid(),%s||id::text,asset,
                        jsonb_build_object('collector',%s::text,'result_id',id,'stream_key',stream_key),3
                    FROM (SELECT DISTINCT ON(stream_key) id,asset,stream_key,model_version
                        FROM research_result ORDER BY stream_key,id DESC) latest
                    WHERE model_version='research-return-conditional-v1'
                    ON CONFLICT(idempotency_key) DO NOTHING""",(COLLECTOR+'/',COLLECTOR))
            self.bootstrapped=True
        job=self.queue.claim(seconds=600,collector=COLLECTOR)
        if not job:return False
        try:
            with report_jobs.background_guard(self.cancelled):self.step(job)
            self.queue.finish(job['id'],job['lease_token'])
        except CollectionInterrupted:self.queue.yield_job(job['id'],job['lease_token'],1)
        except Exception:
            self.queue.fail(job['id'],job['lease_token'],'window_report_rebuild_failed',delay_seconds=30)
            raise
        return True
    def step(self,job):
        source_id=job['parameters']['result_id'];stream=job['parameters']['stream_key']
        with self.pool.connection() as c:
            source=c.execute('SELECT report,asset FROM research_result WHERE id=%s AND stream_key=%s',(source_id,stream)).fetchone()
            current=c.execute('SELECT id,model_version FROM research_result WHERE stream_key=%s ORDER BY id DESC LIMIT 1',(stream,)).fetchone()
        if current['id']!=source_id:return
        old=source['report'];ids=sorted(d['id'] for d in old['datasets'])
        def inputs():
            for identifier in ids:
                report_jobs.check_priority()
                with self.pool.connection() as c:
                    row=c.execute('SELECT id,fingerprint,payload,COALESCE((payload->>'uncompressed_bytes')::bigint,octet_length(payload::text)) AS bytes FROM research_dataset WHERE id=%s',(identifier,)).fetchone()
                if not row or row['bytes']>64*1024*1024:raise EvidenceConflict('Window rebuild source missing or exceeds memory limit')
                yield row
        if 'selection' in old:
            from .cumulative import prepare_category
            prepared=prepare_category(source['asset'],inputs(),old['selection']['windows'],old['selection']['revision'],publication_complete=old.get('publication',{}).get('complete',True))
        else:
            latest=[d['id'] for d in old['datasets'] if d.get('latest')] if old['latest_membership_known'] else None
            prepared=prepare_report_stream(source['asset'],inputs(),latest_ids=latest)
        payload=json.loads(prepared.payload_json)
        if 'publication' in old:payload['publication']=old['publication']
        encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False)
        if len(encoded)+len(prepared.observations_json)>MAX_REPORT_BYTES:raise ValueError('Rebuilt report exceeds memory limit')
        prepared=PreparedReport(encoded,report_fingerprint(encoded,prepared.observations_json),prepared.observations_json)
        self.queue.heartbeat(job['id'],job['lease_token'],600)
        result=ReportStore(self.pool)._save(stream,source['asset'],prepared,expected_result_id=source_id)
        print(json.dumps(dict(event='research_time_windows_rebuilt',asset=source['asset'],model=MODEL,result_id=result,source_result_id=source_id)),flush=True)
