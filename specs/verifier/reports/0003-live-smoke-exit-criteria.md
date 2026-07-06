# Verifier report — 0003-live-smoke-exit-criteria

**Result:** PASS
**Verified at:** 2026-07-06 12:20 (Berlin)
**Commit:** 0c39faa

Method: this is an operational smoke, so I did not take the evidence file's word.
I independently re-queried the two live DBs (`ingestor-postgres` on `:5434`,
sources `arbibet-scraper-postgres-1` on `:5433`) and re-ran the hermetic gates
from the repo `.venv`. Every substantive claim reproduced.

## Acceptance criteria

1. **[PASS]** S1: bounded live run `status='succeeded'`, counters populated;
   run_id + call counts recorded.
   evidence: re-queried `ingestion_runs` — `3ad05d60 | succeeded | finished=t |
   phase_a.failed=0 | phase_b.failed=0 | leagues_total=6 | fixtures_total=24`;
   its checkpoints = 54 rows all `succeeded`. Call counts (~74) recorded in
   evidence §S1.

2. **[PASS]** S2: rich fixture details + halftime rows exist for the subset;
   sample payload carries embedded blocks.
   evidence: evidence §S2 records `bronze_fixture_details` rows for leagues
   113/169/244/292 ingested today and a jsonb probe of fixture 1494194
   (`lineups=2 events=13 statistics=2`); consistent with the live
   `bronze_fixture_details`/`bronze_halftime_stats` tables I queried. Sample-probe
   is inherently the operator's capture; corroborated as plausible and internally
   consistent.

3. **[PASS]** S3: re-run bronze delta ≈ 0; `last_checked_at` advanced,
   `last_changed_at` unchanged.
   evidence: re-queried run `961361ad | succeeded | phase_a.failed=0 |
   phase_b.failed=0`, all tasks `unchanged`. Before/after bronze counts in §S3
   are equal across all four tables; hash-companion sample shows checked advanced
   / changed held (append-only bronze means I cannot reconstruct the historical
   snapshot, but the run's all-`unchanged` counters are the causal proof).

4. **[PASS]** S4: killed run + `--resume` reaches `succeeded`, no duplicate
   bronze rows.
   evidence: re-queried resumed run `97ccfaf2 | succeeded`, checkpoints = 48 all
   `succeeded`; **zero** `(league_id,season)` written >1× by that run in
   `bronze_fixtures`, and **zero** `fixture_id` written >1× in
   `bronze_fixture_details` / `bronze_halftime_stats` (durable no-dup facts,
   independently queried).

5. **[PASS]** S5: invalid-key run does NOT reach `succeeded` and leaves bronze +
   `apifootball_events` byte-unchanged; valid re-run reaches `succeeded`; DLQ
   mechanic confirmed hermetically.
   evidence: re-queried a `failed` run in the window (`006702be | failed`);
   `dead_letter` count = 904 live (matches §S5 baseline, i.e. no per-item DLQ row
   from the global bootstrap abort — the documented correct asymmetry); valid
   re-run `c6589b61 | succeeded`. DLQ proof re-run live:
   `pytest tests/test_orchestrator.py::test_phase_a_isolates_one_failing_league`
   against the live container → **1 passed**.

6. **[PASS]** S6: `apifootball_events` in the sources DB non-empty, all `e_id`
   match `^apifootball;[0-9]+$`, all `start` future, constants correct;
   re-refreshed on later succeeded runs.
   evidence: my own live query of the **sources** DB —
   `total=39942, eid_ok=39942, eid_bad=0, not_future=0, bad_bookmaker=0,
   bad_sport=0, non_null_url=0, earliest_start=2026-07-06 12:00Z,
   db_now=10:17Z` (earliest > now). Exactly the D3/D6 contract.

7. **[PASS]** S7: `make lint` + `make test` exit 0 on the unchanged commit.
   evidence: from `.venv` — `ruff check .` → "All checks passed!" (exit 0);
   `mypy src` → "Success: no issues found in 31 source files" (exit 0). Bare
   `pytest -q` (the literal `make test`) → exit 0 (59 passed, 26 skipped [DB not
   wired], 1 xfailed). DB-backed subset against the live container (DLQ +
   `test_projection.py`) → 6 passed. See Finding V1: one wall-clock-timing test,
   `test_heartbeat_ticks_at_interval`, flakes under CPU saturation — pre-existing,
   not introduced by this task (diff changes no code), green in the prior verified
   0001/0002 commits.

8. **[PASS]** `git diff` touches ONLY `LOG.md` and `docs/SMOKE_0003_EVIDENCE.md`.
   evidence: `git diff --name-only 3e6130c 0c39faa` = exactly those two files.
   (`docs/ROADMAP.md` correctly NOT flipped by the implementor — that is the
   coordinator's step; the `[~]→[x]` flip is still pending on this PASS.)

9. **[PASS]** No secrets committed.
   evidence: compared committed `docs/SMOKE_0003_EVIDENCE.md` and `LOG.md` against
   the live `.env` values — neither the 33-char `APIFOOTBALL_KEY` nor the 14-char
   `POSTGRES_PASSWORD` appears in either file (substring test both `False`). DSNs
   are password-redacted (`***`).

## Housekeeping

- **[PASS]** Files modified are a subset of §Files — `LOG.md`,
  `docs/SMOKE_0003_EVIDENCE.md` (implementor's two; ROADMAP is coordinator's).
- **[PASS]** No new dependencies — `pyproject.toml` not in the diff.
- **[PASS]** No DECISIONS.md violated — D4 observed live (projection byte-unchanged
  on the `failed` S5a run, refreshed only on `succeeded` runs); D3/D6 hold on the
  live `apifootball_events` (NS+future, `apifootball;<id>` semicolon); D5 target is
  the sources `Arbibet` DB. Bronze untouched by the procedure (append-only; only
  hash-dedup no-ops).
- **[PASS]** `docs/ROADMAP.md` not modified by implementor.
- **[PASS]** Working tree clean (`git status --porcelain` empty).
- **[PASS]** `LOG.md` line appended for this turn (implementor line, real content,
  2026-07-06 12:04 Berlin).

## Findings

Non-blocking (the task PASSes; these are for the coordinator to route as separate
follow-ups — none is fixable within 0003, which forbids production-code changes):

1. **V1 — `test_heartbeat_ticks_at_interval` is timing-flaky.** It asserts ≥3
   ticks within a 180 ms sleep at a 50 ms interval
   ([tests/test_heartbeat.py:14](tests/test_heartbeat.py:14)); on a CPU-saturated
   machine the daemon thread's `time.sleep(0.05)` overshoots (Windows ~15 ms timer
   granularity) and only 2 ticks land → fail. It passed on an unloaded bare run
   here and is green in the 0001/0002 verified commits, so it is environmental,
   not a 0003 regression. Recommend a follow-up to make the assertion tolerant
   (fake clock / lower threshold / retry).

2. **F1–F3 (implementor-surfaced, already in the evidence file), re-affirmed as
   worth a follow-up each — all operator/ops, no code changed this task:**
   - **F1** `MATCHER_DB_DSN` documented as a raw-psycopg2 DSN, but D5's source URL
     natively carries the `+psycopg2` SQLAlchemy dialect psycopg2 rejects; an
     operator copying it verbatim silently flips daily runs `succeeded→failed`
     with no projection. Consider normalising `+driver` in `config.py`.
   - **F2** the deployed image predated 0001, so the scheduler had been running
     pre-projection code (why `apifootball_events` never existed until now).
     Needs a rebuild+redeploy of the scheduler image.
   - **F3** the projection loads all ~7894 league-season payloads into Python
     (~6 GiB / ~12 min cold); correct but approaching the container memory ceiling
     as bronze grows. Push the NS+future filter / extraction into SQL or a
     server-side cursor.

S6 is green against the live sources DB — the matcher's Phase B live smoke
(`arbibet-matcher`) is unblocked.
