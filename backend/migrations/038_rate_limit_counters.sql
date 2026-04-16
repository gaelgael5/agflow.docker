-- 038_rate_limit_counters.sql
CREATE TABLE IF NOT EXISTS rate_limit_counters (
    key          TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL DEFAULT date_trunc('minute', now()),
    count        INT NOT NULL DEFAULT 1,
    PRIMARY KEY (key, window_start)
);
