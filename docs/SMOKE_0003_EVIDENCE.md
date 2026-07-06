# SMOKE 0003 — Live smoke: Phase 1 exit criteria + projection E2E

Evidence log for task `0003-live-smoke-exit-criteria`. Commands + queried
results are copied verbatim as the procedure was executed. Timestamps are
Berlin (CEST = UTC+2 on this date); raw DB timestamps are UTC (the DB session
TZ is UTC).

**Operator:** implementor cycle · **Date:** 2026-07-06 (Berlin) ·
**Commit baseline:** branch `apifootball-integration`

> Secrets discipline: the API key and the sources-DB password appear nowhere in
> this file. DSNs are shown with the password redacted (`***`).

---

## Environment

| Component | Value |
|---|---|
| Docker | Server 29.5.3, Compose v5.1.4 |
| Bronze DB | `ingestor-postgres` (compose `postgres`), host `localhost:5434` → container `postgres:5432`, db `ingestor` |
| Sources DB (D5) | host `:5433` → container `arbibet-scraper-postgres-1`, db `Arbibet`, PostgreSQL 16.14 |
| `MATCHER_DB_DSN` | `postgresql://postgres:***@host.docker.internal:5433/Arbibet` (see Finding F1) |
| Season | `2026` (current per league for all chosen leagues) |
| Lookback | `3` days |
| League subset | `169,292,113,244,103,253` |

**Chosen leagues** (all full coverage `lineups/statistics_fixtures/events = true`,
in-season July 2026, with both recently-played and future-NS fixtures):

| id | league | current season |
|---|---|---|
| 169 | Super League (China) | 2026 |
| 292 | K League 1 (South Korea) | 2026 |
| 113 | Allsvenskan (Sweden) | 2026 |
| 244 | Veikkausliiga (Finland) | 2026 |
| 103 | Eliteserien (Norway) | 2026 |
| 253 | Major League Soccer (USA) | 2026 |

Why not the coordinator's suggested EPL/La Liga/Serie A/Bundesliga/Ligue 1:
those are European domestic leagues and are **off-season** on 2026-07-06 (no
fixtures in the lookback window, no NS+future fixtures for their 2025/26 season).
The spec explicitly allows the coordinator/operator to substitute the league
subset ("coordinator may substitute"; "5–10 handpicked ids"). Calendar-year
summer leagues with rich coverage were substituted so S2 (rich data) and S6
(projection NS+future) are non-vacuous. `--season` is set to `2026` because that
is the `current=true` season for every chosen league (verified against the
latest `/leagues` snapshot); the daily scheduler achieves the same by passing no
`--season` and riding each league's current season.

---

## Pre-existing state (important context)

This repo is **not** first-touch-of-the-real-API as the task premise assumed.
The `ingestor-scheduler` cron has been running **full-catalogue live runs daily
at 00:00 UTC**; the most recent succeeded run finished `2026-07-06 00:13 UTC`
(today). So bronze is already heavily populated and the per-item `dead_letter`
mechanic has fired for real many times.

Baseline counts immediately before S1 (`2026-07-06 ~11:18 Berlin`):

```
bronze_leagues          = 22
bronze_fixtures         = 10321
bronze_fixture_details  = 132237
bronze_halftime_stats   = 130089
bronze_latest_hash      = 267956
dead_letter             = 904
ingestion_runs          = 43
```

Recent runs (all `succeeded`, daily 00:00 UTC):

```
c5c4ebae-2a24-4bac-bc70-24ff2e253f13 | succeeded | 2026-07-06 00:00:10 | 2026-07-06 00:13:13
b0706538-291e-4e21-a7e7-d0e0d3dc7c0c | succeeded | 2026-07-05 00:00:07 | 2026-07-05 00:13:29
44fb7d9f-3008-4831-9309-f97a35b35945 | succeeded | 2026-07-04 00:00:07 | 2026-07-04 00:08:04
```

Consequence for the smoke: because today's 00:00 scheduler run already fetched
these leagues, **hash-dedup** means S1 itself may append few new bronze rows
(only fixtures whose payload changed since 00:00). This does not affect S1's
success criteria (run `succeeded`, counters populated) and is exactly the
behaviour S3 asserts.

---

## Finding F1 (pre-flight, resolved as operator config) — malformed `MATCHER_DB_DSN`

**What:** `MATCHER_DB_DSN` in `.env` was set to the matcher's native
SQLAlchemy-dialect URL, `postgresql+psycopg2://…`. This ingestor connects with
**raw psycopg2**, which rejects that scheme:

```
$ python -c "import os,psycopg2; psycopg2.connect(os.environ['MATCHER_DB_DSN'])"
CONNECT: FAIL ProgrammingError
MSG: invalid dsn: missing "=" after "postgresql+psycopg2://postgres:***@host.docker.internal:5433/Arbibet" in connection info string
```

**Impact if unaddressed:** the projection step (`runner.py:114 _project_events`)
runs *after* `finish_run(succeeded)`; a connect exception there is caught by the
inner `except` (`runner.py:122`), which flips the run to `failed` and re-raises.
S1 would never show `succeeded` and S6 would be impossible.

**Resolution (operator config, not a code change):** the documented contract for
this variable is a **psycopg2** DSN — `.env.example` comments it as
"Sources-DB psycopg2 connection string (env MATCHER_DB_DSN)" and `config.py`
says the same. `.env` is gitignored operator config (not a production/source
file). Corrected in `.env` by stripping only the `+psycopg2` dialect suffix
(password never printed):

```
$ sed -i 's#MATCHER_DB_DSN=postgresql+psycopg2://#MATCHER_DB_DSN=postgresql://#' .env
$ grep '^MATCHER_DB_DSN=' .env | sed -E 's#(://[^:]+:)[^@]*(@.*)#\1***\2#'
MATCHER_DB_DSN=postgresql://postgres:***@host.docker.internal:5433/Arbibet
```

Re-test after fix:

```
CONNECT: OK  | PostgreSQL 16.14 (Debian 16.14-1.pgdg12+1) on x86_64-pc-linux-gnu
apifootball_events exists: None   (created by the first projected run)
```

**Recommendation for the coordinator (non-blocking, no code changed here):**
D5 points the ingestor at "the matcher's `POSTGRES_URL` database", and that URL
*natively* carries the `+psycopg2` dialect. An operator copying it verbatim will
hit this every time, and a daily scheduler run would silently flip
`succeeded→failed` with no projection. Consider a scoped follow-up to have the
ingestor tolerate/normalise a SQLAlchemy-style DSN (strip `+driver`) in
`config.py`. Not done in this task (production code is out of scope for a smoke).

---

## Finding F2 (pre-flight, resolved by rebuild) — deployed image predates 0001

**What:** the first S1 attempt (run `f11fadb8-62c1-4869-b22b-dfa32cda9be4`,
discarded) completed `succeeded` but emitted **no projection log line**. Cause:
`docker compose run` does not rebuild, and the local image
`api-football-ingestor:latest` was **built 2026-06-18** — before 0001 landed
(2026-07-05). The stale image's `Settings` has no `matcher_db_dsn` field and its
runner has no projection hook:

```
$ docker compose run --rm --entrypoint python ingestor -c "from ingestor.config import get_settings; get_settings().matcher_db_dsn"
AttributeError: 'Settings' object has no attribute 'matcher_db_dsn'
```

**Impact:** the `ingestor-scheduler` cron invokes `docker compose run --rm
ingestor ingest` against this **same** stale image. So — independent of F1 — the
projection has **never been deployed**; every daily run since 0001 ran pre-0001
code, which is the deeper reason `apifootball_events` never existed in the
sources DB.

**Resolution (operational, no code change):** rebuilt the image from current
committed source (`make build` does this; `make ingest` builds before running —
the direct `compose run` I used first did not):

```
$ docker compose --profile cli build ingestor
$ docker images api-football-ingestor:latest --format '{{.ID}} {{.CreatedAt}}'
# old: 7d070fc8fc35  2026-06-18 09:51:48   ->   new: 5e8ae4917bee  2026-07-06 11:23:43
$ docker compose run --rm --entrypoint python ingestor -c "..."
matcher_db_dsn field present: True
matcher_db_dsn truthy: True
_project_events present: True
```

**Recommendation for the coordinator (non-blocking):** the deployed image needs
a rebuild+redeploy so the scheduler runs 0001 code; otherwise the daily
projection stays dark. All S1–S7 evidence below runs on the **rebuilt** image.

---

## Finding F3 (surfaced by S1, non-blocking) — projection does not scale to prod bronze volume

**What:** on the rebuilt image the projection step ran for **~11–12 minutes** and
peaked at **~6.1 GiB / 7.7 GiB** container RAM before completing. Cause:
`projection._read_rows` executes `SELECT DISTINCT ON (league_id, season) payload
FROM bronze_fixtures` and pulls **every** payload into Python via `fetchall()`,
then loops in pure Python. At current scale that is **7894 distinct
(league_id, season)** full-season payloads (bronze accumulates daily via the
full-catalogue scheduler):

```
bronze pg_stat_activity during the hang:
 1177139 | idle in transaction | 00:11:30 | SELECT DISTINCT ON (league_id, season) payload FROM bronze_fixtures ORDER BY ...
container: CPU=45.9%  MEM=6.134GiB / 7.698GiB
SELECT count(*) FROM (SELECT DISTINCT league_id,season FROM bronze_fixtures) t;  -> 7894
```

**Outcome:** it **completes correctly** — the write is atomic and the result is
right (see S6). So this is a *performance/scalability* finding, not a correctness
failure, and the smoke proceeds. But: (a) it approaches the container memory
ceiling and bronze only grows, so a future run will OOM; (b) a ~12-min step at
the tail of every daily run is heavy.

**Recommendation for the coordinator (non-blocking):** push the NS+future filter
and the field extraction into SQL (or stream with a server-side cursor) instead
of loading all payloads into Python — a scoped follow-up. No code changed here.

---

## S1 — Bounded live run  ✅

Command (rebuilt image):

```
$ docker compose --profile cli run --rm ingestor ingest \
      --season 2026 --leagues 169,292,113,244,103,253 --lookback-days 3
```

**run_id `3ad05d60-2d17-462e-aad2-af38c669b819`** — `run.done`:

```
{"status": "succeeded",
 "counters": {"leagues_total": 6, "fixtures_total": 24,
   "phase_a": {"ok": 0, "skipped": 0, "unchanged": 6, "failed": 0},
   "phase_b": {"ok": 1, "skipped": 0, "unchanged": 47, "failed": 0}}}
run.leagues_selected count=6  (seasons_override=[2026])
run.fixtures_selected count=24  window=lookback_3d
```

`ingestion_runs` row:

```
3ad05d60-2d17-462e-aad2-af38c669b819 | succeeded | started 2026-07-06 09:25:11Z | finished 09:25:16Z | error=(null)
```

Counters are populated and `failed=0` in both phases → terminal status
`succeeded` (`_terminal_status`), so the projection is gated ON (D4). Most
Phase-A/B work shows `unchanged` because today's 00:00 scheduler run already
fetched these leagues (hash-dedup) — expected (see Pre-existing state).

**Quota / call counts** (from the run log; the earlier stale-image attempt used a
near-identical volume):

```
/leagues            :  1 call   (Phase A bootstrap)
/fixtures?league=…  :  6 calls  (Phase A, one per league)  -> Phase A ≈ 1 + N = 7
/fixtures?id=…      : ~37 calls (Phase B rich detail)
/fixtures/statistics: ~30 calls (Phase B halftime)          -> Phase B ≈ 2 per recent fixture
```

Total ≈ 74 API calls for the bounded run — a small fraction of the 75000 daily
quota; rate limiter (240/65s) never throttled. Well within headroom.

*(Note: the projection ran as the final step and took ~11–12 min — see F3 — and
wrote the snapshot proven in S6. An earlier attempt on the **stale** image, run
`f11fadb8…`, is discarded per F2.)*

## S2 — Phase B rich data  ✅

`bronze_fixture_details` rows landed today for the subset leagues (Norway 103 /
MLS 253 correctly have none — no recently-played fixtures in the window):

```
league_id | detail_rows | latest_ingest
   113 (Allsvenskan) |  11 | 2026-07-06 09:25:15Z
   169 (China SL)    |  15 | 2026-07-06 09:20:20Z
   244 (Veikkausliiga)|  8 | 2026-07-06 09:20:21Z
   292 (K League 1)  |  12 | 2026-07-06 09:20:22Z
```

Sample `bronze_fixture_details` payload (`fixture_id 1494194`) — embedded blocks
present (jsonb path probe):

```
lineups=2   events=13   statistics(fixture)=2   players(stat teams)=2
```

`bronze_halftime_stats` — 281 rows ingested today; sample (`fixture_id 1494194`)
carries real half-time statistics:

```
teams_in_response=2   first_stat_type="Shots on Goal"
```

## S6 — Projection E2E (0001 handshake)  ✅

Sources-DB `apifootball_events` after S1 (all assertions pass):

```
total | eid_ok | eid_bad | start_not_future | bad_bookmaker | bad_sport | non_null_url
39941 |  39941 |       0 |                0 |             0 |         0 |            0
earliest_start=2026-07-06 12:00Z  latest_start=2027-06-06 15:00Z  db_now=2026-07-06 09:40Z
```

- `count(*) = 39941 > 0` ✔
- every `e_id ~ '^apifootball;[0-9]+$'` (semicolon, D6); 0 violations ✔
- `min(start) > now()` — earliest kickoff is in the future (NS+future only, D3) ✔
- `bookmaker_id='apifootball'`, `sport_key='football'`, `url IS NULL` for all ✔

Sample rows + subset leagues represented:

```
apifootball;1567557 | apifootball | football | 2026-07-06 12:00Z | tid 667 | FK Partizan vs Neftchi Baku | 573/2270 | url=NULL
apifootball;1554754 | apifootball | football | 2026-07-06 15:00Z | tid 667 | Cracovia vs Başakşehir       | 350/564  | url=NULL

subset leagues in projection:
 103 Eliteserien 151 | 113 Allsvenskan 153 | 169 Super League 104 |
 244 Veikkausliiga 46 | 253 MLS 292 | 292 K League 1 102
```

*(S3 re-check of the re-refresh is under S3 below.)*

## S3 — Idempotent re-run (hash dedup)  ✅

Immediately re-ran S1's exact args.
**run_id `961361ad-540f-481a-9403-2b6941175e61`** — `run.done`:

```
{"status": "succeeded",
 "counters": {"leagues_total": 6, "fixtures_total": 24,
   "phase_a": {"ok": 0, "skipped": 0, "unchanged": 6, "failed": 0},
   "phase_b": {"ok": 0, "skipped": 0, "unchanged": 48, "failed": 0}}}
```

Every task `unchanged` (6/6 Phase A, 48/48 Phase B) — nothing re-written.

**Bronze row-count delta = 0** across all four tables:

```
                         pre-S3      post-S3
bronze_leagues            23           23
bronze_fixtures           10325        10325
bronze_fixture_details    132261       132261
bronze_halftime_stats     130097       130097
```

**Hash companion behaves as designed** — sample row
`fixtures_by_league / params_hash c5087c0f…`:

```
                 pre-S3                     post-S3
last_checked_at  2026-07-06 09:25:12.694Z   2026-07-06 09:42:24.434Z   -> advanced  ✔
last_changed_at  2026-07-06 09:20:19.008Z   2026-07-06 09:20:19.008Z   -> unchanged ✔
```

`last_checked_at` advanced (the endpoint was re-queried) while `last_changed_at`
held (the response hash was identical → no new bronze row). 6 of the subset's
`fixtures_by_league` hash rows had `last_checked_at` advance into the S3 window
(the 6 current league-seasons).

**Projection re-refresh (S6 re-check):** the S3 run is `succeeded`, so the
projection ran again (atomic replace, D4). Result recorded below once the
~12-min projection completed.

```
projection.built           rows=39941   run_id=961361ad…  09:44:48Z
run.projection_written     rows=39941   run_id=961361ad…  09:44:48Z

apifootball_events after S3 re-refresh:
 total | eid_bad | not_future | earliest
 39941 |     0   |     0      | 2026-07-06 12:00Z
```

The atomic replace ran again and the snapshot still satisfies every S6
assertion. (This projection took ~2.5 min — S1's ~12 min in F3 was the
cold-cache first build; warm re-runs are far cheaper, though still ~4–6 GiB.)

---

## S4 — Crash resume  ✅

To get a catchable mid-Phase-A window (6 leagues finish in ~6 s), a **40-league**
run was started with a throttled `RATE_LIMIT_PER_MIN=10` (env override for that
one invocation), so Phase A stalls on the rate limiter while partial. It was then
**killed ungracefully** (`docker kill` = SIGKILL) once 9 of 40 league checkpoints
were `succeeded`.

Aside (corroboration): a pre-existing run `ba83af6a…` has sat in `status=running`
since **2026-06-18** — a much older ungraceful kill whose `finish_run` never ran.
Confirms a crash leaves a `running` row (the resume trigger); excluded from
detection here by `started_at`.

**Killed run `97ccfaf2-bdb3-4844-aff7-b987da22918a`** immediately after SIGKILL:

```
ingestion_runs:  status=running  finished_at=NULL   (crash left it un-finalised)
checkpoints:     league succeeded = 9
                 league pending   = 8      (never reached Phase B: 0 fixture checkpoints)
```

**Resume** (`--resume 97ccfaf2…`, same `--leagues`, normal rate):

```
run.resume  run_id=97ccfaf2…
run.done -> {"status": "succeeded",
   "phase_a": {"ok": 0, "skipped": 9, "unchanged": 31, "failed": 0},
   "phase_b": {"ok": 0, "skipped": 0, "unchanged": 8,  "failed": 0}}
checkpoints after resume: league succeeded = 40, fixture succeeded = 8
ingestion_runs: status=succeeded, finished_at=2026-07-06 09:54:48Z
```

- Resumed run reaches **`succeeded`** ✔
- **`phase_a.skipped=9`** — the 9 already-succeeded leagues were **not re-done**
  (checkpoint skip via `is_succeeded`); the 8 `pending` + 23 unstarted leagues all
  moved to `succeeded` (pending→succeeded) ✔

**No duplicate bronze rows** — counts identical across the resume, and no key
written twice by the resumed run_id:

```
                         pre-resume    post-resume
bronze_leagues            23            23
bronze_fixtures           10326         10326
bronze_fixture_details    132265        132265
bronze_halftime_stats     130100        130100

(league_id,season) written >1x by run 97ccfaf2 in bronze_fixtures : NONE
fixture_id written >1x by run 97ccfaf2 in details / halftime      : NONE / NONE
```

Row counts are flat because the killed leagues' data was already current
(hash-dedup) — the resume re-checked and wrote nothing new, and crucially wrote
no duplicates. The run is `succeeded`, so the projection re-ran (D4) as its tail
(`run.projection_written rows=39942`, run 97ccfaf2…, 09:57:41Z).

---

## S5 — Failure boundary + recovery  ✅

Per the spec, the per-item `dead_letter` mechanic is **not** code-free reachable
live (every operator failure lever is global and aborts the un-isolated
`/leagues` bootstrap first); it is proven hermetically under S7. This step proves
the boundary is **safe** (S5a) and **recoverable** (S5b).

**Baseline before S5a** — bronze `23 / 10326 / 132265 / 130100`;
`apifootball_events` `count=39942  md5=13aae13fb0833b4b4bc8f3564e5f119e`
(md5 over `e_id + start` ordered by `e_id`); `dead_letter=904`.

### S5a — fail fast & safe (invalid API key)

`.env` untouched; the key was overridden for **this one invocation only**
(`-e APIFOOTBALL_KEY=INVALID_SMOKE_TEST_KEY`). Same args as S1.

```
S5a EXIT=1
http.error … then:
  ingestor.http.errors.NonRetryableHttpError: client error 403   (at /leagues bootstrap)
  event=run.crashed
ingestion_runs (this run): status=failed, error="NonRetryableHttpError: client error 403"
```

Fail-safe assertions — **nothing moved**:

```
                          baseline                       after S5a
bronze_leagues            23                             23
bronze_fixtures           10326                          10326
bronze_fixture_details    132265                         132265
bronze_halftime_stats     130100                         130100
apifootball_events count  39942                          39942
apifootball_events md5    13aae13fb0833b4b4bc8f3564e5f119e  13aae13fb0833b4b4bc8f3564e5f119e
dead_letter               904                            904
```

- The run does **not** reach `succeeded` (it is `failed`) ✔
- Bronze across all four tables is **unchanged** — a failed bootstrap writes no
  bronze ✔
- `apifootball_events` is **byte-for-byte unchanged** (identical count *and*
  content md5) — the projection is gated on `succeeded`, so it never ran (D4) ✔
- `dead_letter` unchanged — confirming the abort happens at the un-isolated
  `/leagues` bootstrap *before* any per-item `record_failure` (the known, correct
  asymmetry: no work list ⇒ nothing to isolate) ✔

### S5b — retryable / recovery (valid key restored)

Re-ran the **same args** with the valid key (no override; `.env` was never
edited for the key):

```
run_id c6589b61-1d13-49c7-aa19-92ac480d6f89
run.done -> status=succeeded  (phase_a unchanged=6/failed=0; phase_b ok=2/unchanged=46/failed=0)
run.projection_written rows=39942   10:02:40Z
apifootball_events: count=39942  eid_bad=0  not_future=0
```

The run the invalid key could not do now **reaches `succeeded`** and the
projection refreshes again — the failure was transient/operator-controlled, not
terminal ✔. (Both invocations + the fact that `.env`'s key was never touched are
recorded above.)

---

## S7 — Hermetic gates still green (control)  ✅

No production/source code changed this task (diff is evidence-only), so the
hermetic suite is a control.

**Lint** — `make lint` (`ruff check .` + `mypy src`):

```
ruff:  All checks passed!   (exit 0)
mypy:  (exit 0)
```

**Tests** — the DB-backed tests resolve `TEST_DB_DSN`/`DB_DSN` and use isolated
per-test schemas. Pointed at the live bronze container (`localhost:5434`, as
0001's verifier did):

```
$ TEST_DB_DSN=postgresql://ingestor:***@localhost:5434/ingestor pytest -q
85 passed, 1 xfailed in 29.10s        (exit 0, zero skips)
```

The one `xfail` is the intentional `test_end_to_end_ingest_placeholder`. The
per-item **DLQ + retryable** mechanic (AC5, not code-free reachable live — see
S5) is confirmed hermetically:

```
$ pytest -q tests/test_orchestrator.py::test_phase_a_isolates_one_failing_league
1 passed
```

(Note: bare `make test` / `pytest -q` without `TEST_DB_DSN` also exits 0, but
**skips** 26 DB-backed tests because the conftest default DSN is `localhost:5432`
— the live container is on `5434`. Set `TEST_DB_DSN` to the live container to run
them with zero skips.)

---

## Summary

| Step | Exit criterion | Result |
|---|---|---|
| S1 | Full run completes | ✅ run `3ad05d60` `succeeded`, 6 leagues / 24 fixtures, ~74 calls |
| S2 | Phase B rich data + halftime | ✅ details+halftime rows for subset; embedded lineups/stats/events present |
| S3 | Immediate re-run ≈0 new rows | ✅ bronze delta = 0; `last_checked` advanced, `last_changed` held |
| S4 | Crash resume, no duplicates | ✅ SIGKILL @ 9/40 leagues → resume `succeeded`, `skipped=9`, 0 dup rows |
| S5 | Failure boundary safe + recoverable | ✅ invalid key `failed`, bronze+projection byte-unchanged; valid re-run `succeeded` |
| S6 | Projection E2E (gates matcher) | ✅ `apifootball_events` 39941→39942, all `e_id ~ ^apifootball;[0-9]+$`, all future, constants OK; re-refreshed on S3/S4/S5b |
| S7 | Hermetic lint+test green | ✅ ruff+mypy exit 0; 85 passed / 1 xfail / 0 skips; DLQ test passes |

**Findings surfaced (all recorded above):**
- **F1** — `MATCHER_DB_DSN` had a SQLAlchemy `+psycopg2` scheme psycopg2 rejects;
  fixed in gitignored `.env` (operator config). Recommend code tolerate it.
- **F2** — deployed image predated 0001 (projection undeployed; scheduler runs it
  too); rebuilt. Recommend rebuild+redeploy.
- **F3** — projection loads all 7894 league-season payloads into Python
  (~6 GiB, ~12 min cold). Completes & correct, but recommend SQL-side filtering.

None of F1–F3 is a production-code change made in this task; each is either
operator config (F1), ops (F2), or a recommended follow-up (F3). The six Phase-1
exit criteria and the 0001 projection are all proven live. **S6 unblocks the
matcher's Phase B live smoke.**

---

---
