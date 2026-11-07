-- Durable collection jobs and immutable raw-archive references for the next phase.
CREATE TABLE research_job (
    id uuid PRIMARY KEY,
    idempotency_key text NOT NULL UNIQUE,
    asset text NOT NULL CHECK (asset IN ('weather','btc','eth','crypto','sports','weather_daily','financial_daily')),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    parameters jsonb NOT NULL CHECK (jsonb_typeof(parameters)='object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    lease_expires_at timestamptz,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts>=0),
    progress jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code text
);
CREATE INDEX research_job_queue ON research_job(status,created_at);
CREATE TABLE raw_archive (
    object_key text PRIMARY KEY,
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    provider text NOT NULL,
    job_id uuid REFERENCES research_job(id),
    content_type text NOT NULL,
    byte_length bigint NOT NULL CHECK (byte_length>=0),
    received_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE ingestion_cursor (
    provider text NOT NULL,
    series_id text NOT NULL,
    last_complete_through timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(provider,series_id)
);
