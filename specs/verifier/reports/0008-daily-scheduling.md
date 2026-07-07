# Verifier report — 0008-daily-scheduling

**Result:** PASS
**Verified at:** 2026-07-07 09:05 (Berlin)
**Commit:** f188c9b

All acceptance criteria corroborated independently — the operational ones
(AC3/AC4) were re-queried against the live scheduler container and both DBs, not
taken from the evidence file.

## Acceptance criteria

1. [PASS] Anti-drift (static): scheduler cron builds current source before
   running (`run --build` or `build && run`), and `scripts/run-ingest.ps1` does
   the same; `0 2 * * *` + log redirect unchanged.
   evidence: `docker-compose.yml:71` cron line is
   `... run --build --rm ingestor ingest >> /var/log/ingest.log 2>&1`
   (schedule `0 2 * * *` and redirect intact); `scripts/run-ingest.ps1:35`
   `run --build --rm --profile cli ingestor`. Both trigger paths carry `--build`.

2. [PASS] `docker compose config` exits 0; scheduler recreated to load the new
   command.
   evidence: `docker compose --profile scheduler --profile cli config` → exit 0
   (re-run by verifier); live `docker exec ingestor-scheduler crontab -l` returns
   the `run --build` line, i.e. the recreated scheduler baked it in; evidence
   file records `up -d --force-recreate scheduler`.

3. [PASS] Autonomous (crond-fired) run rebuilt `:latest` from source before
   running.
   evidence (both proofs re-verified live): scheduler log line 6 =
   `#1 [ingestor internal] load build definition from Dockerfile`, precedes
   `run.done` at line 3696. `docker image inspect api-football-ingestor:latest`
   → `sha256:552d4a2874cb… 2026-07-07T05:47:12Z` — advanced off 0007's
   `d764187325a2` (17:04Z) to fire time, no manual `make build`.

4. [PASS] That scheduled run reached `status='succeeded'` and refreshed
   `apifootball_events` (D6 contract holds).
   evidence: `ingestion_runs` latest = `46bb4d05-…|succeeded`; scheduler log
   `projection.built rows=43123` and `run.projection_written rows=43123`, same
   `run_id`; sources-DB `SELECT count(*) FROM apifootball_events` = **43123** ==
   `projection.built rows`. Run started 05:47:18Z (after the pre-fire baseline),
   so it is attributable to the autonomous trigger.

5. [PASS] `docs/OPS.md` exists with all four sections incl. expiry 2026-08-06;
   README points to it.
   evidence: `docs/OPS.md` §1 Daily run, §2 Subscription tracking
   (`Expiry **2026-08-06**`, `docs/OPS.md:75`), §3 Verify-a-run checklist, §4
   Shared-key caveat; `README.md:74` links `docs/OPS.md`.

6. [PASS] `make lint` + `make test` exit 0 (control — no Python changed).
   evidence (verifier ran in `.venv`): `ruff check .` → All checks passed;
   `mypy src` → Success, no issues in 31 files; `pytest -q` → 60 passed, 27
   skipped, 1 xfailed, 0 failed (exit 0). The 27 skips are the DB-backed
   `test_projection.py` tests (no Postgres on the verifier's local run); the
   implementor's container-up run was 87 passed / 1 xfail. No Python changed
   (see AC7), so the pass baseline is preserved by construction.

7. [PASS] `git diff` touches ONLY the §Files list.
   evidence: `git diff-tree` f188c9b = LOG.md, README.md, docker-compose.yml,
   docs/DEPLOY_0008_EVIDENCE.md, docs/OPS.md, scripts/run-ingest.ps1. No
   `src/`, tests, migrations, or `pyproject.toml`.

8. [PASS] No secrets committed.
   evidence: secret-pattern grep over all six changed files at f188c9b returns
   only `docker-compose.yml:35` `DB_DSN: ...${POSTGRES_PASSWORD}...` — an
   env-var template (not a literal, and pre-existing / outside this diff's
   hunks). OPS.md `/status` examples use `$APIFOOTBALL_KEY`; evidence file DSNs
   password-redacted.

## Housekeeping

- [PASS] Files modified are a subset of §Files
  evidence: 6 files above; all listed in §Files (ROADMAP flip is the
  coordinator's, correctly absent).
- [PASS] No new dependencies beyond §In scope
  evidence: `pyproject.toml` not in the diff.
- [PASS] No DECISIONS.md entries violated
  evidence: D4 gate intact — projection refreshed only because the run
  `succeeded` (corroborated live: succeeded run → 43123 rows written); no
  matview/FDW (D4), sources-DB-only write (D5), bronze append-only untouched;
  `src/` unchanged.
- [PASS] docs/ROADMAP.md not modified by implementor
  evidence: not in diff; 0008 still `[~]` in ROADMAP.
- [PASS] Working tree clean (`git status --porcelain` empty)
- [PASS] `LOG.md` line appended for this turn
  evidence: `LOG.md` line `2026-07-07 08:01 Berlin | implementor |
  0008-daily-scheduling | implemented | ...` (root file, not per-agent).

## Findings

PASS — no blocking findings. Non-blocking observations for the coordinator
(NOT for this task, which is done):

1. `scripts/run-ingest.ps1:35` passes `--profile cli` as an argument to
   `docker compose run` rather than as a top-level flag
   (`docker compose --profile cli run`). This is pre-existing (unchanged by
   0008) and out of this task's scope, but the Windows trigger path has not been
   exercised end-to-end the way the compose scheduler has. Worth a one-line
   smoke someday if the Windows path is ever the primary trigger.
2. The verify-a-run checklist in `docs/OPS.md` §3 hard-codes container names
   (`ingestor-scheduler`, `arbibet-scraper-postgres-1`); fine today, but a
   rename would silently break the runbook. Cosmetic; log for future.
