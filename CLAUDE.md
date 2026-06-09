# API-Football Bronze Ingestor

## Why
Ingest data from API-Football into a medallion-architecture data platform.
This repo is built incrementally, ONE layer at a time. Current scope is
**BRONZE only** — raw, append-only ingestion. Silver and Gold are explicitly
out of scope until Bronze is complete and stable.

## What (Bronze scope)

### Endpoint strategy (important — read carefully)
There are TWO ingestion phases per run, with different grains:

**Phase A — League-grain (daily, all ~1,000–1,500 leagues):**
1. `/leagues` — fetch once per run; returns all leagues with coverage flags
   and current seasons. Used to build the work list.
2. `/fixtures?league={id}&season={year}` — one call per current league+season.
   Returns the fixture list (ids, dates, statuses, scores). This is the
   "catalogue" — it tells us WHAT fixtures exist.

**Phase B — Fixture-grain (only for recently-played fixtures):**
3. `/fixtures?id={fixture_id}` — the RICH endpoint. Returns fixture details
   PLUS embedded lineups, events, player statistics, and fixture statistics
   in a single response. This is the primary data fetch for match data.
4. `/fixtures/statistics?fixture={id}&half=true` — the ONLY separate call
   needed: half-time fixture statistics, which are NOT included in the rich
   fixture response.

So the flow is: Phase A discovers fixtures → Phase B fetches rich data for
relevant ones (2 calls per fixture instead of 5).

### Which fixtures get Phase B treatment
Not every fixture needs rich-data fetching. Filter to:
- Fixtures in the last N days (configurable, default 14)
- Fixtures with status indicating they've been played or are live
  (FT, AET, PEN, and optionally 1H/2H/HT/ET/INT/LIVE/P/BT/SUSP)
- Leagues whose `coverage` flags indicate they provide the relevant data
  (coverage.fixtures.lineups, coverage.fixtures.statistics_fixtures,
  coverage.fixtures.statistics_players, coverage.fixtures.events)

### Existing scraper reference
The file `docs/legacy/fix.py` contains the previous monolith scraper.
Use it as a reference for API response shapes, parsing patterns, and
edge cases — but do NOT replicate its architecture (upserts, pandas
transformations, hardcoded keys, no error isolation).

## Tech stack
- Python 3.12
- httpx (sync), tenacity (retries/backoff), pydantic (validation/config)
- concurrent.futures.ThreadPoolExecutor for bounded concurrency
- Postgres for bronze storage (raw JSON in JSONB columns)
- structlog for structured JSON logging
- Docker / docker-compose for everything

## API details
- Base URL: https://v3.football.api-sports.io
- Auth header: x-rapidapi-key (from env), x-rapidapi-host: v3.football.api-sports.io
- Rate limit: ~300 requests per 65 seconds (plan-dependent; make configurable)
- Daily quota: plan-dependent (make configurable, track usage)
- QUIRK: API returns HTTP 200 with a non-empty `errors` field on some failures.
  Treat this as an error, not a success.

## Commands
- `make up` — start the stack (db + ingestor) via docker-compose
- `make down` — tear down the stack
- `make ingest` — run a one-off bronze ingestion inside the container
- `make test` — run pytest
- `make lint` — ruff + mypy
- `make logs` — tail ingestor logs

## Hard rules
- NEVER commit secrets. API key comes from env / .env (gitignored).
- Bronze is APPEND-ONLY and immutable. Never UPDATE or DELETE bronze rows.
- Every external API call goes through the shared HTTP client (rate-limited,
  retried, validated). No raw httpx/requests calls in business logic.
- Each league's fetch is failure-isolated: one league failing must not abort the run.
- Each fixture's rich-data fetch is failure-isolated independently.
- HTTP 200 with non-empty `errors` field = treated as failure.

## Working style
- Work in small, reviewable steps. After each step, stop and summarise what
  changed and what's next, so work can pause and resume cleanly.
- Update the checkbox and progress log in docs/ROADMAP.md at the end of each step.
- Prefer config over hardcoding (rate limits, league list, season, retries,
  lookback window, fixture statuses).
