-- Worker lease tokens fence obsolete processes after retries/cancellation.
ALTER TABLE research_job ADD COLUMN lease_token uuid;
ALTER TABLE research_job ADD COLUMN available_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE research_job ADD COLUMN max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 20);
ALTER TABLE research_job ADD CONSTRAINT research_job_lease CHECK (
    (status='running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
    OR (status<>'running' AND lease_token IS NULL AND lease_expires_at IS NULL)
);
CREATE INDEX research_job_available ON research_job(available_at,created_at,id) WHERE status='queued';
CREATE INDEX research_job_expired ON research_job(lease_expires_at) WHERE status='running';
-- Commit page evidence and its restart cursor together. Never store provider tokens here.
CREATE TABLE collection_page (
    job_id uuid NOT NULL REFERENCES research_job(id),
    page_key text NOT NULL CHECK (length(page_key) BETWEEN 1 AND 256),
    object_key text NOT NULL REFERENCES raw_archive(object_key),
    checkpoint jsonb NOT NULL CHECK (jsonb_typeof(checkpoint)='object'),
    completed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(job_id,page_key)
);
