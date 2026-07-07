# Escalation — 0001-apifootball-events-projection

**Status:** BLOCKED on handoff. Task code is implemented and validated; the
blocker is a contaminated working tree that predates this turn and cannot be
resolved without touching files outside `§Files`.

## Summary

The task itself is complete and green (see "State" below). But the working tree
was **already dirty when this turn started** — the session-start `git status`
listed `cli.py`, `db/connection.py`, `orchestrator/runner.py`,
`selection/league_filter.py`, and `tests/test_selection_filters.py` as modified.
Those changes form a **single coherent, uncommitted feature** — a
`seasons_override` / date-range backfill (RunArgs field renamed
`season_override: int` → `seasons_override: list[int]`, `select_leagues(...,
seasons=...)`, matching `cli.py` wiring and `test_selection_filters.py` tests).
None of these five files (except `runner.py`) are in this task's `§Files`, and
the feature was never committed (git log shows the last two commits touched only
`LOG.md` / `specs/` — the bootstrap + coordinator draft).

This produces three problems for a clean, in-scope handoff:

1. **Entanglement in `runner.py`.** My projection hook and the pre-existing
   `seasons_override` hunks live in the same file, so I cannot produce a clean
   task-only commit without either dropping the foreign hunks (which would break
   `league_filter.py`/`cli.py`, which depend on the new `seasons=` signature) or
   sweeping foreign work into my commit (scope violation).
2. **`make lint` (AC1) fails outside `§Files`.** `ruff check .` errors on
   `cli.py:175` (`UP017` — `timezone.utc` → `datetime.UTC`), a line that only
   exists in the uncommitted feature. I must not fix `cli.py` (outside `§Files`;
   pre-fixing the gap is explicitly forbidden), so AC1 cannot go green while that
   feature sits uncommitted.
3. **Broken host test env (informational).** `.venv` is Python **3.10.11** but
   `pyproject` requires `>=3.12`, and the package isn't importable
   (`ModuleNotFoundError: No module named 'ingestor'`) unless `PYTHONPATH=src` is
   set — `make test` is a bare `pytest -q` with no `pythonpath`/editable install.
   Not my regression, but it means AC1's `make test` won't pass as-is on the host.

## Evidence

- `git status --porcelain` (unstaged, pre-existing, outside §Files):
  `M src/ingestor/cli.py`, `M src/ingestor/db/connection.py`,
  `M src/ingestor/selection/league_filter.py`,
  `M tests/test_selection_filters.py` (+ `runner.py`, which I also edit).
- `git show HEAD:src/ingestor/cli.py` has no `_to_epoch` — confirming the
  `UP017` line is from the uncommitted feature, not from HEAD.
- `git log --oneline -4`: last two commits touched only `LOG.md`/`specs/`; the
  feature was never committed.
- `ruff check .` → `Found 2 errors` — `cli.py:175 UP017` (foreign) and (now
  fixed) `test_projection.py B905` (mine).
- My task code, validated against the real Postgres (`.env` DSN, localhost:5434):
  `TEST_DB_DSN=... PYTHONPATH=src pytest tests/test_projection.py -q` → **5 passed**
  (AC3 mapping + full D6 columns, AC4 semicolon, AC5 atomic-swap-intact-on-failure,
  AC6 gate, AC7 latest-per-league/season). Gate unit test is DB-free and passes.

## Options

- **A (recommended) — Coordinator lands the `seasons_override` feature first.**
  Open a coordinator task (or amend) to commit the pre-existing feature (and fix
  the `cli.py` `UP017`) as its own change, plus fix the venv (Python 3.12 +
  editable install / `pythonpath = ["src"]`). Then re-route 0001 to the
  implementor for a clean commit on a clean tree. Cleanest boundary; keeps 0001's
  history uncontaminated.
- **B — Authorize 0001 to absorb the feature.** Expand 0001's `§Files` to include
  the four extra files, and let the implementor commit everything + fix lint.
  Fast, but merges two unrelated changes into one task/commit.
- **C — Commit 0001 on top of the dirty tree.** Stage only 0001's hunks and
  commit; leave the feature uncommitted. Gets the projection landed, but the tree
  stays dirty and `make lint` stays red until the feature is handled — AC1 fails.

Recommendation: **A**. The feature is real and passing; it deserves its own
commit, and 0001 verifies cleanly only on a tree where lint is green.

## State (what's staged / uncommitted)

Per the escalation carve-out, my task production work is left **uncommitted** in
the working tree (evidence to salvage, not discard):

- Created: `src/ingestor/projection.py`, `tests/test_projection.py`, `.env.example`
- Modified (mine): `src/ingestor/config.py` (`matcher_db_dsn`),
  `src/ingestor/orchestrator/runner.py` (projection hook + `_should_project` /
  `_project_events`; note this file ALSO carries the foreign `seasons_override`
  hunks).
- Pre-existing/foreign, untouched by me: `cli.py`, `db/connection.py`,
  `selection/league_filter.py`, `tests/test_selection_filters.py`.

Only this note + the `LOG.md` escalation line are committed this turn.
