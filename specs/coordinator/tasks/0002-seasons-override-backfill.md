# 0002 — Land the pending multi-season backfill + restore a green baseline

**Roadmap item:** §1.8 — Backfill & replay (multi-season enhancement)
**Depends on:** none (this is a *precursor* to 0001 — it must land first)
**Blocks:** `0001-apifootball-events-projection` (paused until this commits)
**Status:** open

## Goal

A coherent, already-implemented but **uncommitted** feature is sitting in the
working tree and is entangled with 0001's projection work — it blocks 0001 from
a clean, lint-green handoff (see
`specs/implementor/notes/0001-apifootball-events-projection.md`, commit
`55078f3`). This task **commits that pre-existing feature on its own** and
restores a green `make lint` / `make test` baseline, so 0001 can then resume on a
clean tree. No new feature work — you are landing, lint-fixing, and green-lighting
code that already exists in the tree. This does not touch any `DECISIONS.md`
scope (it is Phase-1 backfill plumbing, not bronze or the projection).

## In scope

The pre-existing (foreign to 0001) uncommitted change set, to be committed as ONE
commit:

### Multi-season backfill feature — already written, just commit
- `src/ingestor/cli.py` — `--seasons` (csv) + `--allow-seasons-without-dates`
  flags; `_merge_seasons(...)` and `_guard_seasons_with_window(...)` helpers;
  `RunArgs(season_override=…)` → `RunArgs(seasons_override=…)` wiring.
- `src/ingestor/selection/league_filter.py` — `select_leagues(..., seasons=…)`:
  when `seasons` is set it replaces the `current=true` filter (historical
  backfill); otherwise unchanged.
- `src/ingestor/orchestrator/runner.py` — **ONLY** the `RunArgs.season_override:
  int` → `seasons_override: list[int] | None` field change and the
  `select_leagues(..., seasons=args.seasons_override)` call wiring. See the
  runner.py note under §Files — this file is shared with 0001 and you must NOT
  commit 0001's projection hook.
- `tests/test_selection_filters.py` — the three new
  `test_select_leagues_seasons_*` tests (already written).

### Bundled connection-pool fix — already written, just commit
- `src/ingestor/db/connection.py` — `SimpleConnectionPool` →
  `ThreadedConnectionPool` (thread-safety fix; part of the same uncommitted
  batch, correct on its own merits, and 0001 depends on a thread-safe pool for
  its second sources-DB connection).

### Lint fix required to make the feature green
- `src/ingestor/cli.py` — fix the `UP017` ruff error the feature introduced at
  `_to_epoch` (`datetime.strptime(...).replace(tzinfo=timezone.utc)`): use
  `datetime.UTC` instead of `timezone.utc` (import `UTC` from `datetime`; drop
  the now-unused `timezone` import if applicable). This is the only lint error
  `ruff check .` reports besides 0001's own (already fixed) one.

### Test-import plumbing so `make test` is runnable
- `pyproject.toml` — add `pythonpath = ["src"]` under
  `[tool.pytest.ini_options]`. `make test` is a bare `pytest -q` with no editable
  install, so `import ingestor` currently fails `ModuleNotFoundError` on a fresh
  checkout. This one-line change lets the suite import the package without
  `PYTHONPATH=src`. (Nothing else in `[tool.pytest.ini_options]` changes.)

## Out of scope
- **0001's projection work.** Do NOT commit, delete, or modify
  `src/ingestor/projection.py`, `tests/test_projection.py`, the `matcher_db_dsn`
  addition in `src/ingestor/config.py`, `.env.example`, or the projection hook
  (`_should_project` / `_project_events` / the `build_projection` import + call
  site) in `runner.py`. Those stay **uncommitted in the working tree** for 0001's
  resume. You are the precursor; you do not touch 0001's deliverable.
- **New backfill behaviour** beyond what is already in the tree. Do not add a
  `--fixture-ids` flag or new date logic; land what exists.
- **Reworking the connection pool** beyond the Simple→Threaded swap already
  present.
- **Fixing the local venv Python version.** The escalation note's
  `.venv is 3.10 vs requires-python >=3.12` is a local-environment issue, not a
  repo defect — the repo correctly pins 3.12. Verify under a 3.12 environment; do
  not downgrade `requires-python` or add shims.

## Files
Created: none.

Modified (commit these — the foreign feature + green-baseline fixes):
- `src/ingestor/cli.py` — flags + helpers + `seasons_override` wiring + `UP017` fix
- `src/ingestor/selection/league_filter.py` — `seasons=` filter
- `src/ingestor/db/connection.py` — `ThreadedConnectionPool`
- `src/ingestor/orchestrator/runner.py` — **seasons_override hunks ONLY** (see Notes)
- `tests/test_selection_filters.py` — three new seasons tests
- `pyproject.toml` — `pythonpath = ["src"]`
- `docs/ROADMAP.md` — coordinator flips this checkbox on close (NOT implementor)
- `LOG.md` — implementor appends one line on commit

Must remain UNCOMMITTED (0001's, leave in the working tree): `projection.py`,
`tests/test_projection.py`, `config.py`, `.env.example`, and the projection-hook
hunks in `runner.py`.

If anything outside this list needs changing, STOP and append to the note at
`specs/implementor/notes/0002-seasons-override-backfill.md`.

## Acceptance criteria (Definition of Done)
1. `make lint` exits 0 (`ruff check .` and `mypy src` both clean). In
   particular the `cli.py` `UP017` error is gone.
2. `make test` exits 0 in a Python 3.12 environment; the three new
   `tests/test_selection_filters.py::test_select_leagues_seasons_*` tests are
   collected and pass. `import ingestor` resolves without `PYTHONPATH=src`
   (i.e. the `pythonpath` config works).
3. `--seasons 2019,2020` on the CLI maps to `RunArgs.seasons_override=[2019,2020]`
   and `select_leagues(payload, seasons=[2019,2020])` returns those seasons'
   `LeagueWork`s (covered by the existing/new unit tests).
4. The commit contains the foreign feature + the two green-baseline fixes and
   **nothing from 0001**: `git show --stat` for this task's commit lists only the
   §Files "Modified (commit these)" set — no `projection.py`,
   `test_projection.py`, `config.py`, or `.env.example`.
5. After this commit, `git diff --stat` (working tree) shows ONLY 0001's residue
   still uncommitted: `projection.py`, `tests/test_projection.py`, `config.py`,
   `.env.example`, and `runner.py` (projection-hook hunks). The projection hook is
   still present in the working-tree `runner.py`.
6. The committed `runner.py` does NOT reference `build_projection`,
   `_project_events`, `_should_project`, or `matcher_db_dsn`
   (`git show HEAD:src/ingestor/orchestrator/runner.py | grep -E
   'build_projection|_project_events|_should_project|matcher_db_dsn'` is empty) —
   proving the hook was not committed here.
7. No `DECISIONS.md` entry touched; bronze tables and the bronze write path are
   byte-identical.

## Notes for the implementor

**The runner.py split is the crux.** The working-tree `runner.py` currently holds
BOTH the foreign `seasons_override` change AND 0001's projection hook, and both
are staged. Commit only the seasons_override hunks. A safe, non-interactive
recipe (`git add -p` is unavailable here):

1. Unstage everything: `git restore --staged .` (working tree is untouched — it
   still holds both change sets).
2. Back up the current runner.py (it has both):
   `cp src/ingestor/orchestrator/runner.py "<scratch>/runner.both.py"`.
3. Rebuild runner.py as **seasons-only**: start from HEAD
   (`git show HEAD:src/ingestor/orchestrator/runner.py > src/ingestor/orchestrator/runner.py`)
   and re-apply ONLY the seasons hunks — the `RunArgs` field
   `season_override: int | None` → `seasons_override: list[int] | None`, and the
   `select_leagues(..., seasons=args.seasons_override)` wiring. Do NOT re-add
   `_should_project`, `_project_events`, the `from ..projection import
   build_projection` import, or the hook call site. Confirm with the AC6 grep.
4. Stage exactly the §Files "commit these" set (the four foreign files with the
   seasons-only runner.py, plus `pyproject.toml` and the `cli.py` UP017 fix) and
   commit. Subject e.g.
   `0002-seasons-override-backfill: land pending backfill + green baseline`.
5. Restore 0001's residue to the working tree:
   `cp "<scratch>/runner.both.py" src/ingestor/orchestrator/runner.py` so the
   projection hook is back (uncommitted). Verify AC5: `git status` shows
   `projection.py`, `test_projection.py`, `config.py`, `.env.example`, and
   `runner.py` still modified/untracked and uncommitted.

**Do not use `git add -A` / `git commit -a`** — that would sweep 0001's residue
into this commit and blow AC4/AC5.

**Lint fix specifics:** `ruff` rule `UP017` wants `datetime.UTC` over
`timezone.utc`. Change the `_to_epoch` `.replace(tzinfo=timezone.utc)` to
`.replace(tzinfo=UTC)` and adjust the `datetime` import accordingly. Run
`ruff check .` to confirm zero errors before committing.

**Handoff:** working tree is NOT fully clean after this task — by design it still
carries 0001's uncommitted residue (AC5). That is the expected state; the
Coordinator will resume 0001 next.

## Verifier checklist (mirror of DoD, plus housekeeping)
- [ ] AC1 — `make lint` green (UP017 gone)
- [ ] AC2 — `make test` green under 3.12; new seasons tests collected; `pythonpath` works
- [ ] AC3 — `--seasons` maps through to `select_leagues(seasons=…)`
- [ ] AC4 — commit contains foreign feature + green-baseline fixes only; no 0001 files
- [ ] AC5 — 0001 residue still uncommitted in the working tree (incl. runner.py hook)
- [ ] AC6 — committed runner.py has no projection-hook / `matcher_db_dsn` references
- [ ] AC7 — no `DECISIONS.md` violated; bronze untouched
- [ ] `docs/ROADMAP.md` checkbox not flipped by implementor (coordinator owns it)
- [ ] `LOG.md` line appended with a real SHA
