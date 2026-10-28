-- Operator-only performance maintenance, outside a transaction (autocommit).
-- These indexes change access paths only: no data, grants or service tiers.
-- Apply once via a private operator connection, then inspect pg_index.indisvalid.
-- If a same-named index is invalid, inspect it before retrying this script.
CREATE INDEX CONCURRENTLY IF NOT EXISTS research_job_ready_collector
    ON research_job ((parameters->>'collector'),available_at,created_at,id)
    WHERE status='queued';
CREATE INDEX CONCURRENTLY IF NOT EXISTS research_job_expired_collector
    ON research_job ((parameters->>'collector'),lease_expires_at,available_at,created_at,id)
    WHERE status='running';
CREATE INDEX CONCURRENTLY IF NOT EXISTS research_campaign_work_job
    ON research_campaign_work(job_id);
ANALYZE research_job;
ANALYZE research_campaign_work;
