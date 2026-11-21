"""Durable, separate sampled research previews during exhaustive collection.

Only the campaign's explicit sample_previews dataset IDs enter this stream.
Neither full campaign publication nor cumulative category reports read it.
"""
import json
from datetime import date
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from . import report_jobs
from .datasets import CollectionInterrupted
from .queue import EvidenceConflict, ResearchQueue
from .reports import ReportStore

COLLECTOR = 'campaign-sample-report-v1'
SAMPLE_LIMIT = 100


def sample_snapshot(previews, days, datasets, stream):
    """Validate frozen sample membership and its dedicated dataset stream."""
    if not isinstance(previews, dict) or not isinstance(days, (list, tuple)) or not isinstance(datasets, (list, tuple)):
        raise EvidenceConflict('Invalid sampled preview membership')
    allowed = {d.isoformat() if isinstance(d, date) else d for d in days}
    if not allowed or len(allowed) != len(days) or len(allowed) > 3660 or not previews or not set(previews).issubset(allowed):
        raise EvidenceConflict('Invalid sampled preview dates')
    if any(type(identifier) is not int or identifier < 1 for identifier in previews.values()):
        raise EvidenceConflict('Invalid sampled preview dataset ID')
    ids = set(previews.values())
    if len(ids) != len(previews) or len(datasets) != len(ids):
        raise EvidenceConflict('Sampled preview dataset membership mismatch')
    seen = set()
    for item in datasets:
        key = item['day'].isoformat() if isinstance(item['day'], date) else item['day']
        if (item['id'] not in ids or key not in previews or previews[key] != item['id']
                or item['stream_key'] != stream or item['id'] in seen):
            raise EvidenceConflict('Foreign sampled preview dataset')
        seen.add(item['id'])
    limits=[d.get('preview_limit',SAMPLE_LIMIT) for d in datasets]
    if any(n not in (100,300) for n in limits):raise EvidenceConflict('Invalid preview limit')
    revision = max(ids)  # Immutable identity IDs increase when another day is published.
    return dict(ids=sorted(ids), publication=dict(complete=False, sampled_preview=True,
        sample_limit=max(limits), reported_sections=len(previews), total_sections=len(days), revision=revision))


class SampleReports:
    def __init__(self, pool):
        self.pool = pool
        self.queue = ResearchQueue(pool)

    @staticmethod
    def enqueue(c, identifier, asset):
        identifier = UUID(str(identifier))
        row = c.execute('''SELECT r.asset,j.progress,
            (SELECT count(*) FROM research_campaign_day d WHERE d.campaign_id=r.id) AS total_sections
            FROM research_campaign r JOIN research_job j ON j.id=r.job_id WHERE r.id=%s''', (identifier,)).fetchone()
        if row is None or row['asset'] != asset:
            raise EvidenceConflict('Unknown sampled preview campaign')
        mapping = row['progress'].get('sample_previews', {})
        if not mapping:
            return
        if (not isinstance(mapping, dict) or len(mapping) > row['total_sections']
                or any(type(value) is not int or value < 1 for value in mapping.values())):
            raise EvidenceConflict('Invalid sampled preview progress')
        revision = max(mapping.values())
        c.execute('''INSERT INTO research_job(id,idempotency_key,asset,parameters,max_attempts)
            VALUES(%s,%s,%s,%s,5) ON CONFLICT(idempotency_key) DO NOTHING''',
            (uuid4(), f'sample-progress/{identifier}/{revision}', asset,
             Jsonb(dict(collector=COLLECTOR, campaign_id=str(identifier), revision=revision))))

    def bootstrap(self):
        with self.pool.connection() as c:
            rows = c.execute('''SELECT r.id,r.asset FROM research_campaign r JOIN research_job j ON j.id=r.job_id
                WHERE j.status IN ('queued','running') AND j.progress ? 'sample_previews'
                ORDER BY r.created_at LIMIT 100''').fetchall()
            for row in rows:
                self.enqueue(c, row['id'], row['asset'])

    def step(self, job):
        identifier = UUID(job['parameters']['campaign_id'])
        stream = 'campaign-sample-' + identifier.hex
        if report_jobs.defer_unfrozen(self.queue, job, stream, 'snapshot'):
            return
        with self.pool.connection() as c:
            owned = self.queue._owned(c, job['id'], job['lease_token'])
            snapshot = owned['progress'].get('snapshot')
            if snapshot is None:
                campaign = c.execute('''SELECT r.asset,j.progress FROM research_campaign r
                    JOIN research_job j ON j.id=r.job_id WHERE r.id=%s''', (identifier,)).fetchone()
                if campaign is None or campaign['asset'] != job['asset']:
                    raise EvidenceConflict('Wrong sampled preview campaign')
                days = [r['day'] for r in c.execute('''SELECT day FROM research_campaign_day
                    WHERE campaign_id=%s ORDER BY day''', (identifier,)).fetchall()]
                previews = campaign['progress'].get('sample_previews', {})
                ids = list(previews.values()) if isinstance(previews, dict) else []
                datasets = c.execute('''SELECT d.id,d.day,d.stream_key,COALESCE(CASE WHEN (s.summary->>'candidate_count')::integer<=100 THEN 100 ELSE (s.summary->>'candidate_count')::integer END,100) AS preview_limit
                    FROM research_dataset d LEFT JOIN research_summary s ON s.dataset_id=d.id
                    WHERE d.id=ANY(%s::bigint[])''', (ids,)).fetchall()
                snapshot = sample_snapshot(previews, days, datasets, stream)
                if snapshot['publication']['revision'] < job['parameters']['revision']:
                    raise EvidenceConflict('Sampled preview revision regressed')
                c.execute('UPDATE research_job SET progress=%s WHERE id=%s',
                          (Jsonb(dict(snapshot=snapshot)), job['id']))
        ReportStore(self.pool).publish_campaign(stream, job['asset'], snapshot['ids'],
                                                publication=snapshot['publication'])
        with self.pool.connection() as c:
            self.queue._owned(c, job['id'], job['lease_token'])
            report_jobs.coalesce(c, job, snapshot['publication']['revision'], campaign=True)
        self.queue.finish(job['id'], job['lease_token'])
        print(json.dumps(dict(event='sample_days_published',asset=job['asset'],
            days=snapshot['publication']['reported_sections'],sample_limit=snapshot['publication']['sample_limit'])),flush=True)

    def run_once(self,*,campaign_id=None,asset=None):
        job = self.queue.claim(seconds=600, collector=COLLECTOR,campaign_id=campaign_id,asset=asset)
        if job is None:
            return False
        try:
            self.step(job)
        except CollectionInterrupted:
            self.queue.yield_job(job['id'],job['lease_token'],1)
        except ValueError:
            self.queue.fail(job['id'], job['lease_token'], 'sample_report_blocked', retry=False)
        return True
