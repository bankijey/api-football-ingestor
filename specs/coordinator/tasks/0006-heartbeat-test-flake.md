# 0006 — De-flake `test_heartbeat_ticks_at_interval` (timing race)

**Roadmap item:** §1.11 — Green-baseline hygiene (0003/0005 finding V1)
**Depends on:** none (test-only).
**Status:** open

## Goal

`tests/test_heartbeat.py::test_heartbeat_ticks_at_interval` is timing-flaky: it
starts a heartbeat at `interval_sec=0.05`, does a fixed `time.sleep(0.18)`, then
asserts `checkpoints.heartbeat.call_count >= 3` (test_heartbeat.py:14-17). The
heartbeat's wait is real wall-clock (`threading.Event.wait(interval)`,
[heartbeat.py:55](../../src/ingestor/heartbeat.py)); under Windows ~15 ms timer
granularity or CPU saturation each wait overshoots, so the fixed 0.18 s window
catches only 2 ticks and the test fails. It is green on an unloaded run and in
the 0001/0002 verified commits, so it is **environmental jitter, not a code
defect** — but it undermines every future `make test` gate. This task removes the
race. **Test-only; no production code changes.**

## In scope — design decision: bounded poll (wait-until-target), not a fake clock
Replace the fixed-`sleep` + exact-count race with a **bounded poll**: after
starting the heartbeat, wait up to a **generous deadline** for the tick count to
reach the target, then assert. A slow machine simply takes longer (still well
under the deadline) instead of failing at the 0.18 s boundary. Intent is
preserved — it still proves the immediate tick **plus** ≥2 interval ticks.

- **`tests/test_heartbeat.py::test_heartbeat_ticks_at_interval`** — poll
  `checkpoints.heartbeat.call_count` until `>= 3` or a generous deadline (e.g.
  `time.monotonic() + 2.0`, ≥ ~40× the ~0.1 s the 3 ticks actually need) elapses;
  then `assert call_count >= 3` and keep `heartbeat.assert_called_with(rid)`.
  Poll with a short `time.sleep(0.01)`. Do the wait **inside** the `with
  Heartbeat(...)` block so ticks are still firing.
- **`tests/test_heartbeat.py::test_heartbeat_swallows_exceptions`** — same fixed
  0.12 s → bounded poll (target `>= 2`), since it shares the identical
  fixed-sleep race.
- `test_heartbeat_double_start_is_noop` — leave unchanged (no timing race).

**Why not a fake/injected clock:** it would require adding an injectable
wait/clock to `Heartbeat` — a production change to a working class for no
reliability gain over a generous deadline. Rejected; keep this test-only.

## Out of scope
- **Any change to `src/ingestor/heartbeat.py`** (or any `src/` file). If you think
  the class needs an injectable clock, STOP and escalate — this task is test-only.
- **New test dependencies** (e.g. `pytest-repeat`, `pytest-timeout`). Use the
  stdlib (`time.monotonic` poll loop). `pyproject.toml` must not change.
- The dead-man's-switch / stale-heartbeat monitor (a future observability task).
- Touching the other heartbeat tests' intent or any unrelated test.

## Files
Modified:
- `tests/test_heartbeat.py` — bounded-poll the two timing-based tests
- `docs/ROADMAP.md` — coordinator flips `0006 [~]→[x]` + Progress-log ON CLOSE
- `LOG.md` — implementor appends one line on commit

No `src/`, no `pyproject.toml`. If one must change, STOP and escalate at
`specs/implementor/notes/0006-heartbeat-test-flake.md`.

## Acceptance criteria (Definition of Done)
1. `make lint` (ruff + mypy) exits 0.
2. `make test` exits 0; all heartbeat tests pass.
3. The fixed-`sleep`-then-exact-assert race is gone: both timing tests use a
   bounded poll with a deadline (no bare `time.sleep(0.18)` / `time.sleep(0.12)`
   gating the assertion). Intent preserved — `test_heartbeat_ticks_at_interval`
   still asserts `>= 3` (immediate + ≥2 interval ticks) and
   `heartbeat.assert_called_with(rid)`.
4. Non-flakiness demonstrated: `tests/test_heartbeat.py` run **20× in a row**
   passes every time (e.g.
   `for i in $(seq 20); do pytest -q tests/test_heartbeat.py || break; done`),
   including at least one run under load — record the loop output in the commit
   or the implementor note.
5. `git diff` touches ONLY `tests/test_heartbeat.py`, `docs/ROADMAP.md`
   (coordinator), `LOG.md`. `src/ingestor/heartbeat.py` is byte-identical.
6. No new dependencies (`pyproject.toml` unchanged).

## Verifier checklist (mirror of DoD + housekeeping)
- [ ] AC1–AC4 — run `make lint`/`make test`; run the 20× loop and confirm zero
      failures; confirm the assertion intent (`>= 3`, `assert_called_with`) is kept
- [ ] AC5 — diff confined to the test + roadmap + log; `heartbeat.py` untouched
- [ ] AC6 — no new dependencies
- [ ] No `DECISIONS.md` violated; working tree clean; `LOG.md` line appended

## Notes for the implementor
- The bug is the **fixed sleep + exact count**, not the heartbeat. A generous
  deadline (~2 s for a target reachable in ~0.1 s) makes slow machines pass by
  taking longer, not by asserting less.
- Keep the poll **inside** the `with Heartbeat(...)` context so the loop is still
  ticking while you wait; break as soon as the target is reached to keep the test
  fast on healthy machines.
- Do not weaken the assertion below `>= 3` for the interval test — that count is
  what proves periodic ticking (immediate + repeats); a lower bound would let a
  one-shot heartbeat pass.
