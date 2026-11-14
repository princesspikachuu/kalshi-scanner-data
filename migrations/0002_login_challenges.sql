CREATE TABLE login_challenge (
    token_hash char(64) PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    csrf_hash char(64) NOT NULL CHECK (csrf_hash ~ '^[0-9a-f]{64}$'),
    nonce_hash char(64) NOT NULL CHECK (nonce_hash ~ '^[0-9a-f]{64}$'),
    expires_at timestamptz NOT NULL
);
CREATE INDEX login_challenge_expiry ON login_challenge(expires_at);
CREATE TABLE login_rate (
    key text PRIMARY KEY,
    window_start timestamptz NOT NULL,
    hits integer NOT NULL CHECK (hits > 0)
);
