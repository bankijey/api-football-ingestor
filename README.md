# API-Football Bronze Ingestor

**Medallion-architecture bronze layer for [API-Football](https://www.api-football.com/).** Raw, append-only ingestion with hash-based deduplication, two-phase fetch strategy, full failure isolation, and idempotent resume from checkpoint. The match-data foundation for the Arbibet platform.

> Built from scratch as a disciplined rebuild of an earlier monolith — *do it properly this time*.

---

## Why this design

API-Football has ~1,500 leagues, a per-minute rate limit, and a daily quota. Naively pulling everything every day blows the quota; pulling nothing wastes the bronze layer's job (capture everything, transform later). The chosen strategy:

- **Phase A (league-grain):** one `/leagues` call + one `/fixtures?league=X&season=Y` call per active league. Builds the fixture catalogue.
- **Phase B (fixture-grain):** for recently-played fixtures only, fetch the rich `/fixtures?id=X` endpoint (one call → lineups + events + player stats + match stats) plus `/fixtures/statistics?fixture=X&half=true` (half-time stats not in the rich response).

Two API calls per relevant fixture instead of five. Quota survives.

## Key technical decisions

| Decision | Rationale |
|---|---|
| **Append-only bronze** (no UPDATE, no DELETE) | Raw layer is the system of record. Mutations live in silver/gold. Replayable from day 1. |
| **SHA-256 hash dedup** on every payload | Re-running an unchanged endpoint writes ~0 new rows. The bronze table is a content-addressed log. |
| **Sync + ThreadPoolExecutor** instead of async | Simpler reasoning, easier rate-limiter coordination, sufficient throughput for the API's rate limit. |
| **Per-league and per-fixture failure isolation** | One bad league can't abort the entire run. Failures go to a `dead_letter` table for replay. |
| **Checkpointed runs** | `ingestion_runs` + per-task state lets a crashed run resume without re-fetching what's already landed. |
| **Heartbeat daemon thread** | `last_heartbeat_at` lets external monitors detect a hung run, not just a crashed one. |
| **HTTP 200 with non-empty `errors` field = failure** | API-Football's quirk — silently succeeded responses that aren't actually success. Handled explicitly. |

## Architecture

```
src/ingestor/
  config.py             Pydantic Settings (rate limits, leagues, lookback, …)
  logging_setup.py      structlog → one JSON object per line, stdout
  heartbeat.py          daemon thread bumping ingestion_runs.last_heartbeat_at
  cli.py                python -m ingestor.cli ingest [--season --leagues --resume]
  http/                 shared client (rate-limited, retried, validated)
  db/                   connection pool, migrations, hash-dedup bronze writer
  fetchers/             one per endpoint (leagues, fixtures_by_league, …)
  selection/            league + fixture filters (status, coverage, lookback)
  checkpoint/           CheckpointStore (run + per-task state)
  orchestrator/         phase_a → phase_b → runner with per-task isolation
migrations/             *.sql, applied in order
```

8 bronze tables: `bronze_leagues`, `bronze_fixtures`, `bronze_fixture_details`, `bronze_halftime_stats`, `bronze_latest_hash`, `ingestion_runs`, `ingestion_checkpoints`, `dead_letter`.

## Quickstart

```bash
git clone <this repo>
cd api-football-ingestor

# 1. Secrets / overrides
cp .env.example .env
# edit .env: APIFOOTBALL_KEY, POSTGRES_HOST_PORT if 5432 is taken

# 2. Bring up Postgres + migrations
make up
make migrate

# 3. Run a one-off ingestion
make ingest

# 4. Backfill / restricted runs
make ingest ARGS="--leagues 39,140 --season 2025"
make ingest ARGS="--lookback-days 30"
make ingest ARGS="--resume <run_id>"
```

Tear down with `make down` (keeps data) or `make clean` (drops the volume).

**Running in production?** The daily schedule, subscription-renewal calendar, and a verify-a-run checklist live in the operations runbook: [`docs/OPS.md`](docs/OPS.md).

## Development

```bash
# Tests need Postgres running:
make up
TEST_DB_DSN=postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:${POSTGRES_HOST_PORT:-5432}/$POSTGRES_DB make test

make lint                     # ruff + mypy strict
```

Pure tests (HTTP, config, logging, selection logic) run without Postgres and auto-skip DB-tagged tests.

## Quality bar

- **74 passing tests** at the close of Phase 1
- **Strict mypy** across the source tree
- **Ruff** for linting + import sorting
- **All Phase 1 ROADMAP boxes ticked** (see `docs/ROADMAP.md`)

## Tech stack

Python 3.12 · `httpx` (sync) · `tenacity` (retries + jitter) · `pydantic` + `pydantic-settings` · `structlog` · `psycopg2` · `concurrent.futures.ThreadPoolExecutor` · Docker / Compose · Make

## Skills demonstrated

- **Medallion architecture executed properly** — Bronze fully complete and stable before any Silver work begins. No shortcuts pulling forward.
- **API quota engineering** — two-phase strategy reduces calls per fixture from 5 → 2 with no loss of data fidelity.
- **Idempotency at every layer** — hash dedup at the row level, checkpoints at the run level, migrations safe to re-apply.
- **Failure isolation as a first-class concern** — per-task isolation + dead_letter so a single bad endpoint never poisons a run.
- **Disciplined observability** — `structlog` JSON throughout, per-run metrics on `run.done`, heartbeat dead-man's-switch.
- **Operational replay** — `docs/REBUILD.md` documents the full bronze rebuild path so the layer is provably reproducible.
- **Test discipline** — DB-tagged tests, pure tests, mocked API throughout; CI-friendly.

## Status

**Phase 1 (Bronze) — complete.** Silver and Gold are intentionally out of scope until Bronze is stable.

Next phases (designed, not started):
- **Silver:** flatten JSONB → typed relational; extract embedded data from rich responses; watermark dedup.
- **Gold:** star-schema marts; business views (match summary, player season stats, team form).

## License

Private — part of the Arbibet platform.
