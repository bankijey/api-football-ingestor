# 0008 — Daily scheduling: anti-drift redeploy + ops runbook

**Roadmap item:** §1.11 — Daily scheduling + anti-drift redeploy
**Depends on:** 0005 (sizing), 0007 (scheduler redeploy proven, PASS `3c26123`).
**Status:** open

## Goal

The daily schedule already exists (compose `scheduler` cron, `0 2 * * *`), and
0007 proved a crond-fired run of a *current* image refreshes `apifootball_events`.
But 0007 also nailed the root cause of finding F2: **the scheduled path never
rebuilds `:latest`**. The cron command is `docker compose run --rm ingestor
ingest` ([docker-compose.yml:71](../../docker-compose.yml)) with **no build
step**, so after any code change the 2am run silently executes a **stale image**
(production ran pre-0001 code for 20 prior `succeeded` runs, all with zero
`projection.built`). 0007's hand-rebuild papers over it only until the next
change.

This task makes the daily run **self-currenting** — it rebuilds from source
before running, so drift cannot recur — and writes the ops runbook that turns the
next subscription lapse (0007's real 429/`failed` root cause) into an
**anticipated calendar event** rather than three mystery fires at 02:00. Scope is
the reliability/ops wrapper around the daily run; the ingestion code itself is
unchanged.

## In scope

### Anti-drift — design decision: **rebuild-on-cron** (build before run)
This is a **single-host, docker-compose** deployment where the scheduler already
mounts the repo read-only at `/workspace` and has the docker socket
([docker-compose.yml:53-55](../../docker-compose.yml)) — so it can build from the
mounted source via the host daemon with no extra plumbing. **Rebuild-on-cron is
therefore the minimal correct fix.** Registry-pull and CI/CD redeploy are heavier
(need a registry / CI) and are rejected for this setup (see Out of scope).

- **`docker-compose.yml` — `scheduler` service `command`:** change the crontab
  line so the run builds first. Either the one-liner
  `docker compose -f /workspace/docker-compose.yml run --build --rm ingestor ingest`
  (compose v2 `--build`), or an explicit
  `docker compose -f /workspace/docker-compose.yml build ingestor && docker compose … run --rm ingestor ingest`.
  Keep the `>> /var/log/ingest.log 2>&1` redirect and the `0 2 * * *` schedule.
- **`scripts/run-ingest.ps1`:** the Windows Task path
  ([scripts/run-ingest.ps1:31-33](../../scripts/run-ingest.ps1)) likewise only
  `run`s — add the same build-before-run so *neither* trigger can drift.
- After editing compose, the scheduler must be recreated to pick up the new
  `command`: `docker compose --profile scheduler up -d --force-recreate scheduler`
  (record in the evidence file).

### Ops runbook — `docs/OPS.md` (created)
The durable place the schedule + subscription are tracked. Must contain:
- **Daily run:** what fires (compose `scheduler` cron, `0 2 * * *` UTC), the
  command (now build-then-run), 0005's sizing (~12 min, ~2,000 calls ≈ 2.7 % of
  the 75k daily quota), and how the projection refresh is gated (D4 — only on
  `succeeded`).
- **Subscription tracking (per the 0007 lapse):** plan `Ultra`, **renewed
  2026-07-06**, **expiry 2026-08-06** (from the `/status` probe). A "renew before
  2026-08-06" reminder, and the note that a lapse surfaces as limit-type
  errors (429 / in-body "request limit for the day") **despite** healthy quota
  headroom — the signature to recognise next time (see
  `docs/DEPLOY_0007_EVIDENCE.md` coordinator addendum).
- **Verify-a-run checklist:** how to confirm today's 02:00 run was current and
  refreshed the projection — `docker exec ingestor-scheduler` tail of
  `/var/log/ingest.log` for the build step + `run.done status=succeeded` +
  `projection.built rows=N`, and the sources-DB `SELECT count(*) FROM
  apifootball_events`.
- **Shared-key caveat (0005 finding 2):** if the API key is shared with the
  scraper/matcher, the daily run's ~2.7 % must be counted *against combined*
  consumption; note where to check remaining headroom (`/status`).

### `README.md`
One-line pointer from the quickstart to `docs/OPS.md` for the daily-run runbook.

## Out of scope
- **Changing the schedule cadence/time.** 0005 validated one run/day; `0 2 * * *`
  stays. This task only makes that run self-currenting + documented.
- **Registry-pull / CI-CD redeploy.** Heavier alternatives to rebuild-on-cron;
  rejected for this single-host, source-mounted setup (see In scope). If you
  believe the deployment is actually multi-host and needs a registry, STOP and
  escalate — do not silently build a CI pipeline.
- **Partial-tolerance / any D4 change (0010 — DEFERRED).** 0007's transient
  failures were a **subscription lapse**, not a genuine partial rate; do not
  amend a locked decision to tolerate a billing event. D4 stays as-is.
- **x-ratelimit-* header logging (0009 — backlog).**
- **Any change to the ingestion/projection code** (`src/`), migrations, or the
  bronze write path. This is the ops wrapper only.
- **0006** (flaky heartbeat test).

## Files
Created:
- `docs/OPS.md` — daily-run + subscription runbook
- `docs/DEPLOY_0008_EVIDENCE.md` — operational proof of the anti-drift fire

Modified:
- `docker-compose.yml` — `scheduler` cron command builds before running
- `scripts/run-ingest.ps1` — same build-before-run for the Windows path
- `README.md` — one-line pointer to `docs/OPS.md`
- `docs/ROADMAP.md` — coordinator flips `0008 [~]→[x]` + Progress-log ON CLOSE
- `LOG.md` — implementor appends one line on commit

No `src/`, tests, migrations, or `pyproject.toml`. If one must change, STOP and
escalate at `specs/implementor/notes/0008-daily-scheduling.md`.

## Acceptance criteria (Definition of Done)
1. Anti-drift (static): the `scheduler` cron command in `docker-compose.yml`
   builds current source **before** running (`run --build` or `build && run`),
   and `scripts/run-ingest.ps1` does the same. Grep confirms a build step in both
   trigger paths; the `0 2 * * *` schedule and log redirect are unchanged.
2. `docker compose config` exits 0 (compose file still valid); the `scheduler`
   service was recreated to load the new command (evidence records
   `up -d --force-recreate scheduler`).
3. Anti-drift (operational): an **autonomous** (crond-fired) scheduled run
   **rebuilt `:latest` from source before running** — proven from the scheduler's
   own `/var/log/ingest.log` (a build step precedes `run.done`) and/or the
   `:latest` image `Created` timestamp advancing at fire time without a manual
   `make build`. This is the proof drift cannot recur.
4. That scheduled run reached `status='succeeded'` and refreshed
   `apifootball_events` (fresh `ingestion_runs` row + `projection.built rows=N` in
   the scheduled log + sources-DB count `== N`, D6 contract holds). The real
   `0 2 * * *` run is an acceptable vehicle if an isolated fire is quota-limited;
   evidence must show one self-current, autonomous, succeeded+refreshed run.
5. `docs/OPS.md` exists with all four sections (daily run, subscription tracking
   incl. **expiry 2026-08-06**, verify-a-run checklist, shared-key caveat);
   `README.md` points to it.
6. `make lint` + `make test` exit 0 (control — no Python changed).
7. `git diff` touches ONLY the §Files list.
8. No secrets in any committed file (key/passwords absent; DSNs redacted).

## Verifier checklist (mirror of DoD + housekeeping)
- [ ] AC1–AC6 — grep both trigger paths for the build step; run `docker compose
      config`; re-query the scheduled run in `ingestion_runs` + the scheduler log
      + `apifootball_events`; confirm `docs/OPS.md` content incl. the expiry date;
      run lint/test.
- [ ] AC7 — diff confined to §Files (no `src/`/tests/migrations)
- [ ] AC8 — no secrets committed
- [ ] No `DECISIONS.md` violated: D4 unchanged (projection still refreshes only on
      `succeeded`); bronze append-only untouched.
- [ ] Working tree clean on handoff; `LOG.md` line appended

## Notes for the implementor
- **The fix is "build then run", nothing more.** Do not re-architect the
  scheduler or introduce a registry — rebuild-on-cron is the decided, minimal
  approach for this single-host setup.
- The scheduler already mounts the repo at `/workspace:ro` and the docker socket,
  so `docker compose -f /workspace/docker-compose.yml build ingestor` builds from
  that source via the host daemon — no new mounts needed.
- After editing `docker-compose.yml`, **recreate** the scheduler
  (`up -d --force-recreate scheduler`) or it keeps the old baked-in `command`.
- Prove the anti-drift fire with the same autonomy standard as 0007 — crond-fired,
  evidenced from the scheduler's own log, never a manual `make ingest`.
- **Subscription:** the 0007 429/`failed` fires were a **lapse** (renewed
  2026-07-06, expiry 2026-08-06 per `/status`) — record this in `docs/OPS.md` so
  the next lapse is a known calendar event, not a mystery. See the coordinator
  addendum in `docs/DEPLOY_0007_EVIDENCE.md`.
- If the isolated proof fire is quota-limited on the day, let the real 02:00 run
  be the vehicle and capture its evidence — do not hammer the API.
