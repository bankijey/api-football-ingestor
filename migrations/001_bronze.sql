-- Bronze layer + ops tables. Append-only by convention; UPDATE/DELETE not
-- permitted by application code. All raw payloads live in `payload` JSONB.

-- ============================================================================
-- Bronze: raw API responses, one row per ingestion.
-- ============================================================================

CREATE TABLE IF NOT EXISTS bronze_leagues (
    id              BIGSERIAL PRIMARY KEY,
    run_id          UUID        NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    endpoint        TEXT        NOT NULL,
    request_params  JSONB       NOT NULL,
    response_hash   TEXT        NOT NULL,
    api_version     TEXT,
    payload         JSONB       NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bronze_leagues_ingested_at
    ON bronze_leagues (ingested_at DESC);

CREATE TABLE IF NOT EXISTS bronze_fixtures (
    id              BIGSERIAL PRIMARY KEY,
    run_id          UUID        NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    endpoint        TEXT        NOT NULL,
    request_params  JSONB       NOT NULL,
    response_hash   TEXT        NOT NULL,
    api_version     TEXT,
    payload         JSONB       NOT NULL,
    league_id       INTEGER     NOT NULL,
    season          INTEGER     NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bronze_fixtures_league_season_ingested
    ON bronze_fixtures (league_id, season, ingested_at DESC);

CREATE TABLE IF NOT EXISTS bronze_fixture_details (
    id              BIGSERIAL PRIMARY KEY,
    run_id          UUID        NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    endpoint        TEXT        NOT NULL,
    request_params  JSONB       NOT NULL,
    response_hash   TEXT        NOT NULL,
    api_version     TEXT,
    payload         JSONB       NOT NULL,
    fixture_id      BIGINT      NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bronze_fixture_details_fixture_ingested
    ON bronze_fixture_details (fixture_id, ingested_at DESC);

CREATE TABLE IF NOT EXISTS bronze_halftime_stats (
    id              BIGSERIAL PRIMARY KEY,
    run_id          UUID        NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    endpoint        TEXT        NOT NULL,
    request_params  JSONB       NOT NULL,
    response_hash   TEXT        NOT NULL,
    api_version     TEXT,
    payload         JSONB       NOT NULL,
    fixture_id      BIGINT      NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bronze_halftime_stats_fixture_ingested
    ON bronze_halftime_stats (fixture_id, ingested_at DESC);

-- ============================================================================
-- Companion: hash dedup. One row per (endpoint, params_hash).
-- last_checked_at always updates; last_response_hash / last_changed_at only
-- update when the hash actually changes.
-- ============================================================================

CREATE TABLE IF NOT EXISTS bronze_latest_hash (
    endpoint            TEXT        NOT NULL,
    params_hash         TEXT        NOT NULL,
    request_params      JSONB       NOT NULL,
    last_response_hash  TEXT        NOT NULL,
    last_run_id         UUID        NOT NULL,
    last_checked_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_changed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (endpoint, params_hash)
);

-- ============================================================================
-- Ops: ingestion_runs, checkpoints, dead_letter.
-- ============================================================================

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id            UUID        PRIMARY KEY,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    status            TEXT        NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running', 'succeeded', 'partial', 'failed')),
    args              JSONB       NOT NULL DEFAULT '{}'::jsonb,
    last_heartbeat_at TIMESTAMPTZ,
    counters          JSONB       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_ingestion_runs_started_at
    ON ingestion_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS ingestion_checkpoints (
    run_id      UUID        NOT NULL,
    scope       TEXT        NOT NULL,    -- 'league' | 'fixture'
    key         TEXT        NOT NULL,    -- e.g. '39:2025' or fixture id as text
    endpoint    TEXT        NOT NULL,
    status      TEXT        NOT NULL,    -- 'pending' | 'succeeded' | 'failed'
    attempts    INTEGER     NOT NULL DEFAULT 0,
    last_error  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, scope, key, endpoint)
);
CREATE INDEX IF NOT EXISTS ix_checkpoints_run_status
    ON ingestion_checkpoints (run_id, status);

CREATE TABLE IF NOT EXISTS dead_letter (
    id              BIGSERIAL PRIMARY KEY,
    run_id          UUID,
    endpoint        TEXT        NOT NULL,
    request_params  JSONB       NOT NULL,
    error_class     TEXT        NOT NULL,
    error_message   TEXT        NOT NULL,
    http_status     INTEGER,
    attempts        INTEGER     NOT NULL DEFAULT 1,
    failed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_dead_letter_failed_at
    ON dead_letter (failed_at DESC);
