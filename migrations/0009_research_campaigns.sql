-- Undeployed date-range orchestration. Existing immutable evidence is retained.
CREATE TABLE research_campaign (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL UNIQUE REFERENCES research_job(id),
    asset text NOT NULL,
    mode text NOT NULL CHECK (mode IN ('backfill','rolling')),
    start_at timestamptz NOT NULL,
    end_at timestamptz NOT NULL CHECK (end_at>start_at),
    config jsonb NOT NULL,
    config_hash char(64) NOT NULL,
    request_key text NOT NULL UNIQUE,
    request_spec jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TRIGGER research_campaign_immutable BEFORE UPDATE OR DELETE ON research_campaign
    FOR EACH ROW EXECUTE FUNCTION reject_research_history_mutation();
CREATE TABLE research_campaign_day (
    campaign_id uuid NOT NULL REFERENCES research_campaign(id),
    day date NOT NULL,
    start_at timestamptz NOT NULL,
    end_at timestamptz NOT NULL CHECK (end_at>start_at),
    manifest jsonb,
    evidence_planned boolean NOT NULL DEFAULT false,
    dataset_id bigint REFERENCES research_dataset(id),
    PRIMARY KEY(campaign_id,day)
);
CREATE INDEX research_campaign_reuse ON research_campaign_day(start_at,end_at) WHERE dataset_id IS NOT NULL;
CREATE TABLE research_campaign_work (
    campaign_id uuid NOT NULL,
    day date NOT NULL,
    phase text NOT NULL CHECK (phase IN ('inventory','evidence')),
    job_id uuid NOT NULL REFERENCES research_job(id),
    PRIMARY KEY(campaign_id,day,phase,job_id),
    FOREIGN KEY(campaign_id,day) REFERENCES research_campaign_day(campaign_id,day)
);
CREATE TABLE research_refresh (
    asset text PRIMARY KEY,
    enabled boolean NOT NULL DEFAULT false,
    next_due timestamptz NOT NULL DEFAULT clock_timestamp(),
    interval_seconds integer NOT NULL DEFAULT 3600 CHECK (interval_seconds=3600)
);
-- Completed membership and manifests cannot be revised or removed through DML.
CREATE FUNCTION guard_campaign_day() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' OR NEW.campaign_id<>OLD.campaign_id OR NEW.day<>OLD.day
        OR NEW.start_at<>OLD.start_at OR NEW.end_at<>OLD.end_at
        OR (OLD.manifest IS NOT NULL AND NEW.manifest IS DISTINCT FROM OLD.manifest)
        OR (OLD.dataset_id IS NOT NULL AND NEW.dataset_id IS DISTINCT FROM OLD.dataset_id) THEN
        RAISE EXCEPTION 'campaign evidence is immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER research_campaign_day_guard BEFORE UPDATE OR DELETE ON research_campaign_day
    FOR EACH ROW EXECUTE FUNCTION guard_campaign_day();
CREATE TRIGGER research_campaign_work_immutable BEFORE UPDATE OR DELETE ON research_campaign_work
    FOR EACH ROW EXECUTE FUNCTION reject_research_history_mutation();

CREATE TABLE research_campaign_result (
    campaign_id uuid PRIMARY KEY REFERENCES research_campaign(id),
    result_id bigint NOT NULL REFERENCES research_result(id)
);
CREATE TRIGGER research_campaign_result_immutable BEFORE UPDATE OR DELETE ON research_campaign_result
    FOR EACH ROW EXECUTE FUNCTION reject_research_history_mutation();
