# 0008 — Daily scheduling: anti-drift redeploy, deployed AND verified

Operational evidence for task
[`specs/coordinator/tasks/0008-daily-scheduling.md`](../specs/coordinator/tasks/0008-daily-scheduling.md).
Every command was run on the **deployment host** against the real API key
(env only). Timestamps are Europe/Berlin (CEST) where a captured line shows the
container clock, UTC where a DB/log line shows UTC. DSNs are password-redacted;
no secret appears in this file.

**Headline:** the daily cron previously ran `docker compose run --rm ingestor
ingest` with **no build step**, so after any code change the 02:00 run silently
executed a stale image (0007 finding F2 — 20 prior `succeeded` runs, zero
`projection.built`). This task changes both trigger paths to **build-then-run**
(`run --build`) so the daily run is **self-currenting**, then proves an
**autonomous, crond-fired** run rebuilt `:latest` from source before running,
reached `succeeded`, and refreshed `apifootball_events`.

---

## AC1 — Static: build step in BOTH trigger paths

**`docker-compose.yml` `scheduler` cron command** — now `run --build`, schedule
and log redirect unchanged:

```
0 2 * * * docker compose -f /workspace/docker-compose.yml run --build --rm ingestor ingest >> /var/log/ingest.log 2>&1
```

**`scripts/run-ingest.ps1`** (Windows Task path) — same `run --build`:

```
run --build --rm --profile cli ingestor ingest --season 2025
```

Both trigger paths now rebuild the image from source before running; neither can
drift onto a stale image.

## AC2 — Compose valid + scheduler recreated

```
$ docker compose --profile scheduler --profile cli config   # → exit 0
$ docker compose --profile scheduler up -d --force-recreate scheduler
 Container ingestor-scheduler  Recreated / Started
$ docker exec ingestor-scheduler crontab -l
0 2 * * * docker compose -f /workspace/docker-compose.yml run --build --rm ingestor ingest >> /var/log/ingest.log 2>&1
```

The recreated scheduler baked in the new `run --build` command. (Recreating also
gave a fresh `/var/log/ingest.log`, so every line in it below is attributable to
this task's fire.)

---

## Pre-fire baseline (captured 2026-07-07 ~07:40 CEST / 05:40 UTC)

| Item | Value |
|------|-------|
| `:latest` image (pre-fire) | `sha256:d764187325a2…` Created **2026-07-06T17:04:51Z** (0007's rebuild) |
| Scheduler log | 0 lines (fresh after `--force-recreate`) |
| Bronze `ingestion_runs` latest | `ca4ca8dd-…` `succeeded` (today's 00:00 UTC real cron) |
| Sources `apifootball_events` | 42365 rows, `min_start 2026-07-07 00:30:00+00` |

**Subscription/quota probe** (`/status` — a meta endpoint that does NOT consume
quota), confirming a fire was worth attempting (no lapse, ample headroom):

```
subscription: {plan: Ultra, end: 2026-08-06T19:59:59+00:00, active: true}
requests:     {current: 4616, limit_day: 75000}      # ~6% used, ~70k free
```

Host topology (redacted) — same as 0007: bronze DB `ingestor-postgres`; sources
DB `arbibet-scraper-postgres-1` (the scraper-shared `Arbibet` DB, D5); live
scheduler `ingestor-scheduler` (`docker:27-cli`).

---

## AC3 / AC4 — Autonomous fire: built from source, succeeded, refreshed

### Armed state (self-disarming; recorded before arming for survive-teardown)
The **running** scheduler's crontab was rewritten to one near-future minute
(container-local Europe/Berlin), self-disarming back to production `0 2` after
the run. **No `make ingest` / hand `docker compose run` was invoked** — `crond`
fired the exact production command.

```
# Armed line (fires ONCE at 07:46 CEST, then restores production 0 2 --build):
46 7 * * * docker compose -f /workspace/docker-compose.yml run --build --rm ingestor ingest >> /var/log/ingest.log 2>&1; echo '0 2 * * * docker compose -f /workspace/docker-compose.yml run --build --rm ingestor ingest >> /var/log/ingest.log 2>&1' | crontab -

# Manual restore/disarm (if ever needed before the self-disarm runs):
echo '0 2 * * * docker compose -f /workspace/docker-compose.yml run --build --rm ingestor ingest >> /var/log/ingest.log 2>&1' | crontab -
```

Armed `2026-07-07 07:43:16 CEST`.

### The fire REBUILT `:latest` before running (AC3 — two independent proofs)

**Proof 1 — a build step precedes `run.done` in the scheduler's own log.** The
run's own `/var/log/ingest.log` opens with BuildKit output, `run.done` is ~3,690
lines later:

```
$ docker exec ingestor-scheduler date            # → 07:46:06 CEST (build start)
$ docker exec ingestor-scheduler grep -n 'load build definition from Dockerfile\|run.done' /var/log/ingest.log
6:#1 [ingestor internal] load build definition from Dockerfile
3696:{"status": "succeeded", … "event": "run.done", "run_id": "46bb4d05-…"}
```

**Proof 2 — `:latest` image `Created` advanced to fire time, no manual build.**
The tag moved off 0007's image onto a fresh one built at the fire:

```
$ docker image inspect api-football-ingestor:latest --format '{{.Id}} {{.Created}}'
# BEFORE: sha256:d764187325a2…  2026-07-06T17:04:51Z
# AFTER:  sha256:552d4a2874cb…  2026-07-07T05:47:12Z   ← rebuilt at fire time
```

Both hold — the scheduled path is now provably self-currenting; drift cannot
recur.

### The run succeeded and refreshed the projection (AC4)

**Autonomous & succeeded** (scheduler's own log; bronze `ingestion_runs`):

```
{"status": "succeeded", "counters": {"leagues_total": 1231, "fixtures_total": 274,
  "phase_a": {"ok": 53, "unchanged": 1178, "failed": 0},
  "phase_b": {"ok": 140, "unchanged": 408, "failed": 0}},
 "event": "run.done", "run_id": "46bb4d05-62fb-41b7-990c-0d039fd4feb3",
 "timestamp": "2026-07-07T05:55:11.493359Z"}

# ingestion_runs (bronze DB):
46bb4d05-62fb-41b7-990c-0d039fd4feb3 | succeeded
  started 2026-07-07 05:47:18Z | finished 2026-07-07 05:55:11Z
```

0 Phase-A and 0 Phase-B failures — the healthy quota bore out the `/status`
probe. `started_at` (05:47:18Z) is **after** the pre-fire baseline, so this run
is attributable to the new autonomous trigger.

**Projected** (same log, `run_id` correlated; ran ~103 s after `run.done` —
streaming bronze read → atomic swap):

```
{"rows": 43123, "event": "projection.built",       "run_id": "46bb4d05-…", "timestamp": "2026-07-07T05:56:54.572945Z"}
{"rows": 43123, "event": "run.projection_written", "run_id": "46bb4d05-…", "timestamp": "2026-07-07T05:56:54.595046Z"}
```

**Sources DB refreshed** (`apifootball_events`, correlated to THIS run — count
42365 → **43123**, `min_start` advanced 00:30 → 09:00 UTC as elapsed events
dropped out):

```
 rows  |       max_start        |       min_start
 43123 | 2027-06-06 15:00:00+00 | 2026-07-07 09:00:00+00
```

`43123` == `projection.built rows` == `run.projection_written rows` — the D6
contract (all-or-nothing atomic swap) holds.

**D6 column contract — all 43,123 rows pass every check:**

```
 total | eid_ok | bkmkr_ok | sport_ok | url_null_ok | future_ok
 43123 | 43123  |  43123   |  43123   |    43123    |   43123
-- eid_ok      : e_id ~ '^apifootball;[0-9]+$'   (semicolon delimiter, D6)
-- bkmkr_ok    : bookmaker_id = 'apifootball'
-- sport_ok    : sport_key = 'football'
-- url_null_ok : url IS NULL
-- future_ok   : start > now()
```

### Schedule restored (self-disarm confirmed)

```
$ docker exec ingestor-scheduler crontab -l
0 2 * * * docker compose -f /workspace/docker-compose.yml run --build --rm ingestor ingest >> /var/log/ingest.log 2>&1
```

The armed line self-disarmed to production `0 2 * * *` (**with `--build`**) after
the run — no manual restore needed. `ingestor-scheduler` left `Up`; production is
armed for the next 00:00-UTC run on the self-currenting command.

---

## D4 unchanged — projection still gated on `succeeded`

This task changed **no** `src/`, migration, or `DECISIONS.md` — only the cron
wrapper. The D4 gate (refresh only on `succeeded`) is untouched: this run
`succeeded`, so it refreshed; a `partial`/`failed` run would still leave the
prior snapshot intact (as 0007 proved). Bronze append-only untouched.

---

## FINAL STATUS: PASS — deployed AND verified ✅

| AC | Result |
|----|--------|
| **AC1** build step in both trigger paths | ✅ compose + `run-ingest.ps1` both `run --build` |
| **AC2** compose valid + scheduler recreated | ✅ `config` exit 0; `--force-recreate`; crontab reloaded |
| **AC3** autonomous run rebuilt `:latest` before running | ✅ build precedes `run.done` (log line 6 vs 3696) **and** image Created advanced d764→552d @ 05:47:12Z |
| **AC4** scheduled run `succeeded` **and** refreshed projection | ✅ `46bb4d05` succeeded; `projection.built rows=43123`; `apifootball_events`=43123; D6 43123/43123 |
| **AC5** `docs/OPS.md` (4 sections, expiry 2026-08-06) + README pointer | ✅ see `docs/OPS.md` |
| **AC6** `make lint` + `make test` exit 0 (control) | ✅ see below |
| **AC7** diff = §Files only | ✅ no `src/`/tests/migrations |
| **AC8** no secrets | ✅ DSNs redacted, key never printed |

## AC6 — Lint + test (control; zero Python changed)

```
$ ruff check .        # → All checks passed!  (exit 0)
$ mypy src            # → exit 0 (strict, no errors)
$ pytest -q           # → 87 passed, 1 xfailed in 32.31s
```

Unchanged from the 0007 baseline (87 passed / 1 xfail) — this task touched only
the cron wrapper, compose, docs, and the Windows script; no `src/`, tests, or
migrations. The single `xfail` is the long-standing end-to-end smoke placeholder.
