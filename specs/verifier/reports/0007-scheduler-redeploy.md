# Verifier report — 0007-scheduler-redeploy

**Result:** PASS
**Verified at:** 2026-07-06 23:05 (Berlin)
**Commit:** 9676d9e

All evidence below was **corroborated independently** — the verifier re-ran the
image import-check, `docker exec`'d the live `ingestor-scheduler` crontab + log,
and re-queried both live databases (`ingestor-postgres` bronze,
`arbibet-scraper-postgres-1` sources). Not read off the evidence file.

## Acceptance criteria

1. [PASS] D1: `:latest` rebuilt on the host; import-check (`ingestor.projection`)
   exits 0; image ID + Created recorded.
   evidence: `docker image inspect` → `ID=sha256:d764187325a2…`,
   `Created=2026-07-06T17:04:51.559581181Z`; `docker run … python -c "import
   ingestor.projection"` → `projection present`, `IMPORT_EXIT=0`.

2. [PASS] D2: production scheduler identified, noted as not rebuilding.
   evidence: `docker exec ingestor-scheduler crontab -l` →
   `0 2 * * * docker compose … run --rm ingestor ingest …` (no `build`);
   `docker:27-cli` container `Up 6 days`; evidence §D2 documents 20 prior
   `succeeded` runs with 0 `projection.built` (the F2 drift).

3. [PASS] D3/D4: a single, isolated, autonomous (crond-fired, not manual) run of
   the rebuilt image reached `status='succeeded'`, proven by a fresh
   `ingestion_runs` row + the scheduler's own `ingest.log`.
   evidence: bronze `ingestion_runs` → `ec38234d-109a-4f3b-a8eb-fc5cc590bd60 |
   succeeded | started 2026-07-06 20:12:23+00 | finished 20:20:27+00`; the
   run_id appears in `ingestor-scheduler:/var/log/ingest.log` with
   `run.done status=succeeded` (phase_a failed=0, phase_b failed=0) and
   `projection.built rows=42383` — a file only the cron command writes, so the
   run was autonomous, not a manual `make ingest`.

4. [PASS] D4: `apifootball_events` refreshed by that run — count == N, contract
   holds, correlated to this run (not 0005's).
   evidence: sources DB `SELECT count(*),min(start),max(start),bool_and(start>now())`
   → `42383 | 2026-07-06 21:00:00+00 | 2027-06-06 15:00:00+00 | t`. Count ==
   `projection.built rows=42383`. Correlated: changed from 0005's snapshot
   (42399 rows, min_start 16:30) → 42383, min_start advanced to 21:00 UTC. D6
   contract: `eid_ok=bkmkr_ok=sport_ok=url_null_ok=core_ok=42383/42383`
   (`e_id ~ '^apifootball;[0-9]+$'`, `bookmaker_id='apifootball'`,
   `sport_key='football'`, `url IS NULL`, `start>now()`, core fields present).

5. [PASS] D5: normal 2am schedule restored; scheduler left running.
   evidence: live `crontab -l` = `0 2 * * *` (self-disarmed after the fire);
   `ingestor-scheduler` `Up 6 days`. Before/after snippets in evidence §D5.

6. [PASS] AC6: drift hand-off to 0008 present.
   evidence: evidence file "Hand-off to 0008 (systemic drift — AC6)" §
   (`docs/DEPLOY_0007_EVIDENCE.md:308`) — cron never rebuilds `:latest`; 0008
   owns anti-drift strategy; do not patch compose here.

7. [PASS] AC7: diff confined to evidence/roadmap/log; no repo code/compose.
   evidence: `git diff --name-only deefd77 HEAD` = `LOG.md`,
   `docs/DEPLOY_0007_EVIDENCE.md`, `docs/ROADMAP.md`,
   `specs/coordinator/tasks/0007-scheduler-redeploy.md` (coordinator amendment),
   `specs/implementor/notes/0007-scheduler-redeploy.md` (designated escalation
   channel). Grep for `src/|docker-compose|Dockerfile|*.py|pyproject` → NONE.

8. [PASS] AC8: no secrets committed.
   evidence: secret-scan of `docs/DEPLOY_0007_EVIDENCE.md` (key/password/DSN/hex
   patterns, excluding image SHAs + `<redacted>`) → NO SECRETS FOUND. All DSNs
   password-redacted; API key never printed.

## Housekeeping

- [PASS] Files modified are a subset of §Files (+ the spec-sanctioned escalation
  note and the coordinator's own amendment).
  evidence: implementor commits `42fa626 / ce25287 / 9676d9e` touched only
  `LOG.md`, `docs/DEPLOY_0007_EVIDENCE.md`,
  `specs/implementor/notes/0007-scheduler-redeploy.md`.
- [PASS] No new dependencies. evidence: `pyproject.toml` unchanged (not in diff).
- [PASS] No DECISIONS.md entries violated. D4 upheld and independently proven:
  the projection refreshed *because* the run was `succeeded`; the two `partial`
  and one `failed` runs correctly left the prior 42399-row snapshot untouched
  (all-or-nothing). Bronze append-only untouched (operational task, no writes to
  bronze tables outside the normal run).
- [PASS] docs/ROADMAP.md not modified by implementor.
  evidence: `git log deefd77..HEAD -- docs/ROADMAP.md` → only coordinator commit
  `8ca0c2c`; 0007 line still `[~]` (line 201).
- [PASS] Working tree clean. evidence: `git status --porcelain` empty.
- [PASS] `LOG.md` line appended for this turn.
  evidence: `2026-07-06 22:26 Berlin | implementor | 0007-scheduler-redeploy |
  implemented | GATE MET — … ec38234d succeeded … projection.built rows=42383 …`.

## Findings

None blocking. Observations for the coordinator to fold into future tasks (NOT
this one):

1. The proof cost three autonomous fires (2 per-minute-429 `partial`, 1 spurious
   in-body "day-limit" `failed`) before the clean `ec38234d`. The `/status`
   probe (9144/75000 used) shows the daily quota was never the blocker — the
   transient 429s remain unexplained without `x-ratelimit-*` header logging.
   Reinforces **0009** (header persistence) and **0010** (partial-tolerance) as
   real reliability work ahead of **0008**'s daily schedule.
2. The account key is possibly shared (scraper/matcher on the same host). If so,
   a daily full run must size against real remaining headroom, not the local
   `DAILY_QUOTA=75000` guard — a **0008** concern.
3. Quiescence for the winning fire was ~2h41m after the last full run (17:31
   UTC); the intervening `851d7576` aborted at bootstrap in 39s so consumed no
   catalogue. The ≥2h isolation intent (AC3) holds; noted for completeness.
