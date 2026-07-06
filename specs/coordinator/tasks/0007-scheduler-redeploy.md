# 0007 — Rebuild + redeploy the ingestor image; prove the scheduled run refreshes the projection

**Roadmap item:** §1.11 — Scheduler redeploy (0003 finding F2)
**Depends on:** 0001 (projection), 0004 (streaming), 0005 (full run PASS `a659f74`).
**Status:** open

## Goal

Every green result so far came from a **manual** `make ingest`, which rebuilds
the image first (`ingest: build up`, [Makefile:41](Makefile:41)). The **deployed
scheduler** does not: its cron command is
`docker compose run --rm ingestor ingest` ([docker-compose.yml:71](docker-compose.yml:71))
with **no build step**, so it runs whatever `api-football-ingestor:latest`
already is on the host — and that image predates 0001, so the scheduled 2am run
has **never** contained the projection code. Result: production has never
autonomously refreshed `apifootball_events`; the matcher's source only got data
from hand-run smokes (0003/0005) and would starve otherwise.

This task rebuilds `:latest` on the deployment host and **proves the autonomous
scheduled path — not a manual invocation — refreshes `apifootball_events`.** Per
the human's gate: "deployed **and verified**," not merely "image built." Like
0003/0005 it is *operational*: evidence, **zero repo/code change**.

## Procedure (in scope)
Run on the **deployment host** against the real API key (env only). Record every
command + result in `docs/DEPLOY_0007_EVIDENCE.md` (command, Berlin timestamp,
output snippet).

### D1 — Rebuild `:latest` from current source
- `make build` (i.e. `docker compose --profile cli build ingestor`,
  [Makefile:28](Makefile:28)).
- Prove the rebuilt image contains the projection code (a pre-0001 image does
  not): `docker run --rm --entrypoint python api-football-ingestor:latest -c
  "import ingestor.projection; print('projection present')"` → exit 0.
- Evidence: image ID + `Created` timestamp (`docker image inspect`), and the
  import-check output.

### D2 — Identify the live scheduler
- State which trigger is production on this host: the compose `scheduler` cron
  service ([docker-compose.yml:40](docker-compose.yml:40)) **or** Windows Task
  Scheduler + [scripts/run-ingest.ps1](scripts/run-ingest.ps1). Note that
  **neither rebuilds the image** before running (see §Out of scope hand-off).
- Ensure it is running the way production runs it (e.g.
  `docker compose --profile scheduler up -d scheduler`).

### D3 — Autonomous trigger (scheduled, NOT manual)
- Make the live scheduler fire on its own within a couple of minutes **without**
  running `make ingest` / `docker compose run` by hand. For the compose cron:
  temporarily rewrite the crontab **inside the running container** to the next
  minute, e.g.
  `docker exec ingestor-scheduler sh -c "echo '<next-min> * * * * docker compose -f /workspace/docker-compose.yml run --rm ingestor ingest >> /var/log/ingest.log 2>&1' | crontab -"`,
  and let `crond` fire it. (For the Windows Task: set a near-future run time or
  "Run" the task via the scheduler service — it must be the scheduler firing it,
  not you invoking the CLI.)
- The scheduled command is the real deployed one (full catalogue, no
  `--leagues`). Expect `succeeded` (0005 showed the full catalogue succeeds and
  refreshes). If it returns `partial` transiently, re-trigger once; if
  **systematically** `partial` (so the projection never refreshes per D4), STOP
  and escalate — that is the partial-tolerance policy, a later task, and it would
  block the daily projection.

### D4 — Prove the scheduled run refreshed the projection
- Evidence the run was **autonomous**: the scheduler's own log
  (`docker exec ingestor-scheduler cat /var/log/ingest.log`) contains this run —
  that file is written only by the cron command ([docker-compose.yml:71](docker-compose.yml:71)),
  never by a manual `make ingest`.
- Evidence the run **succeeded and projected**: a fresh `ingestion_runs` row
  whose `finished_at` is after the trigger time with `status='succeeded'`, and
  the scheduled run's log shows `projection.built rows=N`
  ([projection.py:85](src/ingestor/projection.py:85)).
- Evidence the **sources DB** refreshed: `apifootball_events` count `== N`; the
  D3/D6 contract holds (every `e_id ~ '^apifootball;[0-9]+$'`, `start` future at
  build time, `bookmaker_id='apifootball'`, `sport_key='football'`, `url IS NULL`);
  correlated to this scheduled run, not the earlier 0005 refresh.

### D5 — Restore the schedule
- Put the crontab back to `0 2 * * *` (or restore the Windows Task's normal
  time) and confirm; leave the scheduler service running as production expects.
- Evidence: crontab/Task before (near-future) and after (restored) snippets.

## Out of scope
- **Fixing the systemic drift** — the scheduled path does **not** rebuild
  `:latest`, so it will go stale again after the next code change (this is *why*
  F2 happened). Do **NOT** edit `docker-compose.yml`/`Dockerfile` to add a
  build/pull step here. **Flag it as an explicit hand-off to the daily-scheduling
  task (0008)**, which owns the redeploy/anti-drift strategy. If you believe it
  must be fixed now, STOP and escalate — do not change repo files in this task.
- **Designing/tuning the daily schedule** (cadence, monitoring, alerting) — 0008.
  0007 uses the existing 2am cron and only *temporarily* retimes it for the proof.
- **Partial-tolerance / success-with-warnings policy** — still no `partial` data
  (0005 was clean); a later task, escalate only if D3 is systematically `partial`.
- **Any repo code/compose change.** The temporary crontab edit lives inside the
  running container and is reverted (D5); it is never committed.
- **0006** (flaky heartbeat test) / **rate-limit header logging** (backlog).
- **The matcher repo.**

## Files
Created:
- `docs/DEPLOY_0007_EVIDENCE.md` — the evidence log

Modified:
- `docs/ROADMAP.md` — coordinator flips `0007 [~]→[x]` + Progress-log ON CLOSE
- `LOG.md` — implementor appends one line on commit

NO repo/source/compose files. If one must change, STOP and escalate at
`specs/implementor/notes/0007-scheduler-redeploy.md`.

## Acceptance criteria (Definition of Done)
1. D1: `:latest` rebuilt on the deployment host; the import-check
   (`ingestor.projection`) exits 0, proving the image now carries the projection
   code; image ID + `Created` timestamp recorded.
2. D2: the production scheduler mechanism is identified in the evidence, with the
   note that it does not rebuild before running.
3. D3/D4: an **autonomous** (crond/Task-fired, not manual) run of the rebuilt
   image reached `ingestion_runs.status='succeeded'` — proven by a fresh
   `ingestion_runs` row (finished_at after the trigger) **and** the scheduler's
   own `ingest.log` showing the run + `projection.built rows=N`.
4. D4: `apifootball_events` was refreshed by that scheduled run — count `== N`,
   contract holds (`e_id` pattern, future `start`, constants), correlated to this
   run (not 0005's). This is the "deployed AND verified" gate.
5. D5: the normal 2am schedule is restored (before/after crontab or Task snippet)
   and the scheduler is left running as production expects.
6. The evidence file explicitly hands the "scheduled path never rebuilds →
   stale-image drift" flaw to the daily-scheduling task (0008).
7. `git diff` for this task touches ONLY `docs/DEPLOY_0007_EVIDENCE.md`,
   `docs/ROADMAP.md` (coordinator), `LOG.md` — no repo code/compose changes.
8. No secrets in any committed file (API key / DB passwords absent; DSNs
   password-redacted).

## Verifier checklist (mirror of DoD + housekeeping)
- [ ] AC1–AC5 — corroborate independently: re-query `ingestion_runs` (the
      scheduled run_id, finished_at vs trigger time, status) and
      `apifootball_events` on the live DBs; confirm the run was autonomous
      (present in the scheduler's `ingest.log`, not a manual invocation); run the
      image import-check; confirm the schedule was restored.
- [ ] AC6 — the drift hand-off to 0008 is present in the evidence
- [ ] AC7 — diff confined to evidence/roadmap/log; no repo code/compose changes
- [ ] AC8 — no secrets committed
- [ ] No `DECISIONS.md` violated: D4 (projection refreshed because the run was
      `succeeded`); bronze append-only, untouched by the procedure
- [ ] Working tree clean on handoff; `LOG.md` line appended

## Notes for the implementor
- **Operator, not coder.** Deliverable is evidence; copy real command output.
- **The mechanism to internalise:** `make ingest` rebuilds (`build up`), which is
  why every manual smoke ran current code; the cron command does not, so it runs
  the stale `:latest`. Rebuild `:latest` on the deployment host, THEN prove the
  autonomous trigger picks it up.
- **"Scheduled, not manual" is the whole point.** Let `crond` (or Windows Task)
  fire the run; the proof that it was autonomous is the entry in the scheduler's
  `/var/log/ingest.log`, which a hand-run `make ingest` never writes. Do not
  substitute a manual invocation.
- Restore `0 2 * * *` at the end (D5) — do not leave the near-future test cron in
  place.
- The stale-drift flaw is real and recurring but **out of scope here** — flag it
  for 0008, don't fix it by editing compose.
