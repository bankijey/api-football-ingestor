# Verifier report — 0005-full-catalogue-run

**Result:** PASS
**Verified at:** 2026-07-06 18:55 (Berlin)
**Commit:** a659f74

All evidence independently corroborated against the live DBs (bronze `ingestor`
on `:5434`, sources `Arbibet` on `:5433`) and by re-running the hermetic gates
in a freshly-built Python 3.12.10 venv. I did not take the evidence file's word.

## Acceptance criteria

1. [PASS] S1: `ingestion_runs` shows one full-catalogue run, non-null
   `finished_at`, populated counters, `leagues_total` = full catalogue (~1k–1.5k).
   evidence: re-queried `ingestion_runs` — `run_id=1f814136-e56a-4c08-be9c-804281d4b5e7`,
   `status=succeeded`, `started 16:05:07Z → finished 16:14:08Z` (541 s bronze),
   counters `leagues_total=1231`, `fixtures_total=381`,
   `phase_a{ok54/unchanged1177/failed0}`, `phase_b{ok208/unchanged554/failed0}`.
   1231 leagues = full current-season catalogue, not a handful.

2. [PASS] S2: total API-call count + lowest `x-ratelimit` remaining + calls/day
   estimate vs `daily_quota` with margin.
   evidence: evidence file records 2021 total calls (`/leagues`×1, `/fixtures`×1635,
   `/fixtures/statistics`×385), daily quota via `/status` = 5094/75000 →
   ~2.7 % of quota, ~37× margin; per-minute headroom stated as ~218/min avg
   under the 240/65s cap. Daily `x-ratelimit` supplied via `/status`; per-minute
   `x-ratelimit-*-remaining` header not captured (not persisted by the client —
   see Findings §1) and substituted with observed throughput. Intent (schedule
   sizing) satisfied; non-blocking gap noted.

3. [PASS] S3: S1=`succeeded` → projection refreshed; row count, `e_id` pattern,
   future `start`, constants, no OOM.
   evidence: re-queried `apifootball_events` (sources DB) — `total=42399`,
   `eid_bad=0` (all `~ '^apifootball;[0-9]+$'`), `bad_bookmaker=0`, `bad_sport=0`,
   `bad_url=0`, `min(start)=2026-07-06 16:30:00Z`. My re-query showed
   `not_future=1` **because real time advanced past one kickoff** (`db_now
   16:32:30Z` > earliest `16:30:00Z`); at build time (~16:17Z) all 42399 were
   future, so D3 held — a snapshot/time-passage artifact, not a projection defect.
   No OOM: container exit 0 with an atomic 42399-row commit (~164 s), consistent
   with 0004's streaming read.

4. [PASS] S4: terminal status + `dead_letter` breakdown by endpoint+error_class.
   evidence: re-queried `dead_letter WHERE run_id='1f814136-…' GROUP BY endpoint,
   error_class` → **0 rows**. Terminal status `succeeded`, so the projection-gating
   escalation branch does not apply this run; evidence documents the
   partial-tolerance context as forward-looking (correct per spec — not an
   escalation obligation on a clean run).

5. [PASS] S5: written daily-schedule sizing recommendation present.
   evidence: `FULLRUN_0005_EVIDENCE.md` §S5 — quota margin (~2.7 %, peak est.
   5–7 %), duration (~12 min now, ~25–30 min peak), one-run/day feasible, rate
   limit `240/65s` adequate, projection-freshness caveat tied to D4.

6. [PASS] S6: `make lint` + `make test` exit 0 on the unchanged commit (Py 3.12).
   evidence: fresh `.venv312v` (Python 3.12.10, `pip install -e .[dev]`) —
   `ruff check .` exit 0 ("All checks passed!"), `mypy src` exit 0
   ("no issues found in 31 source files"), `pytest -q` exit 0
   (60 passed, 27 skipped, 1 xfailed). The 27 skips are DB-integration tests that
   skip gracefully when no DB password is in the DSN; they do not affect exit
   status. Implementor's run (DB DSN supplied) recorded 87 passed / 0 skips.

7. [PASS] Diff touches ONLY evidence + roadmap + LOG.md.
   evidence: `git diff --name-only 19abe6e a659f74` = `LOG.md`,
   `docs/FULLRUN_0005_EVIDENCE.md`. ROADMAP not touched by implementor (correct);
   no `src/`, `tests/`, or `pyproject.toml` changes.

8. [PASS] No secrets committed.
   evidence: grep of committed evidence+log — DSN password-redacted
   (`postgres:***@host.docker.internal`), `TEST_DB_DSN=…@localhost` elided, no
   `x-rapidapi-key`/password literals. The one grep hit (`postgres:5432`) is a
   container host:port, not a credential.

## Housekeeping

- [PASS] Files modified are a subset of §Files
  evidence: `LOG.md`, `docs/FULLRUN_0005_EVIDENCE.md` — both in §Files.
- [PASS] No new dependencies beyond §In scope
  evidence: `pyproject.toml` not in the diff.
- [PASS] No DECISIONS.md entries violated
  evidence: D4 observed live — projection refreshed **iff** `succeeded` (run was
  `succeeded`, projection ran, 42399 rows). Bronze append-only untouched by the
  verification procedure (SELECT-only queries).
- [PASS] docs/ROADMAP.md not modified by implementor
  evidence: not in `git diff --name-only 19abe6e a659f74`.
- [PASS] Working tree clean (`git status --porcelain` empty)
- [PASS] `LOG.md` line appended for this turn
  evidence: `2026-07-06 18:25 Berlin | implementor | 0005-full-catalogue-run |
  executed full run | …` present.

## Findings

PASS — no blocking issues. Three non-blocking observations for the coordinator
(fold into future tasks, NOT this one — this one is done):

1. **Per-minute `x-ratelimit-*-remaining` headers are not persisted** by the HTTP
   client, so the exact lowest per-minute remaining could not be reproduced
   post-hoc; the implementor substituted observed throughput (~218/min vs 240
   cap). Capturing those headers would need a code change (correctly out of scope
   here). A future task could log rate-limit headers so schedule-sizing has the
   exact per-minute headroom, not a derived average.
2. **The run came back `succeeded`, not the expected `partial`.** The
   partial-tolerance / success-with-warnings policy follow-up (roadmap §1.6)
   therefore still has **no real `partial` `dead_letter` numbers** to size against
   — the S4 breakdown is empty by virtue of a clean run. The coordinator may want
   a targeted capture the next time a full run returns `partial`.
3. **Leftover template scaffolding** in `FULLRUN_0005_EVIDENCE.md`: duplicate
   empty section stubs (`## S2 … <!-- S2 -->`, `## S4 …`, `## S6 …`) appear a
   second time at the bottom/middle of the file. Cosmetic only; content is intact.
