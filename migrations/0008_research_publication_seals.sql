-- Child membership/observations may only be inserted with their parent version.
-- Existing versions acquire this migration's xid and are sealed on commit.
ALTER TABLE research_dataset ADD COLUMN publication_xid xid8 NOT NULL DEFAULT pg_current_xact_id();
ALTER TABLE research_result ADD COLUMN publication_xid xid8 NOT NULL DEFAULT pg_current_xact_id();
CREATE FUNCTION guard_research_publication_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_xid xid8;
BEGIN
    IF TG_TABLE_NAME IN ('research_summary','research_dataset_artifact') THEN
        SELECT publication_xid INTO parent_xid FROM research_dataset WHERE id=NEW.dataset_id;
    ELSE
        SELECT publication_xid INTO parent_xid FROM research_result WHERE id=NEW.result_id;
    END IF;
    IF parent_xid IS NULL OR parent_xid<>pg_current_xact_id() THEN
        RAISE EXCEPTION 'Published research version is sealed against later inserts';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER research_summary_sealed BEFORE INSERT ON research_summary
    FOR EACH ROW EXECUTE FUNCTION guard_research_publication_insert();
CREATE TRIGGER research_dataset_artifact_sealed BEFORE INSERT ON research_dataset_artifact
    FOR EACH ROW EXECUTE FUNCTION guard_research_publication_insert();
CREATE TRIGGER research_result_dataset_sealed BEFORE INSERT ON research_result_dataset
    FOR EACH ROW EXECUTE FUNCTION guard_research_publication_insert();
CREATE TRIGGER research_observation_sealed BEFORE INSERT ON research_observation
    FOR EACH ROW EXECUTE FUNCTION guard_research_publication_insert();
