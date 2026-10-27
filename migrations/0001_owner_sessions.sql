-- Draft PostgreSQL migration; not applied to any database.
-- Owner provisioning is an explicit authenticated administrative operation.
BEGIN;
CREATE TABLE owner_account (
    id smallint PRIMARY KEY CHECK (id = 1),
    google_subject text NOT NULL UNIQUE CHECK (length(google_subject) BETWEEN 1 AND 255),
    display_email text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE owner_session (
    token_hash char(64) PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    csrf_hash char(64) NOT NULL CHECK (csrf_hash ~ '^[0-9a-f]{64}$'),
    owner_id smallint NOT NULL REFERENCES owner_account(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CHECK (expires_at > created_at)
);
CREATE INDEX owner_session_expiry ON owner_session(expires_at);
COMMIT;
