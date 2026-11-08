-- Draft-only, append-only strategy definitions. No paper or live order path.
CREATE TABLE strategy_draft (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    asset text NOT NULL CHECK (asset IN ('btc','eth','crypto','weather','weather_daily','sports')),
    current_revision integer NOT NULL DEFAULT 0 CHECK (current_revision>=0),
    state text NOT NULL DEFAULT 'draft' CHECK (state='draft'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE strategy_version (
    strategy_id uuid NOT NULL REFERENCES strategy_draft(id),
    revision integer NOT NULL CHECK (revision>0),
    definition jsonb NOT NULL CHECK (jsonb_typeof(definition)='object'),
    fingerprint char(64) NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(strategy_id,revision)
);
CREATE FUNCTION guard_strategy_draft() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='INSERT' THEN
        IF NEW.current_revision<>0 OR NEW.state<>'draft' THEN
            RAISE EXCEPTION 'New strategy must start as a draft without versions';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Strategy drafts cannot be deleted'; END IF;
    IF NEW.id<>OLD.id OR NEW.name<>OLD.name OR NEW.asset<>OLD.asset
        OR NEW.state<>OLD.state OR NEW.created_at<>OLD.created_at
        OR NEW.current_revision<>OLD.current_revision+1
        OR NOT EXISTS(SELECT 1 FROM strategy_version v WHERE v.strategy_id=OLD.id
                      AND v.revision=NEW.current_revision AND v.definition->>'asset'=OLD.asset) THEN
        RAISE EXCEPTION 'Strategy draft can only advance to a saved version';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER strategy_draft_guard BEFORE INSERT OR UPDATE OR DELETE ON strategy_draft
    FOR EACH ROW EXECUTE FUNCTION guard_strategy_draft();
CREATE FUNCTION guard_strategy_version_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_asset text; parent_revision integer;
BEGIN
    SELECT asset,current_revision INTO parent_asset,parent_revision FROM strategy_draft
        WHERE id=NEW.strategy_id FOR UPDATE;
    IF parent_asset IS NULL OR NEW.revision<>parent_revision+1
        OR NEW.definition->>'asset'<>parent_asset
        OR NEW.definition->>'version'<>'draft-strategy-v1' THEN
        RAISE EXCEPTION 'Strategy version must extend its draft';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER strategy_version_insert_guard BEFORE INSERT ON strategy_version
    FOR EACH ROW EXECUTE FUNCTION guard_strategy_version_insert();
CREATE FUNCTION guard_strategy_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Strategy versions are immutable';
END $$;
CREATE TRIGGER strategy_version_immutable BEFORE UPDATE OR DELETE ON strategy_version
    FOR EACH ROW EXECUTE FUNCTION guard_strategy_version();
