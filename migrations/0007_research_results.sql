CREATE TABLE research_result (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stream_key text NOT NULL CHECK (length(stream_key) BETWEEN 1 AND 128),
    model_version text NOT NULL,
    fingerprint char(64) NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    asset text NOT NULL,
    report jsonb NOT NULL CHECK (jsonb_typeof(report)='object'),
    published_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(stream_key,fingerprint)
);
CREATE INDEX research_result_history ON research_result(stream_key,id DESC);
CREATE TABLE research_result_dataset (
    result_id bigint NOT NULL REFERENCES research_result(id),
    dataset_id bigint NOT NULL REFERENCES research_dataset(id),
    is_latest boolean NOT NULL,
    PRIMARY KEY(result_id,dataset_id)
);
CREATE TABLE research_observation (
    result_id bigint NOT NULL REFERENCES research_result(id),
    day date NOT NULL,
    ticker text NOT NULL,
    minute integer NOT NULL CHECK (minute BETWEEN 1 AND 1440),
    observation jsonb NOT NULL,
    PRIMARY KEY(result_id,day,ticker,minute)
);
CREATE TRIGGER research_result_immutable BEFORE UPDATE OR DELETE ON research_result
    FOR EACH ROW EXECUTE FUNCTION reject_research_history_mutation();
CREATE TRIGGER research_result_dataset_immutable BEFORE UPDATE OR DELETE ON research_result_dataset
    FOR EACH ROW EXECUTE FUNCTION reject_research_history_mutation();
CREATE TRIGGER research_observation_immutable BEFORE UPDATE OR DELETE ON research_observation
    FOR EACH ROW EXECUTE FUNCTION reject_research_history_mutation();
