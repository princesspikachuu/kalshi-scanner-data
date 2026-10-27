"""Bounded precomputed reads only. Never import collectors or report builders here."""


class HistoryStore:
    def __init__(self,pool): self.pool=pool

    def datasets(self,stream,*,before=None,limit=26):
        boundary='AND d.id<%s' if before is not None else ''
        args=(stream,before,limit) if before is not None else (stream,limit)
        with self.pool.connection() as c:
            return c.execute(f'''SELECT d.id::text AS id,d.fingerprint,d.day::text AS day,
                d.published_at,s.version,s.summary FROM research_dataset d
                JOIN research_summary s ON s.dataset_id=d.id WHERE d.stream_key=%s {boundary}
                ORDER BY d.id DESC LIMIT %s''',args).fetchall()

    def results(self,stream,*,before=None,limit=26):
        boundary='AND id<%s' if before is not None else ''
        args=(stream,before,limit) if before is not None else (stream,limit)
        with self.pool.connection() as c:
            return c.execute(f'''SELECT id::text AS id,fingerprint,published_at,model_version,asset,
                report->'latest_membership_known' AS latest_membership_known,
                jsonb_array_length(report->'datasets') AS dataset_count,
                {self._summary('historical')} AS historical,{self._summary('latest')} AS latest
                FROM research_result WHERE stream_key=%s {boundary} ORDER BY research_result.id DESC LIMIT %s''',args).fetchall()

    @staticmethod
    def _summary(view):
        # view is an internal literal, never user SQL. No policy computation or observation scan.
        return f'''jsonb_build_object('candidate_count',report->'{view}'->'candidate_count',
            'observation_count',report->'{view}'->'observation_count',
            'first_date',report->'{view}'->'first_date','last_date',report->'{view}'->'last_date')'''

    def result(self,stream,identifier,*,view):
        if view not in ('historical','latest'):raise ValueError('Invalid view')
        with self.pool.connection() as c:
            return c.execute(f'''SELECT id::text AS id,fingerprint,published_at,model_version,asset,
                report->'latest_membership_known' AS latest_membership_known,
                report->'source_commit' AS source_commit,report->'entry_minutes' AS entry_minutes,
                report->'price_bands' AS price_bands,report->'execution_included' AS execution_included,
                report->'baseline_fees_cents' AS baseline_fees_cents,
                report->'exit_cost_stress_cents' AS exit_cost_stress_cents,
                {self._summary(view)} AS summary,
                CASE WHEN octet_length((report->%s->'cells')::text)<=131072
                     THEN report->%s->'cells' ELSE NULL END AS cells
                FROM research_result WHERE stream_key=%s AND id=%s''',(view,view,stream,identifier)).fetchone()

    def members(self,stream,identifier,*,before=None,limit=26):
        # Parent existence is separate so an unknown report cannot masquerade as an empty cohort.
        boundary='AND m.dataset_id<%s' if before is not None else ''
        args=(identifier,before,limit) if before is not None else (identifier,limit)
        with self.pool.connection() as c:
            if not c.execute('SELECT id FROM research_result WHERE stream_key=%s AND id=%s',(stream,identifier)).fetchone():return None
            return c.execute(f'''SELECT d.id::text AS id,d.fingerprint,d.day::text AS day,m.is_latest
                FROM research_result_dataset m JOIN research_dataset d ON d.id=m.dataset_id
                WHERE m.result_id=%s {boundary} ORDER BY m.dataset_id DESC LIMIT %s''',args).fetchall()
