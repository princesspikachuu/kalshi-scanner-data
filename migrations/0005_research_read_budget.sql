-- Shared application-side read budget. No account credentials or tier assumptions.
CREATE TABLE research_read_budget (
    name text PRIMARY KEY CHECK (length(name) BETWEEN 1 AND 64),
    refill_per_second double precision NOT NULL CHECK (refill_per_second > 0 AND refill_per_second <= 100000),
    capacity integer NOT NULL CHECK (capacity BETWEEN 1 AND 100000),
    tokens double precision NOT NULL CHECK (tokens >= 0 AND tokens <= capacity),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    blocked_until timestamptz NOT NULL DEFAULT clock_timestamp()
);
