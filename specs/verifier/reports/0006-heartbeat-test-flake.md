# Verifier report — 0006-heartbeat-test-flake

**Result:** PASS
**Verified at:** 2026-07-07 09:35 (Berlin)
**Commit:** 8da71f3

## Acceptance criteria

1. [PASS] `make lint` (ruff + mypy) exits 0.
   evidence: `ruff check .` → "All checks passed!"; `mypy src` → "Success: no
   issues found in 31 source files" (run via `.venv/Scripts`).
2. [PASS] `make test` exits 0; all heartbeat tests pass.
   evidence: `pytest -q` → `60 passed, 27 skipped, 1 xfailed` (0 failed); the 27
   skips are DB-unreachable (no local Postgres), same environmental skips the
   0008 verifier recorded — none is a heartbeat test. `test_heartbeat.py` runs
   3/3 green in isolation.
3. [PASS] The fixed-`sleep`-then-exact-assert race is gone: both timing tests use
   a bounded poll with a deadline; intent preserved.
   evidence: test_heartbeat.py:12-25 `_poll_until` (2.0 s `time.monotonic`
   deadline, 0.01 s spin); the two `time.sleep(0.18)`/`sleep(0.12)` gates are
   replaced by `_poll_until(...)` *inside* the `with Heartbeat(...)` block
   (test_heartbeat.py:32-33, 44-45). `test_heartbeat_ticks_at_interval` still
   asserts `>= 3` and `heartbeat.assert_called_with(rid)` (:35-36); swallows
   test targets `>= 2` (:45-46). No bare sleep gates the assertion.
4. [PASS] Non-flakiness: `tests/test_heartbeat.py` run 20× passes every time,
   including under load.
   evidence: 20/20 rc=0 loop (0 failures); a further 6/6 under genuine 4-process
   CPU load also green (0 failures) — load-run 4 took 2.20 s, proving a loaded
   machine passes by taking longer, not by asserting less. 26 total runs, 0
   failures. Implementor also recorded 20/20 under 4-core load in the LOG line.
5. [PASS] `git diff` touches ONLY `tests/test_heartbeat.py`, `LOG.md`
   (`docs/ROADMAP.md` is the coordinator's on close); `heartbeat.py`
   byte-identical.
   evidence: `git diff --name-only HEAD~1 HEAD` → `LOG.md`,
   `tests/test_heartbeat.py`; `git diff HEAD~1 HEAD -- src/ingestor/heartbeat.py`
   empty (byte-identical). ROADMAP 0006 still `[~]` (not flipped by implementor).
6. [PASS] No new dependencies (`pyproject.toml` unchanged).
   evidence: `git diff HEAD~1 HEAD -- pyproject.toml` empty; `_poll_until` uses
   only stdlib `time.monotonic`/`time.sleep`.

## Housekeeping

- [PASS] Files modified are a subset of §Files
  evidence: `LOG.md`, `tests/test_heartbeat.py` — both listed in §Files; ROADMAP
  correctly untouched by implementor.
- [PASS] No new dependencies beyond §In scope
  evidence: `pyproject.toml` diff empty.
- [PASS] No DECISIONS.md entries violated
  evidence: test-only change; no `src/`, no projection, no DB path touched
  (D2/D4/D5 untouched).
- [PASS] docs/ROADMAP.md not modified by implementor
  evidence: not in diff; 0006 still `[~]` at ROADMAP.md:219.
- [PASS] Working tree clean (`git status --porcelain` empty)
  evidence: `git status --porcelain` returned nothing.
- [PASS] `LOG.md` line appended for this turn
  evidence: `2026-07-07 09:20 Berlin | implementor | 0006-heartbeat-test-flake |
  implemented | ...`.

## Findings

None blocking. Minor, non-blocking observation for the coordinator (do NOT fold
into this task — it's done): the 27 DB-dependent test skips are an environmental
gap on the verifier host (no reachable local Postgres), not a defect of this or
any prior task; if the workflow ever wants those exercised in the standard gate,
a coordinator task could stand up an ephemeral Postgres for `make test`. Purely
optional.
