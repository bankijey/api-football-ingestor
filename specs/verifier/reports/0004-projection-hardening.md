# Verifier report — 0004-projection-hardening

**Result:** PASS
**Verified at:** 2026-07-06 15:42 (Berlin)
**Commit:** 11493f40593fdfa1964f2c8358066299e9eea6c2

## Acceptance criteria

1. [PASS] `make lint` (ruff + mypy) exits 0.
   evidence: `ruff check .` → "All checks passed!" (exit 0); `mypy src` →
   "Success: no issues found in 31 source files" (exit 0).
2. [PASS] `make test` exits 0; all pre-existing `tests/test_projection.py`
   tests still pass unchanged.
   evidence: `pytest -q` → `87 passed, 1 xfailed in 17.22s` (0 skips, run
   against live `ingestor-postgres` @ localhost:5434). `git diff` of
   `tests/test_projection.py` has NO deletions — pre-existing tests are
   byte-identical, only the streaming test + spy helpers were appended. The 5
   pre-existing projection tests (`…keeps_only_ns_future_with_full_columns`,
   `…reflects_only_newest_ingest_per_league_season`,
   `…atomic_replace_keeps_prior_snapshot_on_mid_write_failure`,
   `…empty_bronze_yields_empty_table`, `…should_project_gate`) all PASS.
3. [PASS] F3 static check: no `.fetchall()` in the bronze read path; `_read_rows`
   obtains a server-side cursor via `conn.cursor(name=…)`.
   evidence: `grep -n fetchall src/ingestor/projection.py` → only a comment
   (projection.py:98); read path is `conn.cursor(name="apifootball_proj_read")`
   (projection.py:104) iterated with `for (payload,) in cur:` (projection.py:108),
   no fetchall. Diff confirms `_read_rows` is the only function changed.
4. [PASS] F3 behavior: `tests/test_projection.py::test_read_streams_with_server_side_cursor`
   seeds one NS+future (projects) + one FT/past (dropped) payload, asserts rows
   == the single projected row (`fixture_id==401`, `e_id=="apifootball;401"`),
   and asserts a NAMED cursor via a `conn.cursor` spy capturing the `name` kwarg.
   evidence: test PASSED (verbose run). Spy (`_ConnSpy`/`_PoolSpy`,
   test_projection.py:156-205) asserts `any(name for name in names)` — fails for
   an unnamed cursor.
5. [PASS] F1: `tests/test_config.py::test_matcher_dsn_dialect_normalized` asserts
   `postgresql+psycopg2://u:p@h:5432/db` → `postgresql://u:p@h:5432/db`, bare
   `postgresql://…` unchanged, and `""` stays `""`.
   evidence: test PASSED. Validator at config.py:100-112 splits scheme on `+`,
   preserves everything after `://` byte-identically.
6. [PASS] `git diff` for this task touches ONLY the seven §Files files.
   evidence: implementor commit 11493f4 touched exactly 6 code/doc files
   (`.env.example`, `LOG.md`, `src/ingestor/config.py`, `src/ingestor/projection.py`,
   `tests/test_config.py`, `tests/test_projection.py`) — all in §Files.
   `docs/ROADMAP.md` (the 7th) was changed only by the coordinator commit 372f406,
   as the spec assigns.
7. [PASS] No new dependencies (`pyproject.toml` unchanged).
   evidence: `git diff --name-only 8e69672 11493f4 | grep pyproject` → no match.
8. [PASS] No `DECISIONS.md` violated.
   evidence: projection.py diff changes ONLY `_read_rows`; `_to_row` (D2/D6
   field-extraction + `EVENT_COLUMNS`), `_LATEST_FIXTURES_SQL`/`_INSERT_SQL`
   (D3), and `_write_atomic` (D4 single-transaction replace) are untouched. D5:
   matcher DSN normalization is a pure settings-load string transform; the
   projection still writes only the sources DB. AC2 proves the row set is
   byte-identical.

## Housekeeping

- [PASS] Files modified are a subset of §Files
  evidence: implementor commit 11493f4 = {.env.example, LOG.md, config.py,
  projection.py, test_config.py, test_projection.py}; ROADMAP owned by coordinator.
- [PASS] No new dependencies beyond §In scope
  evidence: pyproject.toml not in diff.
- [PASS] No DECISIONS.md entries violated
  evidence: D2/D3/D4/D6 code paths (`_to_row`, SQL, `_write_atomic`) unchanged;
  D5 write target unchanged. See AC8.
- [PASS] docs/ROADMAP.md not modified by implementor
  evidence: `git show --stat 11493f4` lists no `docs/ROADMAP.md`; 0004 remains
  `[~]` (coordinator flips to `[x]` on close).
- [PASS] Working tree clean (`git status --porcelain` empty)
  evidence: `git status --porcelain` returned no output at HEAD 11493f4.
- [PASS] `LOG.md` line appended for this turn
  evidence: `2026-07-06 17:20 Berlin | implementor | 0004-projection-hardening |
  implemented | …` (LOG.md).

## Findings

None blocking. Minor observations for the coordinator (do NOT fold into 0004 —
it is done):

1. The `_ITERSIZE = 200` batch size is not asserted anywhere; the streaming test
   proves the cursor is named but not that batching bounds memory (hard to unit
   test). Fine as-is — the memory win is inherent to a server-side cursor. No
   action needed.
2. Test suite runs under Python 3.10.11 in `.venv` (project targets 3.12). All
   green here, but the CI/lint target Python version is worth confirming before
   0005's full-catalogue run. Out of scope for this task.
