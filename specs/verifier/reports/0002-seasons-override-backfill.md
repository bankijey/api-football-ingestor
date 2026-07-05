# Verifier report — 0002-seasons-override-backfill

**Result:** PASS
**Verified at:** 2026-07-05 19:24 (Berlin)
**Commit:** 32e51eb544f3acdd791101fcff65fd8a1f00e3c8

Verification env: fresh Python 3.12.10 venv (the local `.venv` is 3.10, which
cannot even import `datetime.UTC`; per spec §Out of scope this is a local-env
issue, so grading was done under a clean 3.12 environment as instructed).

## Acceptance criteria

1. [PASS] `make lint` exits 0 (`ruff check .` and `mypy src` both clean); the
   `cli.py` `UP017` error is gone.
   evidence: `ruff check .` → "All checks passed!" (exit 0); `mypy src` →
   "Success: no issues found in 31 source files" (exit 0). Committed
   `cli.py` now imports `from datetime import UTC, datetime` and `_to_epoch`
   uses `.replace(tzinfo=UTC)` (src/ingestor/cli.py:10, cli.py:173).

2. [PASS] `make test` exits 0 under 3.12; the three new
   `test_select_leagues_seasons_*` tests are collected and pass; `import
   ingestor` resolves without `PYTHONPATH=src`.
   evidence: `pytest -q` → "59 passed, 26 skipped, 1 xfailed" (exit 0); the
   26 skips are all "postgres not reachable" (env, not code). `pytest -k
   seasons` → "4 passed" (3 new + the current-only baseline). Package imports
   with no PYTHONPATH via `pythonpath = ["src"]` (pyproject.toml:63).

3. [PASS] `--seasons 2019,2020` maps to `RunArgs.seasons_override=[2019,2020]`
   and `select_leagues(payload, seasons=[2019,2020])` returns those seasons'
   `LeagueWork`s.
   evidence: `_merge_seasons(None, "2019,2020")` → `[2019, 2020]`; cli.py
   constructs `RunArgs(seasons_override=seasons)` (cli.py:71) and runner wires
   `select_leagues(..., seasons=args.seasons_override)`
   (src/ingestor/orchestrator/runner.py:143-145). Unit test
   `test_select_leagues_seasons_override_returns_those_seasons` passes.

4. [PASS] The commit contains the foreign feature + the two green-baseline
   fixes and nothing from 0001.
   evidence: `git show --stat HEAD` lists exactly: LOG.md, pyproject.toml,
   cli.py, db/connection.py, orchestrator/runner.py, selection/league_filter.py,
   tests/test_selection_filters.py. No projection.py, test_projection.py,
   config.py, or .env.example.

5. [PASS] After the commit, working tree shows ONLY 0001's residue uncommitted.
   evidence: `git status --porcelain` →
   ` M src/ingestor/config.py`, ` M src/ingestor/orchestrator/runner.py`,
   `?? .env.example`, `?? src/ingestor/projection.py`,
   `?? tests/test_projection.py` — exactly the AC5 set, nothing extra. The
   projection hook is still present in working-tree runner.py
   (runner.py:114-115, 200-210).

6. [PASS] Committed runner.py has no projection-hook / `matcher_db_dsn` refs.
   evidence: `git show HEAD:src/ingestor/orchestrator/runner.py | grep -E
   'build_projection|_project_events|_should_project|matcher_db_dsn'` → empty.

7. [PASS] No `DECISIONS.md` entry touched; bronze tables and bronze write path
   byte-identical.
   evidence: DECISIONS.md not in commit; no migrations / bronze-writer /
   bronze-table files in `git show --stat HEAD`. connection.py change is the
   pool-wrapper type (Simple→Threaded), not bronze write logic.

## Housekeeping

- [PASS] Files modified are a subset of §Files
  evidence: commit touches only cli.py, league_filter.py, connection.py,
  runner.py, tests/test_selection_filters.py, pyproject.toml, LOG.md — all
  listed under §Files "Modified (commit these)".
- [PASS] No new dependencies beyond §In scope
  evidence: `git show HEAD -- pyproject.toml` adds only `pythonpath = ["src"]`;
  no `dependencies`/`dev` changes.
- [PASS] No DECISIONS.md entries violated
  evidence: DECISIONS.md untouched; D2 (bronze-only exception) / D4 / D5
  unaffected — this is Phase-1 backfill plumbing, no projection code committed.
- [PASS] docs/ROADMAP.md not modified by implementor
  evidence: ROADMAP.md not in `git show --stat HEAD`; §1.8 still `[~]`.
- [PASS] Working tree carries ONLY the expected 0001 residue (spec AC5
  explicitly overrides the generic "tree must be empty" housekeeping item — a
  clean tree here would be a FAIL, since it would mean 0001's residue was lost).
  evidence: `git status --porcelain` matches the AC5 set exactly (see AC5).
- [PASS] `LOG.md` line appended for this turn
  evidence: LOG.md:19 — implementor line
  `2026-07-05 18:30 Berlin | implementor | 0002-seasons-override-backfill |
  implemented | ...`.

## Findings

None blocking. Minor observations for the coordinator (do NOT fold into this
task — it is done):

1. The verifier README housekeeping item "Working tree clean (`git
   status --porcelain` empty)" directly conflicts with this task's AC5 (residue
   must remain). It was resolved in favour of the task spec. The coordinator may
   want to add a "clean tree unless the task states otherwise" carve-out to the
   verifier README to avoid future ambiguity.
2. `_merge_seasons(2021, "2019,2020")` yields `[2021, 2019, 2020]` (dedup, first
   seen order) — order follows single-then-csv, not sorted. `select_leagues`
   uses set membership so order is irrelevant to behaviour; noted only in case a
   future task wants deterministic sorted ordering.
