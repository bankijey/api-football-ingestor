# Operations runbook — API-Football bronze ingestor

The durable home for how the ingestor runs in production: what fires each day,
the subscription that keeps it alive, how to confirm a given day's run was
healthy, and the shared-quota caveat. Keep this current — it is the first thing
to read when a 02:00 run looks wrong.

> Scope: the **operational wrapper** around the daily run. The ingestion and
> projection logic itself is documented in `README.md` and `DECISIONS.md`.

---

## 1. Daily run

| Property | Value |
|----------|-------|
| **What fires** | The compose `scheduler` service — a long-lived `docker:27-cli` container (`ingestor-scheduler`) running `crond`. |
| **Schedule** | `0 7 * * *` — 07:00 daily (moved from 02:00 on 2026-09-21: 02:00 CEST = 00:00 UTC, the daily-quota rollover; see `docs/ingestion-failure-report.pdf`), in the container's `TZ` (`Europe/Berlin` on this host; the crontab minute/hour is local time). |
| **Command** | `docker compose -f /workspace/docker-compose.yml run --build --rm ingestor ingest >> /var/log/ingest.log 2>&1` |
| **Defined in** | [`docker-compose.yml`](../docker-compose.yml) — `scheduler.command` writes this crontab at container start. |

### Build-then-run (anti-drift)
The command carries `--build`: crond **rebuilds the `ingestor` image from the
`/workspace` source before every run**. The scheduler mounts the repo read-only
at `/workspace` and has the host docker socket, so it builds via the host daemon
with no extra plumbing.

This is deliberate. Before task 0008 the cron command was a bare
`docker compose run --rm ingestor ingest` with **no build step** — so after any
code change the 02:00 run silently kept executing a **stale image**. That is
exactly what happened before task 0001's projection code shipped: production ran
20 consecutive `succeeded` runs that never once refreshed `apifootball_events`
(zero `projection.built` lines) because the deployed image predated the
projection. `--build` makes the run **self-currenting** — drift cannot recur.
Cached builds are near-instant, so the cost when nothing changed is seconds.

**If you edit `docker-compose.yml`'s `scheduler.command`, recreate the service**
so it picks up the new crontab (it bakes the command in at start):
```bash
docker compose --profile scheduler up -d --force-recreate scheduler
docker exec ingestor-scheduler crontab -l    # confirm the new line loaded
```

The Windows Task Scheduler path ([`scripts/run-ingest.ps1`](../scripts/run-ingest.ps1))
carries the same `run --build` so **neither trigger can drift**.

### Sizing (from task 0005)
- **~12 minutes** wall-clock per run.
- **~2,000 API calls** per run ≈ **2.7 %** of the 75,000/day quota. One run/day
  was the validated cadence — see Out-of-scope in `specs/coordinator/tasks/0008`;
  do **not** raise the frequency without re-sizing.

### Projection refresh gate (D4)
The run's final step rebuilds the `apifootball_events` serving table in the
sources DB, **gated on `ingestion_runs.status = 'succeeded'`**. A `partial` or
`failed` run leaves the prior snapshot fully intact (all-or-nothing — the matcher
never sees a half-written table). So "the run fired" is **not** the same as "the
projection refreshed"; always confirm the status. See `DECISIONS.md` D4.

---

## 2. Subscription tracking

The ingestor is useless without an **active** API-Football subscription, and a
lapse does **not** announce itself as "subscription expired" — it surfaces as
**limit-type errors despite healthy quota** (see the signature below). Track the
renewal date as a calendar event so the next lapse is anticipated, not
diagnosed at 02:00.

| Property | Value |
|----------|-------|
| **Account** | the account owner (see API-Football dashboard) |
| **Plan** | `Pro` (was `Ultra` until 2026-08-06) |
| **Renewed** | ~2026-08-26 |
| **Expiry** | **2026-09-26** (from the `/status` probe, 2026-09-21) |
| **Daily quota** | 7,500 requests/day (`.env` DAILY_QUOTA still 75000 — must be lowered) |

### ⏰ Reminder: renew before **2026-09-26**
Set a calendar reminder a few days ahead. The plan `end` date is also readable
live from `/status` (see below) — it does not consume request quota.

### Lapse signature — recognise it next time
On 2026-07-06 the subscription lapsed mid-day and was renewed ~20:2x UTC. During
the lapse window, every full-catalogue run failed with **limit-type errors**:
- Phase-A calls rejected with **HTTP 429** (`fixtures_by_league`), and
- a bootstrap `/leagues` call rejected with an **in-body** message
  `"You have reached the request limit for the day"` (HTTP 200 + non-empty
  `errors` — the API quirk).

…**yet `/status` showed the plan active with ~88 % of the daily quota free.** A
limit rejection with large real headroom is the fingerprint of an **inactive
subscription**, not genuine rate-limiting. The first run after renewal, same key
and command, succeeded with **zero** failures. Full correlation table:
[`docs/DEPLOY_0007_EVIDENCE.md`](DEPLOY_0007_EVIDENCE.md) coordinator addendum.

> Do **not** react to a lapse by loosening the projection gate (D4) to tolerate
> `partial` runs — a billing event is not a genuine per-run failure rate. That
> path (task 0010) is deferred; D4 stays locked.

### Check subscription + quota live (`/status`)
`/status` is a meta endpoint — it returns plan state and today's request count
**without** consuming quota:
```bash
docker exec ingestor-scheduler sh -c \
  'wget -qO- --header="x-rapidapi-key: $APIFOOTBALL_KEY" \
   --header="x-rapidapi-host: v3.football.api-sports.io" \
   https://v3.football.api-sports.io/status'
# → subscription.active, subscription.end (expiry), requests.current / limit_day
```

---

## 3. Verify-a-run checklist

To confirm a given day's 02:00 run was **current** (built from source) and
**refreshed the projection**:

**a. The scheduled run built, then succeeded** — from the scheduler's own log:
```bash
# Build step present (proves it was self-current, not a stale image):
docker exec ingestor-scheduler sh -c \
  'grep -Ei "building|load build definition|=> \[|CACHED|naming to" /var/log/ingest.log | tail'

# Run reached succeeded (the D4 gate):
docker exec ingestor-scheduler sh -c 'grep "run.done" /var/log/ingest.log | tail -1'
#   → "status": "succeeded", ... "event": "run.done", "run_id": "<id>"
```

**b. The projection was rebuilt** — same log, correlated by `run_id`:
```bash
docker exec ingestor-scheduler sh -c \
  'grep -E "projection.built|run.projection_written" /var/log/ingest.log | tail -2'
#   → {"rows": N, "event": "projection.built", "run_id": "<same id>"}
```

**c. The sources DB shows N rows** (D6 contract holds) — the count must equal
the `projection.built rows=N` from step b:
```bash
docker exec arbibet-scraper-postgres-1 sh -c \
  'PGPASSWORD=$POSTGRES_PASSWORD psql -U $POSTGRES_USER -d $POSTGRES_DB -tAc \
   "SELECT count(*) FROM apifootball_events"'
```
Cross-check the run row itself in the bronze DB:
```bash
docker exec ingestor-postgres sh -c \
  'PGPASSWORD=$POSTGRES_PASSWORD psql -U $POSTGRES_USER -d $POSTGRES_DB -tAc \
   "SELECT run_id, status, started_at, finished_at FROM ingestion_runs \
    ORDER BY started_at DESC LIMIT 1"'
```

**If the run is `partial`/`failed`:** the projection is intentionally NOT
refreshed and `apifootball_events` still holds the prior snapshot. Check
`dead_letter` for the failing endpoints, and check `/status` for a lapse (§2)
before assuming a code bug.

---

## 4. Shared-key caveat

The API key may be **shared** with the scraper/matcher (they can run against the
same API-Football account). If so, the daily run's ~2.7 % of quota must be
counted **against combined consumption**, not in isolation — several consumers on
one key can exhaust the 75,000/day cap even though the ingestor alone is tiny
(task 0005 finding 2).

**Where to check remaining headroom:** the live `/status` probe (§2) reports
`requests.current` / `limit_day` for the **whole account** — i.e. all consumers
on the key combined. Read it there, not from any single service's local
`DAILY_QUOTA` guard (that env value is only a per-process ceiling and does not
know about other consumers). If `requests.current` is climbing toward the cap
before 02:00, the ingestor's run is at risk regardless of its own small share.
