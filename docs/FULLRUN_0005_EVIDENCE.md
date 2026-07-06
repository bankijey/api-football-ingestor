# FULL RUN 0005 — Full-catalogue live run: quota / duration sizing

Evidence log for task `0005-full-catalogue-run`. Commands + queried results are
copied verbatim as executed. Timestamps are Berlin (CEST = UTC+2 on this date);
raw DB timestamps are UTC (DB session TZ is UTC).

**Operator:** implementor cycle · **Date:** 2026-07-06 (Berlin) ·
**Branch:** `apifootball-integration`

> Secrets discipline: the API key and sources-DB password appear nowhere in this
> file; DSNs are shown password-redacted (`***`).

---

## Environment & pre-flight

| Component | Value |
|---|---|
| Runtime | container `python:3.12-slim` (image rebuilt from 0004 source), **Python 3.12.13** |
| Bronze DB | `ingestor-postgres`, `localhost:5434` → `postgres:5432`, db `ingestor` |
| Sources DB (D5) | `arbibet-scraper-postgres-1`, `:5433`, db `Arbibet`, PostgreSQL 16.14 |
| `MATCHER_DB_DSN` | `postgresql://postgres:***@host.docker.internal:5433/Arbibet` (0004: dialect-tolerant) |
| Rate limit | `240` / `65s` window |
| Daily quota | `75000` |
| Lookback | `2` days (default) |
| Args | `ingest` — **no `--leagues`**, **no `--season`** (rides each league's `current=true` season, as the daily scheduler does) |

**Image rebuilt so the run exercises 0004's hardened projection** (`docker
compose run` does not auto-rebuild; the prior image predated 0004):

```
old image 5e8ae4917bee (2026-07-06 11:23)  ->  new 12782649a7ca (2026-07-06 18:03)
in-image checks:
  _read_rows uses cursor(name=: True   calls .fetchall(: False   _ITERSIZE: 200
  matcher_db_dsn normalize postgresql+psycopg2://→postgresql://: True
  python: 3.12.13
```

**Baseline before S1** (`2026-07-06 ~18:03 Berlin`):

```
bronze_leagues          = 23
bronze_fixtures         = 10326
bronze_fixture_details  = 132267
bronze_halftime_stats   = 130100
dead_letter             = 904
ingestion_runs          = 50
apifootball_events (sources DB) = 39942
```

---

## S1 — The full run

Command (rebuilt 3.12 image, no filters):

```
$ docker compose --profile cli run --rm ingestor ingest
```

**run_id `1f814136-e56a-4c08-be9c-804281d4b5e7`** — `run.done`:

```
{"status": "succeeded",
 "counters": {"leagues_total": 1231, "fixtures_total": 381,
   "phase_a": {"ok": 54, "skipped": 0, "unchanged": 1177, "failed": 0},
   "phase_b": {"ok": 208, "skipped": 0, "unchanged": 554, "failed": 0}}}
run.leagues_selected  count=1231  (full current-season catalogue)
run.fixtures_selected count=381   window=lookback_2d
```

`ingestion_runs` row:

```
run_id     1f814136-e56a-4c08-be9c-804281d4b5e7
status     succeeded
started    2026-07-06 16:05:07Z
finished   2026-07-06 16:14:08Z   (bronze phases; projection follows)
bronze duration     541 s (~9m01s)
leagues_total 1231   fixtures_total 381
```

- **1231 leagues** — the full current-season catalogue (not a handful) ✔
- Terminal status **`succeeded`** — zero Phase-A/Phase-B failures across all 1231
  leagues (the retry/backoff absorbed the transient errors; see S4).
- Total process wall-clock incl. projection: `16:05:07Z → 16:16:52Z` ≈ **11m45s**.

## S2 — Quota accounting

API calls actually sent this run (by path, from the run log):

```
/leagues              :    1
/fixtures             : 1635   (Phase A 1231 fixtures-by-league + Phase B ~404 fixture-details)
/fixtures/statistics  :  385   (Phase B halftime)
                        ─────
total                 : 2021   API calls  (of which 29 were retries — see S4)
```

Consistent with the model: Phase A ≈ `1 + leagues_total` = 1232; Phase B ≈
`2 × recent-fixtures` = `2 × 381` = 762 base (+29 retries).

**Daily quota** — `/status` probe (does not consume quota), taken just after the
run:

```
subscription: Ultra (active)
requests today: 5094 / 75000     (all sources today: 0003 smoke + 0004 + this run + probes)
```

- This full run ≈ **2021 calls = ~2.7 % of the 75000 daily quota**; ~73k headroom.
- Per-minute: ~1960 rate-limited calls over ~9 min ≈ **~218/min average**, under
  the configured 240/65s cap — the limiter enforced it, no blow-through.
- (`x-ratelimit-*` response headers are observed by the rate limiter but not
  logged/persisted, so exact per-minute *remaining* values aren't retrievable
  post-hoc; the call-count-vs-quota figures above are the actionable sizing
  numbers, and `/status` gives the authoritative daily total.)

## S2 — Quota accounting

<!-- S2 -->

## S3 — Projection at full scale (0004 payoff)

The run was `succeeded`, so the projection ran (D4). Log:

```
projection.built        rows=42399   16:16:52Z
run.projection_written  rows=42399   16:16:52Z
projection duration: run.done 16:14:08Z → written 16:16:52Z ≈ 2m44s (~164 s)
```

- **No OOM.** The container exited **0** and committed 42399 rows atomically; an
  OOM would exit 137 and roll the transaction back (empty/stale table). Contrast
  the pre-0004 cold build (~6 GiB / ~12 min): 0004's server-side cursor streams
  the ~7.9k latest league-season payloads in 200-row batches, so resident input
  is bounded regardless of catalogue size. (Peak RSS was not sampled this run —
  it was backgrounded — but the clean exit + ~164 s at 1231-league scale is the
  observable payoff.)

Sources-DB `apifootball_events` re-affirmed at full scale (D3/D6):

```
 total | eid_bad | not_future | bad_bookmaker | bad_sport | bad_url | earliest_start
 42399 |    0    |     0      |       0       |     0     |    0    | 2026-07-06 16:30:00Z
```

- `count(*) = 42399 > 0` ✔
- every `e_id ~ '^apifootball;[0-9]+$'` — 0 violations ✔
- `min(start) > now()` (earliest kickoff 16:30Z, run finished ~16:17Z) — NS+future
  only (D3) ✔
- `bookmaker_id='apifootball'`, `sport_key='football'`, `url IS NULL` for all ✔

## S4 — Terminal status + failure characterization

**Terminal status: `succeeded`** — and therefore **zero `dead_letter` rows for
this run**:

```
SELECT endpoint, error_class, count(*) FROM dead_letter
 WHERE run_id='1f814136-…' GROUP BY 1,2;   ->  (0 rows)
```

The catalogue is currently clean enough to complete with **no terminal
failures** at 1231-league scale. This run therefore does **not** exhibit the
expected `partial`, and there is nothing to escalate re: the terminal-status /
projection-gating tension **on this run** — the `succeeded` branch (S3) applies
and the projection refreshed.

**Transient failures that were absorbed (did not become `dead_letter`):** 29
retried requests, all **HTTP 200 with a non-empty `errors` field** — the
documented API-Football quirk (`CLAUDE.md`) — which the client correctly treats
as failure and retries:

```
 25 × /fixtures            status 200 (200-with-errors, retried→ok)
  4 × /fixtures/statistics status 200 (200-with-errors, retried→ok)
```

**For the deferred partial-tolerance decision (context, not an escalation):** the
binary `_terminal_status` + `succeeded`-gated projection (D4) means a *single*
un-recovered league/fixture on a future day would flip the run to `partial` and
skip the projection refresh for that day (the prior snapshot stands). This run
provides a lower bound — the transient-error class is 200-with-errors and the
retry path cleared all of them — but it did **not** produce partial-failure data
(a clean run). If/when a run comes back `partial`, its `dead_letter` breakdown is
the input a success-with-warnings policy (roadmap §1.6) would need. No change to
D4 or the status logic here (out of scope).

## S4 — Terminal status + failure characterization

<!-- S4 -->

## S5 — Daily-schedule sizing recommendation

Measured this run (summer, low-fixture window):

| Dimension | Observed | vs limit |
|---|---|---|
| API calls / run | ~2,021 | 2.7 % of 75000 daily quota (~37× margin) |
| Wall-clock / run | ~11m45s (9m bronze + 2m44s projection) | fits any daily slot |
| Peak req/min | ~218/min avg | under the 240/65s cap; limiter enforced, no blow-through |
| Projection | ~164 s, 42,399 rows, no OOM | memory bounded by 0004 streaming |

**Recommendation — one full run/day is comfortably feasible.**

- **Quota:** even a peak-season estimate — Phase B scales with recent fixtures;
  381 fixtures here could be ~3–5× higher when most leagues are mid-season, i.e.
  ~1,200–2,000 fixtures → ~1,232 (Phase A) + ~2,400–4,000 (Phase B) ≈ **3.6k–5.2k
  calls/run**, still only ~5–7 % of the 75000 quota. One run/day has a large
  margin; several/day would still fit.
- **Duration:** ~12 min now; a peak run scales mainly on Phase B calls at the
  240/min cap → est. **~25–30 min**. Fine for an off-peak (e.g. 02:00) slot
  (which is where the existing `ingestor-scheduler` cron already runs it).
- **Rate limit / concurrency:** `240/65s` is adequate; the run rode near it
  (~218/min) without throttling problems. The bottleneck is the rate limiter, not
  `thread_pool_size` (8). The Ultra plan likely permits a higher per-minute rate —
  raising `RATE_LIMIT_PER_MIN` would shorten wall-clock if desired, but is **not
  required**.
- **Projection freshness caveat (ties to S4):** the projection refreshes only on
  a `succeeded` run (D4). A full run *can* come back `partial` on a day with even
  one un-recovered failure, which would skip that day's refresh (prior snapshot
  stands). If daily projection freshness must be guaranteed, the deferred
  **partial-tolerance / success-with-warnings** policy (roadmap §1.6) is the
  lever — sequenced after this run's data, as intended.

## S6 — Hermetic gates (control, Python 3.12)

Run in a **Python 3.12.10** venv (`.venv312`, `pip install -e .[dev]`) — the
repo's default `.venv` is 3.10, so a 3.12 env was built to match the production
target. No source changed this task (diff is evidence-only), so this is a control.

```
$ ruff check .            -> All checks passed!   (exit 0)
$ mypy src                -> (exit 0)
$ TEST_DB_DSN=…@localhost:5434/ingestor  pytest -q
  87 passed, 1 xfailed in 15.17s              (exit 0, zero skips)
```

The one `xfail` is the intentional placeholder. Gates green on the unchanged
commit under Python 3.12.

---

## Summary

| Step | Result |
|---|---|
| S1 full run | ✅ run `1f814136` **`succeeded`**, **1231 leagues**, 381 fixtures, bronze ~9m, wall-clock ~11m45s |
| S2 quota | ✅ ~2,021 calls (~2.7% of 75000); `/status` 5094/75000 today; ~218/min avg under cap |
| S3 projection | ✅ refreshed to **42,399** events, ~164 s, **no OOM** (0004 payoff); D3/D6 contract holds at scale |
| S4 status/failures | ✅ `succeeded`, **0 `dead_letter` this run**; 29 transient HTTP-200-with-errors all retried clean |
| S5 sizing | ✅ one run/day feasible, ~37× quota margin, ~12 min; partial-tolerance flagged as follow-up |
| S6 gates | ✅ ruff+mypy exit 0; pytest 87 passed / 1 xfail / 0 skips (Python 3.12) |

**Outcome:** the unbounded catalogue run completes cleanly, refreshes the
projection at full scale within memory (0004), and costs ~2.7 % of daily quota in
~12 min — a daily schedule is comfortably feasible. No production code changed;
no defect surfaced (no crash, no bronze corruption, no OOM, no quota
blow-through). The only forward-looking item is the deferred **partial-tolerance
policy** (S4/S5), which needs a future `partial` run's numbers as input.

## S6 — Hermetic gates (control, Python 3.12)

<!-- S6 -->
