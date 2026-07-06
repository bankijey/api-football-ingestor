# 0007 — Scheduler redeploy: deployed AND verified

Operational evidence log for task
`specs/coordinator/tasks/0007-scheduler-redeploy.md`. Every command was run on
the **deployment host** against the real API key (env only). Timestamps are
Berlin (Europe/Berlin) unless a captured line shows UTC. DSNs are
password-redacted; no secrets appear in this file.

**Headline:** the deployed 2am cron (`docker compose run --rm ingestor ingest`,
[docker-compose.yml:71](../docker-compose.yml)) has **no build step**, so it
runs whatever `api-football-ingestor:latest` already is on the host. This task
rebuilds `:latest` from current source and proves an **autonomous, crond-fired**
run of the rebuilt image reaches `succeeded` and refreshes `apifootball_events`
in the sources DB — the "deployed AND verified" gate.

---

## Host topology (for correlation)

| Role | Container | DSN (redacted) |
|------|-----------|----------------|
| Bronze DB (source of `bronze_fixtures`) | `ingestor-postgres` | `postgresql://ingestor:<redacted>@localhost:5434/ingestor` |
| Sources DB (target of `apifootball_events`, D5) | `arbibet-scraper-postgres-1` | `postgresql://postgres:<redacted>@host.docker.internal:5433/Arbibet` |
| Live scheduler | `ingestor-scheduler` (`docker:27-cli`) | crond, crontab `0 2 * * *` |

The sources DB is the scraper-shared `Arbibet` DB on host port 5433 — the same
DB the matcher reads, per D5 (the ingestor writes the projection *into* the
matcher's DB rather than being JOINed across DBs).

---

## D1 — Rebuild `:latest` from current source

`make build` → `docker compose --profile cli build ingestor`
([Makefile:28](../Makefile)).

- Build START: `2026-07-06 17:03:48` (UTC label GMT) — END `2026-07-06 17:04:53`. Exit 0.

**Proof the rebuilt image carries the projection code** (a pre-0001 image does
not):

```
$ docker run --rm --entrypoint python api-football-ingestor:latest \
    -c "import ingestor.projection; print('projection present')"
projection present
IMPORT_EXIT=0
```

**Rebuilt image metadata** (`docker image inspect`):

```
ID=sha256:d764187325a281bdece4e95e5318045e8379e8f9018d73b3b17387fcaef045ed
Created=2026-07-06T17:04:51.559581181Z
```

(For contrast, the pre-rebuild `:latest` was
`sha256:12782649a7cafb017a6899190ca9512160a758e323f5c75a5189e36ebaa43ab0`,
Created `2026-07-06T16:03:49Z` — itself a *manual* `make ingest` rebuild from
0005; the point of F2 is that the **cron path never rebuilds**, so on a host
where no manual run happened it would still be pre-0001.)

---

## D2 — The live scheduler (and why it drifts)

Production trigger on this host is the compose **`scheduler` cron service**
(`ingestor-scheduler`, image `docker:27-cli`,
[docker-compose.yml:40](../docker-compose.yml)), running for 6 days, with the
production crontab:

```
$ docker exec ingestor-scheduler crontab -l
0 2 * * * docker compose -f /workspace/docker-compose.yml run --rm ingestor ingest >> /var/log/ingest.log 2>&1
```

The cron command is `docker compose run --rm ingestor ingest` — **no `build`**.
The alternative Windows path ([scripts/run-ingest.ps1](../scripts/run-ingest.ps1))
also only does `docker compose ... run` with no build. **Neither rebuilds
`:latest` before running** — this is the systemic drift flaw (hand-off to 0008
below).

**Direct evidence of the drift's effect:** the scheduler's own
`/var/log/ingest.log` contains **20 prior `succeeded` runs and ZERO
`projection.built` lines** — every historical scheduled run ran a stale,
pre-projection image, so production had never autonomously refreshed
`apifootball_events`:

```
$ docker exec ingestor-scheduler sh -c "grep -c 'projection.built' /var/log/ingest.log"   # → 0
$ docker exec ingestor-scheduler sh -c "grep -o '\"status\": \"[a-z]*\", \"counters\"' /var/log/ingest.log | sort | uniq -c"
     20 "status": "succeeded", "counters"
```

---

## Pre-trigger baseline (BEFORE the autonomous run)

Captured `2026-07-06 17:05:54` (GMT label):

```
-- bronze ingestion_runs, latest (all pre-existing, newest = 0005's manual run):
run_id      | 1f814136-e56a-4c08-be9c-804281d4b5e7
status      | succeeded
started_at  | 2026-07-06 16:05:07.114934+00
finished_at | 2026-07-06 16:14:08.335063+00

-- sources DB apifootball_events (from 0005):
 rows  |       max_start        |       min_start
 42399 | 2027-06-06 15:00:00+00 | 2026-07-06 16:30:00+00
```

So any run whose `finished_at` is **after ~17:06 UTC** and any
`apifootball_events` refresh **after** this point is attributable to the new
autonomous trigger, not 0005.

---

## D3 — Autonomous trigger (scheduled, NOT manual)

The crontab inside the **running** scheduler container was temporarily rewritten
to fire at the next minute in container-local time (Europe/Berlin). Container
clock at arm time: `2026-07-06 19:06:15 CEST` (= 17:06 UTC).

```
# crontab BEFORE (production):
0 2 * * * docker compose -f /workspace/docker-compose.yml run --rm ingestor ingest >> /var/log/ingest.log 2>&1

# crontab AFTER (near-future test — fires 19:08 CEST):
8 19 * * * docker compose -f /workspace/docker-compose.yml run --rm ingestor ingest >> /var/log/ingest.log 2>&1
```

Trigger armed at `2026-07-06 17:06:58` (GMT). Log baseline: 83512 lines (the new
run appends beyond this). **No `make ingest` / `docker compose run` was invoked
by hand** — `crond` fires the exact production command.

### D3 result — TWO consecutive autonomous runs, both `partial` (BLOCKED)

Both runs were fired by `crond` (not a manual `make ingest`) and appended to the
scheduler's own `/var/log/ingest.log` — proof they were autonomous. Both came
back **`partial`**, so per D4 the projection is gated off and never refreshed.

| Trigger | run_id | fired (Berlin) | finished (UTC) | status | Phase-A failed | projection.built |
|---------|--------|----------------|----------------|--------|----------------|------------------|
| 1st (cron 19:08) | `c7f82ae2-99b8-4a67-b2cd-bec1cce34154` | 19:08:02 CEST | 2026-07-06 17:18:01 | **partial** | 3 | none |
| 2nd (cron 19:21, re-trigger) | `4befe5d5-0bac-476b-a6e1-81183ee24280` | 19:21:19 CEST | 2026-07-06 17:31:17 | **partial** | 9 | none |

`run.done` lines (from the scheduler log):

```
{"status": "partial", "counters": {"leagues_total": 1231, ... "phase_a": {"ok": 5, "unchanged": 1223, "failed": 3}, "phase_b": {"ok": 12, "unchanged": 738, "failed": 0}}, "event": "run.done", "run_id": "c7f82ae2-...", "timestamp": "2026-07-06T17:18:01.536243Z"}
{"status": "partial", "counters": {"leagues_total": 1231, ... "phase_a": {"ok": 4, "unchanged": 1218, "failed": 9}, "phase_b": {"ok": 8,  "unchanged": 742, "failed": 0}}, "event": "run.done", "run_id": "4befe5d5-...", "timestamp": "2026-07-06T17:31:17.599851Z"}
```

**Every failure is a transient HTTP 429** (rate-limit), classified
`RetryableHttpError`, on the `fixtures_by_league` (Phase A) endpoint. From
`dead_letter`:

```
-- run c7f82ae2 (3 failures): leagues 503, 813, 1049 — all "retryable client error 429" http_status=429
-- run 4befe5d5 (9 failures): fixtures_by_league | RetryableHttpError | retryable client error 429 | 429 | 9
```

Per the D3 protocol: the 1st partial → re-trigger **once** (done); the 2nd was
**also** partial (in fact worse: 9 vs 3), i.e. **systematically `partial`**. That
is the defined **STOP-and-escalate** condition. The partial-tolerance policy that
would let a `partial` run still refresh the projection is explicitly a **later
task** (Out of scope), so the implementor does not decide it here.

### D4 — projection was correctly NOT refreshed (gate works; DoD gate NOT met)

- Zero `projection.built` lines across both autonomous runs.
- `apifootball_events` is **unchanged**: still `42399` rows, `max_start
  2027-06-06 15:00:00+00`, `min_start 2026-07-06 16:30:00+00` — byte-for-byte the
  pre-trigger 0005 snapshot.

This is the D4 gate behaving **exactly as designed**: a non-`succeeded` run
leaves the prior snapshot untouched (all-or-nothing — the matcher never sees a
half-written table). The *mechanism* is proven correct. What is **not** met is
the task's "deployed AND verified" gate — namely a **`succeeded`** autonomous run
that **refreshes** the projection — because the autonomous full-catalogue run is
systematically `partial` on 429s in this window.

### D5 — schedule restored

```
# crontab restored to production (confirmed via `docker exec ingestor-scheduler crontab -l`):
0 2 * * * docker compose -f /workspace/docker-compose.yml run --rm ingestor ingest >> /var/log/ingest.log 2>&1
```

Restored `2026-07-06 17:33:27` (GMT). `ingestor-scheduler` left running (`Up`),
as production expects. The near-future test crons (`8 19 …`, `21 19 …`) are gone.

---

## Status: BLOCKED — escalated to coordinator

- **D1 met**: `:latest` rebuilt (`d764187325a2`, Created `2026-07-06T17:04:51Z`);
  import-check `ingestor.projection` exit 0.
- **D2 met**: live scheduler identified (`ingestor-scheduler` compose cron); it
  does not rebuild before running.
- **D3/D4 NOT met**: two consecutive autonomous runs were `partial` (3 then 9
  transient 429s), so the projection never refreshed. The DoD's "scheduled run
  reaches `succeeded` and refreshes `apifootball_events`" gate cannot be
  satisfied under the current partial-on-429 behaviour.
- **D5 met**: schedule restored.

Escalation note: [specs/implementor/notes/0007-scheduler-redeploy.md](../specs/implementor/notes/0007-scheduler-redeploy.md).

---

## Hand-off to 0008 (systemic drift — AC6)

The scheduled path **never rebuilds `:latest`** before running: the cron command
is `docker compose run --rm ingestor ingest` (no `build`;
[docker-compose.yml:71](../docker-compose.yml)), and `scripts/run-ingest.ps1`
likewise only `run`s. So after any code change the 2am run silently executes a
**stale image** — this is the root cause of finding F2 (production ran pre-0001
code for 20 prior `succeeded` runs, all with zero `projection.built`). **0008
(daily scheduling) owns the anti-drift redeploy strategy** — rebuild-on-cron vs
registry-pull vs CI/CD. Do NOT patch `docker-compose.yml`/`Dockerfile` inside
0007 (out of scope). Rebuilding `:latest` by hand (D1) papers over it only until
the next code change.

