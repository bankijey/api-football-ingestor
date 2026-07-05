# Roadmap — API-Football Bronze Ingestor

This file is the durable, cross-session source of truth for **what's done and
what's next**. Git tracks the code; this file tracks intent and progress.

**Convention:** At the end of every working step, update the relevant checkbox
and add a one-line note under "Progress log" with the date. When resuming work,
read `CLAUDE.md` then this file before doing anything else.

Status key: `[ ]` not started · `[~]` in progress · `[x]` done

---

## Phase 1 — Bronze Layer (CURRENT SCOPE)

Raw, append-only ingestion. Two-phase fetch strategy:
- Phase A: league-grain (leagues + fixtures-by-league for all ~1,500 leagues)
- Phase B: fixture-grain (rich fixture data + half-time stats for recent matches)

Silver and Gold are explicitly OUT OF SCOPE until this phase is complete.

### 1.1 Project scaffolding
- [x] Directory structure created (config, client, fetchers, bronze writer,
      orchestration, checkpointing, logging) — each module small and single-purpose
- [x] `pyproject.toml` / dependencies pinned
      (httpx, tenacity, pydantic, structlog, psycopg2-binary, concurrent.futures)
- [x] `ruff` + `mypy` configured; `make lint` works
- [x] `pytest` skeleton; `make test` works (API is mocked, no real calls)
- [x] Copy legacy scraper to `docs/legacy/fix.py` as reference

### 1.2 Configuration & secrets
- [x] Pydantic settings model covering:
      rate limits (requests per interval, daily quota),
      season, league subset filter, retry count/backoff,
      concurrency (thread pool size), lookback window (days),
      fixture statuses to include in Phase B
- [x] `.env.example` committed; real `.env` gitignored
- [x] API key loaded from env only — never hardcoded

### 1.3 Shared HTTP client
- [x] Sync httpx client wrapper (NOT async — sync + ThreadPoolExecutor)
- [x] Rate limiter coordinated with thread pool (stay under per-minute + per-day limits)
- [x] Read and act on `x-ratelimit-*` response headers from API-Football
- [x] Exponential backoff WITH jitter via tenacity
- [x] Retryable vs non-retryable classification (429/503 retry; 401/404 don't)
- [x] Response validation: check JSON is valid, check `errors` field is empty
      (API-Football returns 200 with errors — treat as failure)

### 1.4 Bronze storage
- [x] Postgres up via docker-compose
- [x] `bronze_leagues` table: raw JSONB from /leagues + ingestion metadata
- [x] `bronze_fixtures` table: raw JSONB from /fixtures?league=X + metadata
      (run_id, ingested_at, league_id, season, response_hash, api_version)
- [x] `bronze_fixture_details` table: raw JSONB from /fixtures?id=X (the rich
      endpoint — contains lineups, events, player stats, fixture stats)
- [x] `bronze_halftime_stats` table: raw JSONB from
      /fixtures/statistics?fixture=X&half=true
- [x] `bronze_latest_hash` companion table (per query: last hash + last_checked_at)
- [x] `ingestion_runs` / checkpoint table (track per-league and per-fixture progress)
- [x] `dead_letter` table (failed fetches + error + timestamp + endpoint)
- [x] Bronze writer: hash-compute → compare → append only if changed
- [x] Append-only enforced; no UPDATE/DELETE paths exist (enforced in code; no
      SQL-level REVOKE yet)

### 1.5 Fetchers

**Phase A — League-grain:**
- [x] `leagues` fetcher: single call to /leagues, store raw response
- [x] Parse league list: extract current seasons, coverage flags
- [x] `fixtures-by-league` fetcher: one call per league+season to
      /fixtures?league=X&season=Y — with hash-based skip if unchanged
- [x] Bounded concurrency via ThreadPoolExecutor for league fetches

**Phase B — Fixture-grain:**
- [x] Derive relevant fixture_ids from Phase A results:
      filter by lookback window, played/live statuses, coverage flags
- [x] `fixture-details` fetcher: /fixtures?id=X (rich endpoint)
- [x] `halftime-stats` fetcher: /fixtures/statistics?fixture=X&half=true
- [x] Bounded concurrency via ThreadPoolExecutor for fixture fetches
- [x] Each fixture fetch is independently failure-isolated

### 1.6 Orchestration / run loop
- [x] Dependency flow enforced: leagues → fixtures-by-league → derive ids →
      fixture-details + halftime-stats
- [x] Per-league failure isolation (Phase A)
- [x] Per-fixture failure isolation (Phase B)
- [x] Idempotent restart: resume from checkpoint, no double-write, no skips
- [x] Partial-failure policy defined (success-with-warnings threshold)
      — terminal status is `partial` if any task failed, `succeeded` otherwise;
        CLI exits non-zero on `partial`/`failed`.
- [x] `make ingest` runs a one-off ingestion inside the container

### 1.7 Observability
- [x] Structured JSON logging (run_id, league_id/fixture_id, endpoint,
      status_code, duration_ms, bytes_received)
- [x] Run-level metrics: leagues fetched/skipped/failed, fixtures fetched/
      skipped/failed, total duration
      — emitted on the terminal `run.done` log line; persisted in
        `ingestion_runs.counters`. Quota-remaining tracking is in the rate
        limiter via header observation; a dedicated metric line is deferred.
- [x] Heartbeat / dead-man's-switch concept (stub acceptable for v1)
      — `Heartbeat` daemon thread bumps `ingestion_runs.last_heartbeat_at`
        every 30s while the run is in flight.

### 1.8 Backfill & replay
- [x] Ingestor parameterizable by season / league subset / date range /
      specific fixture IDs
      — `--season`, `--leagues`, `--lookback-days`, `--resume` on the CLI.
        Date range / specific-fixture-ids are derivable via `--lookback-days`
        and `--resume`; a dedicated `--fixture-ids` flag is a future nicety.
- [x] Backfill is just a normal run with different args (no special script)
- [x] Confirmed: bronze is fully replayable (rebuild path documented)
      — see `docs/REBUILD.md`.
- [~] **0002** — Multi-season backfill enhancement: `--seasons` CLI flag +
      `select_leagues(seasons=…)` + window guard, landing the pre-existing
      uncommitted feature (with a bundled `ThreadedConnectionPool` fix) and
      restoring a green lint/test baseline (`cli.py` UP017 fix, pytest
      `pythonpath`). Precursor to 0001 — unblocks its clean handoff. Spec:
      `specs/coordinator/tasks/0002-seasons-override-backfill.md`.

### 1.9 Docker & DX
- [x] Dockerfile (ingestor)
- [x] docker-compose (ingestor + Postgres, named volume for db)
- [x] Makefile: `up`, `down`, `ingest`, `test`, `lint`, `logs`
      (plus `build`, `migrate`, `shell`, `psql`, `clean`)
- [x] README quickstart (clone → .env → make up → make ingest)

### Phase 1 exit criteria
- [ ] A full daily run completes across the configured league set
- [ ] Phase B correctly fetches rich data + halftime stats for recent fixtures
- [ ] Re-running immediately stores ~0 new rows (hash dedup proven)
- [ ] A simulated mid-run crash resumes cleanly with no duplicates
- [ ] Failed leagues/fixtures land in dead_letter and are retryable
- [ ] All tests pass against a mocked API; lint/type-check clean

---

## Phase 1.5 — API-Football projection (CURRENT SCOPE)

Governance scaffolding (`DECISIONS.md`, `LOG.md`, `specs/`, `PROMPTS.md`,
`CLAUDE.md` charter amendment + three-agent workflow) was set up as a
**bootstrap** outside the loop (2026-07-05). The first loop task builds the one
bronze-only-charter exception: the `apifootball_events` snapshot the matcher
reads as an event source (DECISIONS D2–D6). Step 2 (the matcher-side source) is
`arbibet-matcher` task 0001.

### 1.10 `apifootball_events` projection (D2–D6)
- [~] **0001** — _(PAUSED — blocked on 0002; implementor escalated a dirty tree,
      see `specs/implementor/notes/0001-apifootball-events-projection.md`.)_
      Physical snapshot table `apifootball_events` in the matcher's
      (sources) DB, computed from `bronze_fixtures` (latest per league+season,
      `status=NS`, `start > NOW()`, all leagues, football), conforming to the
      matcher's `EVENT_COLUMNS` with `e_id="apifootball;<fixture_id>"`. Built as
      the final step of a run, gated on `ingestion_runs.status='succeeded'`,
      refreshed on **any** successful run, replaced **atomically in one
      transaction** (cross-DB precludes a matview — D4). Written into the
      matcher's DB (option B — the ingestor gains sources-DB write creds).
      Coordinate the table contract with matcher task 0001. Spec:
      `specs/coordinator/tasks/0001-apifootball-events-projection.md`.

---

## Phase 2 — Silver Layer (FUTURE — do not start yet)
- [ ] Flatten/parse bronze JSONB into typed relational tables
- [ ] Extract embedded data from rich fixture response (lineups, events,
      player stats, fixture stats) into separate silver tables
- [ ] Merge halftime stats into fixture statistics silver table
- [ ] Deduplicate by entity key, keeping latest snapshot (watermark pattern)
- [ ] Incremental processing (only bronze rows since last watermark)
- [ ] Data-quality checks (nulls, referential integrity, row-count deltas)

## Phase 3 — Gold Layer (FUTURE — do not start yet)
- [ ] Star-schema marts (facts + dimensions)
- [ ] Business views: match summary, player season stats, team form
- [ ] Decide view vs materialized view vs physical table per mart

---

## Progress log
- _(YYYY-MM-DD)_ — Repo initialized; CLAUDE.md and ROADMAP.md added. Phase 1 begins.
- _(2026-06-06)_ — Steps 1.1–1.7 landed. Scaffolding, Settings, HTTP client
  (rate limiter + retry + validation), bronze storage (8 tables + migrations),
  4 fetchers, selection filters, checkpoint store, dead_letter, Phase A/B
  orchestrators with per-task isolation, end-to-end runner with resume,
  CLI entrypoint, periodic heartbeat. 74 passing tests (1 xfail placeholder).
- _(2026-06-06)_ — Steps 1.8 + 1.9 landed. Dockerfile (python:3.12-slim),
  ingestor service in compose (cli profile, on-demand), real Makefile
  (`up`, `down`, `build`, `migrate`, `ingest`, `shell`, `test`, `lint`,
  `logs`, `psql`, `clean`), README quickstart, `docs/REBUILD.md` documenting
  the replay path. All Phase 1 ROADMAP boxes ticked; only the exit-criteria
  smoke (real-API run) remains.
