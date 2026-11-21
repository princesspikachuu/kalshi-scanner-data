-- Append-only raw-evidence versions; no hosted migration runs automatically.
CREATE TABLE research_artifact (
    object_key text PRIMARY KEY,
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    provider text NOT NULL,
    content_type text NOT NULL,
    byte_length bigint NOT NULL CHECK (byte_length>=0)
);
CREATE TABLE research_dataset (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stream_key text NOT NULL CHECK (length(stream_key) BETWEEN 1 AND 128),
    fingerprint char(64) NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    day date NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
    published_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(stream_key,fingerprint)
);
CREATE INDEX research_dataset_history ON research_dataset(stream_key,id DESC);
CREATE TABLE research_summary (
    dataset_id bigint PRIMARY KEY REFERENCES research_dataset(id),
    version text NOT NULL,
    summary jsonb NOT NULL CHECK (jsonb_typeof(summary)='object')
);
CREATE TABLE research_dataset_artifact (
    dataset_id bigint NOT NULL REFERENCES research_dataset(id),
    object_key text NOT NULL REFERENCES research_artifact(object_key),
    PRIMARY KEY(dataset_id,object_key)
);
CREATE FUNCTION reject_research_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Published research history is immutable'; END;
$$;
CREATE TRIGGER research_artifact_immutable BEFORE UPDATE OR DELETE ON research_artifact
    FOR EACH ROW EXECUTE FUNCTION reject_research_history_mutation();
CREATE TRIGGER research_dataset_immutable BEFORE UPDATE OR DELETE ON research_dataset
    FOR EACH ROW EXECUTE FUNCTION reject_research_history_mutation();
CREATE TRIGGER research_summary_immutable BEFORE UPDATE OR DELETE ON research_summary
    FOR EACH ROW EXECUTE FUNCTION reject_research_history_mutation();
CREATE TRIGGER research_dataset_artifact_immutable BEFORE UPDATE OR DELETE ON research_dataset_artifact
    FOR EACH ROW EXECUTE FUNCTION reject_research_history_mutation();
