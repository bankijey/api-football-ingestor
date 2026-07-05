# 0001 — `apifootball_events` projection → matcher DB

**Roadmap item:** Phase 1.5 §1.10
**Depends on:** governance bootstrap (done); `bronze_fixtures` (exists).
Coordinates with `arbibet-matcher` task 0001 (the column contract).
**Status:** open

## Goal

Build the one bronze-only-charter exception (**D2**): the `apifootball_events`
snapshot the matcher reads as an event source. As the final step of a successful
ingestor run, project the latest `bronze_fixtures` catalogue into a physical
table in the **matcher's (sources) DB** (option B — **D5**), conforming to the
matcher's `EVENT_COLUMNS` with `e_id = "apifootball;<fixture_id>"` (**D6**). The
table is **atomically replaced in one transaction** on **any** successful run
(**D4** — a Postgres matview can't span DBs, so this is a plain table the
ingestor maintains, not `REFRESH MATERIALIZED VIEW`).

## In scope

### Config — modified (`src/ingestor/config.py`)
- Add `matcher_db_dsn: str` (env `MATCHER_DB_DSN`) to the `Settings` model,
  mirroring the existing `db_dsn`/`DB_DSN` field (config.py:64) — same type, same
  env-only loading (never hardcoded). This is the **sources DB** the projection
  is written INTO; bronze ingestion keeps using `db_dsn`. Also document it in
  `.env.example`. (Naming: DSN not URL, to stay consistent with `db_dsn`.)

### Projection builder — created (`src/ingestor/projection.py`)
A single-purpose module that takes two `ConnectionPool`s (from
`src/ingestor/db/connection.py`) — the existing bronze pool for reads and a
second pool built from `settings.matcher_db_dsn` for the sources-DB write. Do
NOT open raw psycopg2 connections (the pool is the only sanctioned DB entrypoint
— see the `connection.py` module docstring). Then:
1. Reads from the **local bronze DB**: the latest `bronze_fixtures` row per
   `(league_id, season)` (`DISTINCT ON (league_id, season) … ORDER BY
   league_id, season, ingested_at DESC`), and unwraps each payload's
   `response[]` fixture array.
2. For each fixture, keeps it only if `fixture.status.short == 'NS'` **and**
   `fixture.timestamp` is in the future. Maps to a projection row:
   | column | source |
   |---|---|
   | `fixture_id` | `fixture.id` (ingestor natural key; not in `EVENT_COLUMNS`, harmless) |
   | `e_id` | `'apifootball;' || fixture.id` (**semicolon**, D6) |
   | `bookmaker_id` | `'apifootball'` (D6) |
   | `sport_key` | `'football'` |
   | `start` | `to_timestamp(fixture.timestamp)` (`TIMESTAMPTZ`) |
   | `tid` | `league.id` |
   | `tournament` | `league.name` |
   | `home_team` / `away_team` | `teams.home.name` / `teams.away.name` |
   | `home_id` / `away_id` | `teams.home.id` / `teams.away.id` |
   | `url` | `NULL` (D6) |

   The full column set is D6's `EVENT_COLUMNS` (plus the `fixture_id` natural
   key). Do NOT drop `bookmaker_id` or `url` — the matcher's `ApiFootballSource`
   selects them by name (matcher task 0001).
3. Writes to the **sources DB** `apifootball_events` table via an **atomic
   replace in one transaction**: build into a staging table then swap, or
   `BEGIN; TRUNCATE apifootball_events; INSERT …; COMMIT;`. The table is created
   if absent (idempotent DDL, run at build start on the same connection). Use a
   single `with matcher_pool.connection() as conn:` block — its commit-on-clean-
   exit / rollback-on-exception (connection.py:38-49) IS the all-or-nothing
   guarantee AC5 checks. Readers see the whole old snapshot or the whole new one
   — never a partial (D4).
- All leagues, football only (D3). No downsampling, no filtering by HF-selected
  leagues.

### Orchestration hook — modified (`src/ingestor/orchestrator/runner.py`)
- In `run_ingestion`, on the **success path only** — after
  `checkpoints.finish_run(run_id, status=status, …)` (runner.py:108) and gated on
  `status == 'succeeded'` (computed by `_terminal_status`, runner.py:101/188) —
  call the projection builder, passing the existing bronze `pool` and a pool
  built from `settings.matcher_db_dsn`. The `except` branch (runner.py:116-120)
  sets status `failed` and re-raises, so `partial`/`failed` never reach the hook
  and the prior snapshot stays untouched (D4). Fires on **any** successful run,
  not only the scheduled 2am one.

## Out of scope
- **The matcher's `ApiFootballSource`** (that's `arbibet-matcher` task 0001).
- **FDW / `postgres_fdw` / a SQL materialized view** — D4 mandates a plain table
  + transactional swap; do not introduce a foreign data wrapper.
- **Any change to bronze tables or the bronze write path.** Bronze stays
  append-only; the projection reads bronze and writes only to the *sources* DB.
- **Silver** (parsing bronze into typed tables) — the projection is
  field-extraction only (D2), not the Silver layer.
- **Player/results/lineups extraction** — out of this projection entirely.

## Files
Created:
- `src/ingestor/projection.py` (builder + atomic-swap writer + idempotent DDL)
- `tests/test_projection.py`

Modified:
- `src/ingestor/config.py` — add `matcher_db_dsn` (env `MATCHER_DB_DSN`)
- `.env.example` — document `MATCHER_DB_DSN`
- `src/ingestor/orchestrator/runner.py` — invoke the builder in `run_ingestion`,
  gated on `status == 'succeeded'`
- `docs/ROADMAP.md` — coordinator flips `0001 [~]→[x]` + Progress-log line ON
  CLOSE (not the implementor)
- `LOG.md` — implementor appends one line on commit

If anything outside this list needs changing, STOP and surface a note at
`specs/implementor/notes/0001-apifootball-events-projection.md`.

## Acceptance criteria (Definition of Done)
1. `make lint` and `make test` exit 0; new tests collected.
2. `matcher_db_dsn` (env `MATCHER_DB_DSN`) is in the `Settings` model and
   `.env.example`; no DSN literal in source.
3. Given a seeded `bronze_fixtures` payload containing a mix of fixtures
   (one `NS`+future, one `NS`+past, one `FT`), running the projection writes to
   the sources DB **exactly one** `apifootball_events` row — the `NS`+future one
   — carrying the full D6 column set: `e_id == "apifootball;<id>"`,
   `bookmaker_id == "apifootball"`, `sport_key == "football"`, `url IS NULL`,
   plus the `start`/`tid`/`tournament`/team-name/team-id mapping.
4. `e_id` uses `;` not `:`.
5. **Atomicity:** simulate a failure mid-write (after staging, before commit) →
   the prior `apifootball_events` snapshot is intact (no partial state, no empty
   table).
6. **Gating:** the builder runs when the run status is `succeeded` and does NOT
   run for `partial`/`failed` (unit-test the hook's guard).
7. **Latest-per-(league,season):** two `bronze_fixtures` ingests for the same
   `(league_id, season)` → the projection reflects only the newest ingest.
8. Bronze tables and the bronze write path are byte-identical (`git diff --stat`
   shows no change under the bronze writer / migrations for bronze).
9. No `DECISIONS.md` violated (D2 field-extraction only; D3 all-leagues/football;
   D4 plain-table atomic swap, no matview/FDW; D5 writes to sources DB; D6
   contract).

## Verifier checklist (mirror of DoD + housekeeping)
- [ ] AC1 — lint/test green
- [ ] AC2 — `matcher_db_dsn` (`MATCHER_DB_DSN`) config + `.env.example`, not hardcoded
- [ ] AC3 — projection row set correct for a mixed seed (full D6 columns)
- [ ] AC4 — semicolon `e_id`
- [ ] AC5 — atomic swap leaves prior snapshot intact on mid-write failure
- [ ] AC6 — refresh gated on `status == 'succeeded'`
- [ ] AC7 — latest ingest per `(league_id, season)`
- [ ] AC8 — bronze untouched
- [ ] AC9 — no `DECISIONS.md` entry violated (esp. no matview/FDW — D4)
- [ ] No files outside §Files modified; `docs/ROADMAP.md` not modified by
      implementor
- [ ] Working tree clean on handoff; `LOG.md` has the implementor line + real SHA

## Notes for the implementor
- **Two connections, one direction:** read bronze locally, write the sources DB.
  The projection is the ONLY place this process touches the sources DB. Keep the
  sources-DB write confined to `projection.py`.
- **The atomic swap is the crux.** The matcher may run at any moment; it must
  never observe a truncated or half-loaded table. Wrap the replace in a single
  transaction. `TRUNCATE`+`INSERT` inside `BEGIN…COMMIT` holds a brief exclusive
  lock — acceptable, since the matcher read either precedes or follows it. Do
  NOT delete-then-insert across separate transactions.
- **`fixture.status.short == 'NS'`** is the not-started marker; combine with a
  future `fixture.timestamp` (unix seconds) — a delayed/erroneous `NS` in the
  past must not leak in (AC3).
- **Coordinate the column names** with `arbibet-matcher` task 0001 — both cite
  D6. If you must deviate, STOP and escalate so both sides stay in lockstep.
- **Idempotent DDL:** `CREATE TABLE IF NOT EXISTS apifootball_events (…)` in the
  sources DB, run once at build start. Do not add it to the bronze migrations.
