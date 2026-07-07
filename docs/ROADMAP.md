# Roadmap — API-Football Bronze Ingestor

This file is the durable, cross-session source of truth for **what's done and
what's next**. Git tracks the code; this file tracks intent and progress.

**Convention:** At the end of every working step, update the relevant checkbox
and add a one-line note under "Progress log" with the date. When resuming work,
read `CLAUDE.md` then this file before doing anything else.

Status key: `[ ]` not started · `[~]` in progress · `[x]` done

---

## Phase 1 — Bronze Layer (✅ COMPLETE & STABLE — 2026-07-07)

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
- [x] **0002** — Multi-season backfill enhancement: `--seasons` CLI flag +
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

### Phase 1 exit criteria — ALL MET (0003 bounded live + 0005 full live)
- [x] A full daily run completes across the configured league set
      — 0005: 1,231-league run `succeeded` in 541 s (verifier PASS `a659f74`).
- [x] Phase B correctly fetches rich data + halftime stats for recent fixtures
      — 0003 S2 + 0005 (phase_b ok=208).
- [x] Re-running immediately stores ~0 new rows (hash dedup proven) — 0003 S3.
- [x] A simulated mid-run crash resumes cleanly with no duplicates — 0003 S4.
- [x] Failed leagues/fixtures land in dead_letter and are retryable
      — proven hermetically (`test_phase_a_isolates_one_failing_league`); the
        live per-item DLQ path is not code-free reachable (0003 S5 rationale).
- [x] All tests pass against a mocked API; lint/type-check clean — every cycle.

---

## Phase 1.5 — API-Football projection (✅ COMPLETE — 2026-07-05)

Governance scaffolding (`DECISIONS.md`, `LOG.md`, `specs/`, `PROMPTS.md`,
`CLAUDE.md` charter amendment + three-agent workflow) was set up as a
**bootstrap** outside the loop (2026-07-05). The first loop task builds the one
bronze-only-charter exception: the `apifootball_events` snapshot the matcher
reads as an event source (DECISIONS D2–D6). Step 2 (the matcher-side source) is
`arbibet-matcher` task 0001.

### 1.10 `apifootball_events` projection (D2–D6)
- [x] **0001** — _(DONE 2026-07-05 — verifier PASS, `d7f125e`. Full suite ran
      against the live `ingestor-postgres` container with zero skips; all 9 ACs
      green.)_
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

## Phase 1.6 — Live smoke: exit criteria + projection E2E (✅ COMPLETE — 2026-07-07)

All hermetic work is green (1.1–1.10). What has never happened is a run against
the **real API**. This phase proves the Phase 1 exit criteria live and, in the
same run, proves the 0001 projection end-to-end (real run → `apifootball_events`
populated in the sources DB) — which gates the matcher's live smoke
(`arbibet-matcher` Phase B).

### 1.11 Live smoke (evidence-based, quota-bounded)
- [x] **0003** — Quota-bounded live smoke: real API key, handpicked league
      subset via `--leagues` (~5–10 leagues, current season). Proves, with
      DB/ledger evidence (not pytest): full run `succeeded`; Phase B rich data +
      halftime stats landed; immediate re-run inserts ≈0 bronze rows (hash
      dedup); mid-run kill + `--resume` completes with no duplicates; forced
      failures land in `dead_letter` and are retryable; projection E2E —
      `apifootball_events` populated in the sources DB, `e_id` format correct,
      NS+future only. Evidence recorded to `docs/SMOKE_0003_EVIDENCE.md`;
      verifier corroborates by re-querying. Spec:
      `specs/coordinator/tasks/0003-live-smoke-exit-criteria.md`.
- [x] **0004** — Projection hardening before the full run (0003 verifier
      findings F3 + F1): stream the bronze read via a server-side cursor so the
      projection no longer loads all ~7,894 league-season payloads into memory
      (~6 GiB), and normalize the `MATCHER_DB_DSN` `+driver` dialect suffix so a
      matcher-copied SQLAlchemy URL works with raw psycopg2. Output-preserving
      (D2/D3/D4/D6 unchanged). Gates 0005. Spec:
      `specs/coordinator/tasks/0004-projection-hardening.md`.
- [x] **0005** — Full-catalogue live run (all ~1,500 current-season leagues):
      one unbounded run for real quota + wall-clock numbers to size the daily
      schedule, and the full-scale failure rate. Came back **`succeeded`**
      (1,231 leagues, 0 failures), projection refreshed to 42,399 rows;
      2,021 calls ≈ 2.7 % of daily quota, ~12 min. Verifier PASS `a659f74`.
      Evidence: `docs/FULLRUN_0005_EVIDENCE.md`. Spec:
      `specs/coordinator/tasks/0005-full-catalogue-run.md`.
- [x] **0007** — Rebuild + redeploy the ingestor image and **prove the
      autonomous scheduled run refreshes `apifootball_events`** (0003 finding F2).
      Verifier PASS `3c26123`. A crond-fired isolated run (`ec38234d`, 20:12 UTC)
      of the rebuilt image reached `succeeded` and refreshed the projection to
      42,383 rows (D6 contract 42383/42383). En route it hit transient
      429/`failed` fires later traced to a **subscription lapse** (renewed
      2026-07-06, expiry 2026-08-06 — see `docs/DEPLOY_0007_EVIDENCE.md`
      coordinator addendum), NOT rate-limiting or shared-key contention; D4 held
      correctly throughout (bad runs left the prior snapshot intact). Spec:
      `specs/coordinator/tasks/0007-scheduler-redeploy.md`.
- [x] **0008** — Daily scheduling: **anti-drift redeploy** + ops runbook.
      Verifier PASS `f188c9b`. Decision **rebuild-on-cron** (`run --build`) landed
      in both trigger paths (`docker-compose.yml`, `scripts/run-ingest.ps1`); an
      autonomous crond-fired run rebuilt `:latest` from source (image advanced to
      `552d4a2874cb`) **before** running, reached `succeeded`, and refreshed
      `apifootball_events` to 43,123 rows — drift can no longer recur. `docs/OPS.md`
      tracks the daily run + the **2026-08-06 subscription expiry**. Spec:
      `specs/coordinator/tasks/0008-daily-scheduling.md`.
- [x] **0006** — De-flake `test_heartbeat_ticks_at_interval` (0003/0005 finding
      V1). Verifier PASS `e322698`. Replaced the fixed `time.sleep` + exact-count
      race with a **bounded poll** (`_poll_until`, 2 s deadline); test-only,
      `heartbeat.py` byte-identical; demonstrated 26/26 clean runs incl. under
      4-process CPU load. Spec:
      `specs/coordinator/tasks/0006-heartbeat-test-flake.md`.
- [ ] **0009** — Persist per-minute `x-ratelimit-*-remaining` headers (0005
      finding 1): the client receives but discards them. **Backlog observability
      for FUTURE diagnosis** — explicitly NOT needed to explain the 0007 incident,
      which is now traced to a subscription lapse (not throttling). Small change.
      _(Bundle-in candidates from 0008's verifier, both low-priority: (a)
      `scripts/run-ingest.ps1` passes `--profile cli` as a `run` argument rather
      than the top-level `docker compose --profile cli run` flag — a latent bug on
      the Windows trigger path, which is not the primary trigger; (b) `docs/OPS.md`
      §3 hard-codes container names, so a rename would silently break the runbook —
      cosmetic.)_
- [ ] **0010 — DEFERRED (D4 stays locked)** — Partial-tolerance /
      success-with-warnings policy. The transient failures that motivated it
      (0007's 429/`failed` fires) were a **subscription lapse**, not a genuine
      per-run partial rate — so we do **not** amend a locked decision (D4) to
      tolerate a billing event. The D4 all-or-nothing gate behaved correctly
      throughout 0007 (bad runs preserved the prior snapshot). **Revisit only if a
      healthy-subscription full run shows a real, recurring partial rate.**
- [ ] **0011** — Test-gate hardening (0006 verifier observation): stand up an
      **ephemeral Postgres** for `make test` so the ~27 DB-backed tests
      (`test_projection.py` et al.) run in the standard gate instead of skipping
      when no local DB is present — the DB-integration coverage currently only
      runs when a container happens to be up. Backlog hygiene, no product impact.

**Backlog note (2026-07-07):** 0009 + 0011 are optional hygiene and 0010 is
deferred — none is on a critical path. Pick them up when this repo next has an
active arc.

---

## Phase 2 — Silver Layer (GATED — authorized only in a platform planning round)

**Why gated, not just "next" (2026-07-07):** Silver is the labels / feature store
for a **future quant/ML phase that has no consumer today**. Because bronze is
fully replayable (`docs/REBUILD.md`), deferring Silver costs nothing — it can be
built from the accumulated raw history whenever a consumer exists. It is
therefore **not** a rolling next-task; it will be authorized in a platform-level
planning round, not picked up automatically off this list.

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
- _(2026-07-05)_ — **0002** done (verifier PASS, `c582c95`): `--seasons` CLI
  flag + `select_leagues(seasons=…)` + window guard, landing the pending
  multi-season backfill feature with a `ThreadedConnectionPool` fix and a
  restored green lint/test baseline (`cli.py` UP017, pytest `pythonpath`). This
  was Option A from 0001's escalation — it disentangles the tree so **0001**
  (`apifootball_events` projection) can now commit cleanly. 0001 re-routed to
  the implementor.
- _(2026-07-05)_ — **0001** done (verifier PASS, `d7f125e`): the
  `apifootball_events` projection — the one bronze-only-charter exception (D2).
  Latest `bronze_fixtures` per `(league_id, season)`, `NS`+future, all leagues,
  projected to D6's `EVENT_COLUMNS` (`e_id="apifootball;<id>"`), written into the
  sources DB via a single-transaction TRUNCATE+INSERT (D4/D5), gated on
  `status=='succeeded'`. 85 tests pass (5 new projection tests ran against the
  live container, zero skips); lint/type-check clean. **Phase 1.5 §1.10 complete
  — the projection loop's terminal deliverable.** Remaining Phase-1 exit criteria
  1–2 (full run across the live league set; Phase B live rich-data) need a
  real-API smoke run.
- _(2026-07-06)_ — **0003** done (verifier PASS, `8e69672`): the quota-bounded
  live smoke — first-ever real-API run. All six Phase-1 exit criteria proven live
  with DB/ledger evidence (S1 succeeded run, S2 rich data, S3 hash-dedup re-run,
  S4 kill+resume no-dup, S5 fail-safe+recovery, S7 hermetic gates) plus S6
  projection E2E (`apifootball_events` populated in the sources DB, 39,942 rows,
  NS+future, `apifootball;<id>` contract) — which **unblocks the matcher's Phase B
  live smoke**. Verifier surfaced four non-blocking findings, routed as follow-ups.
  **0004** opened (coordinator, human-confirmed sequencing): harden the projection
  path (F3 server-side-cursor streaming to kill the ~6 GiB fetchall; F1
  `MATCHER_DB_DSN` dialect normalization) **before** the expensive full-catalogue
  run — which is renumbered **0005**. Findings V1 (flaky heartbeat test) and F2
  (stale scheduler image) tracked as **0006**/**0007**.
- _(2026-07-06)_ — **0004** done (verifier PASS, `11493f4`): projection hardening.
  `_read_rows` now streams `bronze_fixtures` via a psycopg2 server-side named
  cursor (`apifootball_proj_read`, itersize 200) instead of `fetchall()`-ing all
  ~7,894 payloads — output byte-identical (all 5 pre-existing `test_projection.py`
  tests green, D2/D3/D4/D6 untouched). `MATCHER_DB_DSN` gains a scheme validator
  stripping the `+driver` suffix (F1). 87 tests pass, lint/mypy clean.
  **0005** opened: the full-catalogue live run — one unbounded run to size the
  daily schedule (quota + duration) and characterize the full-scale failure rate.
  Designed observational: `partial` (and thus no projection refresh per D4) is
  expected DATA, and its failure numbers are the input a future partial-tolerance
  policy needs — so the run rightly precedes that policy call.
- _(2026-07-06)_ — **0005** done (verifier PASS, `a659f74`): the full-catalogue
  live run came back **`succeeded`** — 1,231 leagues, 0 Phase A/B failures, 541 s
  bronze + ~164 s projection, 2,021 API calls (~2.7 % of the 75k daily quota,
  ~37× margin), projection refreshed to 42,399 rows. Not the anticipated
  `partial`, so the partial-tolerance policy still has no real failure numbers
  (deferred). **All Phase 1 exit criteria now met.** Human steered the next arc to
  operationalization: **0007** opened — rebuild the stale deployed image and prove
  the *autonomous* 2am schedule (not a manual `make ingest`) refreshes
  `apifootball_events`, since the cron path never rebuilds `:latest` and has run
  pre-projection code in production. Sequenced after: **0008** daily scheduling
  (owns the anti-drift redeploy strategy), then **0006** flaky test; **0009**
  (rate-limit header logging) tracked as backlog.
- _(2026-07-06)_ — **0007** escalated + amended (stays `[~]`). Implementor
  completed D1/D2/D5 — rebuilt `:latest` (`d764187`, projection code present);
  identified the live `ingestor-scheduler` cron (20 prior scheduled runs, **0**
  `projection.built`, confirming F2's stale-image drift in production); schedule
  restored — but D3/D4 blocked: two **back-to-back** autonomous full runs went
  `partial` on transient 429s, so the `succeeded`-gated projection (D4) never
  refreshed (gate proven correct; DoD gate unmet). Coordinator amended D3 to a
  **single ISOLATED** autonomous fire (the 429s are likely self-inflicted by
  rapid re-triggering — 0005 in isolation had 0 failures); §Files unchanged,
  D1/D2/D5 evidence salvaged. Fallback wired: if the isolated fire is still
  `partial`, the **partial-tolerance policy (0010)** becomes a precursor.
- _(2026-07-06)_ — **0007** done (verifier PASS, `3c26123`): "deployed AND
  verified" — a crond-fired isolated run (`ec38234d`, 20:12 UTC) of the rebuilt
  projection-carrying image reached `succeeded` and refreshed `apifootball_events`
  to 42,383 rows (D6 contract 42383/42383). **Root cause of the en-route
  429/`failed` fires identified post-hoc: a subscription lapse** (operator fact;
  renewed 2026-07-06, expiry 2026-08-06) — evidence-bracketed by run outcomes
  (all fires 17:08–19:27 UTC rejected with limit-type errors despite 88 % quota
  free; first fire after renewal, 20:12, succeeded with 0 failures). So the
  "flaky day" was a billing event, not a real partial rate: **0010
  (partial-tolerance / D4 change) DEFERRED, D4 stays locked**; **0009**
  (x-ratelimit logging) demoted to future-observability backlog. Opened **0008**
  (daily scheduling): decision **rebuild-on-cron** to kill the anti-drift flaw
  (scheduled path never rebuilds `:latest`) + `docs/OPS.md` runbook tracking the
  2026-08-06 expiry so the next lapse is anticipated.
- _(2026-07-07)_ — **0008** done (verifier PASS, `f188c9b`): daily scheduling is
  now **self-currenting**. `run --build` in both trigger paths
  (`docker-compose.yml` cron + `scripts/run-ingest.ps1`) means the `0 2 * * *` run
  rebuilds `:latest` from source before executing — an autonomous crond-fired run
  rebuilt the image (→ `552d4a2874cb`), reached `succeeded`, and refreshed
  `apifootball_events` to 43,123 rows, so F2's stale-image drift **cannot recur**.
  `docs/OPS.md` runbook records the daily run + the 2026-08-06 subscription expiry.
  **The Bronze daily pipeline is fully operational** (build → ingest → projection,
  automated, verified). Opened **0006** (de-flake the heartbeat timing test via a
  bounded poll) — the last green-baseline hygiene item; two low-priority 0008
  verifier findings (Windows-path `--profile` placement; OPS.md hard-coded
  container names) parked as bundle-in candidates for 0009.
- _(2026-07-07)_ — **0006** done (verifier PASS, `e322698`): heartbeat timing
  test de-flaked via a bounded poll (26/26 clean, incl. under CPU load);
  `heartbeat.py` untouched. Green-baseline hygiene closed.
- _(2026-07-07)_ — **✅ PHASE 1 COMPLETE & STABLE — `apifootball-integration`
  branch merge-ready.** Bronze is built, hermetically tested, live-proven at full
  catalogue (0005: 1,231 leagues `succeeded`), and running as a self-currenting
  automated daily job (0008: rebuild-on-cron) whose `apifootball_events`
  projection feeds the matcher (D2–D6). Exit criteria all met; lint/type-check/
  tests green. Remaining items are optional backlog (**0009** x-ratelimit logging,
  **0011** ephemeral-Postgres test gate) or explicitly deferred (**0010**
  partial-tolerance, D4 locked); **Phase 2 Silver stays gated** — authorized only
  in a platform planning round (no consumer today; bronze replayability makes
  deferral free). No rolling next-task; the three-agent loop pauses here until a
  new arc is authorized.
