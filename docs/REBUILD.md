# Rebuilding from Bronze

Bronze is the source of truth — every row is the raw API response as it landed,
with `run_id`, `ingested_at`, `request_params`, `response_hash`, and the full
`payload` JSONB. Anything downstream (silver, gold) is derivable from these
tables; if they ever get corrupted you delete them and re-derive.

This doc covers two scenarios. Silver/gold rebuild is documented here for
completeness but is **not yet implemented** — Phase 1 is bronze-only.

---

## 1. Re-deriving silver/gold from bronze (future)

When silver lands:

```sql
TRUNCATE silver_fixtures, silver_lineups, silver_events,
         silver_player_stats, silver_fixture_stats
RESTART IDENTITY CASCADE;
```

Then run the silver pipeline against bronze (no API calls — bronze is enough).

Because bronze rows are append-only with `ingested_at` timestamps, you can also
do **point-in-time rebuilds**: filter bronze rows to `ingested_at <= T` and
materialise silver as of `T`.

---

## 2. Backfilling missing bronze rows

If you discover bronze is missing data for a league / season / fixture range,
just run the ingestor again with the right flags. The hash-skip dedup means
unchanged data won't bloat the tables; only genuinely-new payloads land as new
rows.

```bash
# Backfill specific leagues for a season
make ingest ARGS="--leagues 39,140,61 --season 2025"

# Widen the Phase B lookback window for a one-off run
make ingest ARGS="--lookback-days 60"

# Re-attempt a partially-failed run (skips already-succeeded tasks)
make ingest ARGS="--resume <run_id>"
```

`--resume` is the right tool when you want to retry only the failures from a
previous run. Without `--resume`, a fresh `run_id` is allocated and the
ingestor re-walks everything (still cheap thanks to hash dedup).

---

## 3. Hard reset (nuclear option)

If you want to start the bronze layer over entirely:

```bash
make clean   # drops the postgres volume — destroys ALL data
make up
make migrate
make ingest
```

This is occasionally useful in dev. Don't do it in prod — bronze is meant to
be your immutable archive.

---

## 4. Inspecting what's in bronze

Drop into `psql` and look around:

```bash
make psql
```

Useful queries:

```sql
-- Latest run summary
SELECT run_id, status, started_at, finished_at, counters
  FROM ingestion_runs
 ORDER BY started_at DESC LIMIT 5;

-- Recent failures
SELECT failed_at, endpoint, error_class, error_message, http_status
  FROM dead_letter
 ORDER BY failed_at DESC LIMIT 20;

-- How many distinct fixtures have rich detail rows?
SELECT count(DISTINCT fixture_id) FROM bronze_fixture_details;

-- Which leagues/seasons have we seen Phase A data for?
SELECT league_id, season, max(ingested_at) AS last_seen, count(*) AS versions
  FROM bronze_fixtures
 GROUP BY 1, 2 ORDER BY 1, 2;

-- Has anything changed lately? (hash drift)
SELECT endpoint, count(*) FILTER (WHERE last_changed_at > now() - interval '1 day') AS changed_today,
       count(*) AS total
  FROM bronze_latest_hash GROUP BY endpoint;
```

---

## 5. Append-only invariant

The bronze writer never issues `UPDATE` or `DELETE` against `bronze_*` tables.
The only mutating table is `bronze_latest_hash` (a companion, not bronze data),
which tracks `(endpoint, params_hash) → latest_response_hash`. If you need to
audit this, run:

```sql
SELECT relname, schemaname FROM pg_stat_user_tables
 WHERE relname LIKE 'bronze_%';
```

…and verify no triggers / rules / views are mutating those tables. None ship
with this project.
