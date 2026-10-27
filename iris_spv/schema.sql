-- Staging tables. Tokens are filled in by load.py so ONE file serves both
-- Postgres (Docker) and SQLite (local runs / tests):
--   @SCHEMA@ = iris_staging   @TS@ = timestamp type   @DATE@ = date type   @NUM@ = number type

CREATE TABLE IF NOT EXISTS @SCHEMA@.corporate_distress_records (
    record_id           TEXT PRIMARY KEY,          -- court|type|number+suffix (never the name)
    source              TEXT NOT NULL,             -- which adapter produced it
    source_url          TEXT,
    source_date         @DATE@ NOT NULL,           -- publication date at the source
    retrieved_at        @TS@ NOT NULL,             -- when we fetched it (UTC)
    run_id              TEXT NOT NULL,             -- last run that touched the row
    company_name        TEXT NOT NULL,
    company_name_norm   TEXT NOT NULL,
    legal_form          TEXT,
    register_court      TEXT NOT NULL,
    register_type       TEXT NOT NULL,             -- HRA / HRB
    register_number     TEXT NOT NULL,
    register_suffix     TEXT NOT NULL DEFAULT '',
    formation_event     TEXT NOT NULL,             -- FORMATION
    formation_date      @DATE@ NOT NULL,
    share_capital_eur   @NUM@,
    activity_text       TEXT,
    activity_terms      TEXT,                      -- JSON array of matched terms
    spv_score           @NUM@ NOT NULL,            -- hypothesis strength, 0..1
    spv_label           TEXT NOT NULL,             -- *_hypothesis / no_spv_signal
    spv_evidence        TEXT NOT NULL,             -- JSON array: which rules fired
    crosscheck_status   TEXT,                      -- set by `crosscheck`
    crosscheck_evidence TEXT,
    content_hash        TEXT NOT NULL,             -- detects real changes on re-runs
    raw_payload         TEXT NOT NULL,             -- original record, untouched
    first_seen_at       @TS@ NOT NULL,
    last_seen_at        @TS@ NOT NULL
);

CREATE TABLE IF NOT EXISTS @SCHEMA@.corporate_distress_rejects (
    reject_id   TEXT PRIMARY KEY,                  -- hash(source+reason+payload): re-runs don't duplicate
    run_id      TEXT NOT NULL,
    source      TEXT NOT NULL,
    reason      TEXT NOT NULL,                     -- machine-readable code
    detail      TEXT,
    raw_payload TEXT NOT NULL,
    rejected_at @TS@ NOT NULL
);
