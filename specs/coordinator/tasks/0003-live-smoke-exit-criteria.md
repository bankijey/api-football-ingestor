# 0003 — Live smoke: Phase 1 exit criteria + projection E2E

**Roadmap item:** Phase 1.6 §1.11
**Depends on:** 0001 (projection, PASS `d7f125e`), 0002 (green baseline, PASS
`c582c95`). Gates: `arbibet-matcher` Phase B (its live smoke needs
`apifootball_events` populated for real).
**Status:** open

## Goal

Nothing in this repo has ever touched the real API — every green test is
hermetic. This task runs the ingestor **live**, quota-bounded, and proves the
six Phase 1 exit criteria plus the 0001 projection end-to-end, with
**DB/ledger evidence instead of pytest**. It is an *operational* task: the
implementor executes a procedure and records evidence; the verifier
independently re-queries to corroborate. Ideally **zero production code
changes** — any needed code change is a finding that STOPs and escalates
(that's the point of a smoke).

## Procedure (in scope)

Run everything against the real API-Football key (env only, never committed)
and the live docker-compose stack. Record every command + queried result in
`docs/SMOKE_0003_EVIDENCE.md` as you go (command, timestamp Berlin, output
snippet).

### S1 — Bounded live run (exit criterion: full run completes)
- `make ingest` (or the CLI directly) with `--leagues <5–10 handpicked ids>`
  and the current `--season`. Choose leagues with rich coverage flags and
  fixtures inside the lookback window (suggested: EPL 39, La Liga 140, Serie A
  135, Bundesliga 78, Ligue 1 61 — coordinator may substitute).
- Evidence: `ingestion_runs` row with `status='succeeded'`, non-null
  `finished_at`, counters populated; `run.done` log line.
- Quota math for the record: Phase A ≈ 1 + N calls; Phase B ≈ 2 per recent
  fixture. Note observed call counts + `x-ratelimit` headroom in the evidence
  file.

### S2 — Phase B rich data (exit criterion)
- Evidence: `bronze_fixture_details` and `bronze_halftime_stats` rows exist for
  fixtures of the subset leagues within the lookback window; one sample payload
  per table spot-checked to contain lineups/statistics (`jsonb` path probe).

### S3 — Idempotent re-run (exit criterion: hash dedup)
- Immediately re-run S1 with identical args.
- Evidence: bronze row-count delta across all four bronze tables ≈ 0 (report
  exact before/after counts); `bronze_latest_hash.last_checked_at` advanced
  while `last_changed_at` did not (sample).

### S4 — Crash resume (exit criterion)
- Start a fresh S1-style run; kill the process mid-Phase-A (`docker kill` or
  SIGKILL — ungraceful on purpose). Re-run with `--resume <run_id>`.
- Evidence: resumed run reaches `succeeded`; checkpoints show
  pending→succeeded without re-doing completed keys; no duplicate bronze rows
  (per-endpoint counts equal to a single clean run's).

### S5 — Failure boundary + recovery (exit criterion: DLQ + retryable)
The per-item `dead_letter` mechanic (a failed league/fixture fetch is isolated,
recorded in `dead_letter` with error class + endpoint, its checkpoint marked
`failed` while siblings still `succeed`) is **not code-free reachable live**:
every operator-controlled failure lever (invalid key, bad host, no network) is
*global*, so it fails the **un-isolated `/leagues` bootstrap**
(`runner.py:147`, outside `run_phase_a`'s try/except) first and aborts the run
before any per-item `record_failure` runs — no `dead_letter` row is written.
That mechanic is therefore proven **hermetically** by
`tests/test_orchestrator.py::test_phase_a_isolates_one_failing_league`
(isolated 500 → exactly one `dead_letter` row + one `failed` checkpoint,
siblings `succeeded`), re-run green live under S7. What this step proves *live*
is that the failure boundary is **safe and recoverable**:
- **S5a (fail fast & safe):** re-run S1's args with an **invalid API key** (env
  override for that single invocation only; never touch `.env`). Evidence: the
  run does NOT reach `status='succeeded'`; bronze row counts across all four
  bronze tables are **unchanged** vs. the pre-S5a snapshot (a failed bootstrap
  writes no bronze); and per D4 the `apifootball_events` snapshot is
  **unchanged** (projection runs only on `succeeded`).
- **S5b (retryable/recovery):** restore the valid key and re-run: the run
  reaches `status='succeeded'` again — the work the invalid-key run could not do
  now completes. Note both invocations + the env restore in the evidence file.

### S6 — Projection E2E (the 0001 handshake, gates matcher Phase B)
- After S1's `succeeded` run, query the **sources DB**:
  - `SELECT count(*) FROM apifootball_events` > 0;
  - every `e_id` matches `^apifootball;[0-9]+$` (semicolon — D6);
  - `min(start) > now()` (NS+future only — D3);
  - columns `bookmaker_id='apifootball'`, `sport_key='football'`, `url IS NULL`.
- Re-check after S3's re-run: the snapshot refreshed (atomic replace ran again)
  and still satisfies the same assertions.

### S7 — Hermetic gates still green (exit criterion)
- `make lint` and `make test` on the same commit — both exit 0 (no code should
  have changed; this is a control, not a deliverable).

## Out of scope
- **The full ~1,500-league catalogue run** — task 0004, sequenced after this.
- **Any production code change.** A bug found here = STOP, escalate with the
  evidence; the fix becomes a scoped follow-up task.
- **The matcher's live smoke** — `arbibet-matcher` Phase B, gated on S6.
- **Scheduling/cron for the daily run** — after 0004 sizes it.

## Files
Created:
- `docs/SMOKE_0003_EVIDENCE.md` — the evidence log (commands, outputs, counts)

Modified:
- `docs/ROADMAP.md` — coordinator flips `0003 [~]→[x]` + Progress-log ON CLOSE
- `LOG.md` — implementor appends one line on commit

NO production/source files. If one must change, STOP and escalate at
`specs/implementor/notes/0003-live-smoke-exit-criteria.md`.

## Acceptance criteria (Definition of Done)
1. S1: `ingestion_runs` shows a bounded live run with `status='succeeded'`,
   counters populated; evidence file records the run_id and call counts.
2. S2: rich fixture details + halftime stats rows exist for the subset; sample
   payloads contain the embedded blocks.
3. S3: re-run bronze delta ≈ 0 rows (exact counts recorded);
   `last_checked_at` advanced, `last_changed_at` unchanged (sample).
4. S4: killed run + `--resume` reaches `succeeded`, no duplicate bronze rows.
5. S5: the invalid-key run does NOT reach `succeeded` and leaves bronze (all
   four tables) + the `apifootball_events` snapshot byte-for-byte unchanged (D4
   boundary); the valid-key re-run reaches `succeeded`. The per-item
   `dead_letter`+retryable mechanic is confirmed via S7's `make test`
   (`test_phase_a_isolates_one_failing_league`), NOT via the live invalid-key
   run (see S5 for why it is not code-free reachable live).
6. S6: `apifootball_events` in the sources DB is non-empty, all `e_id`s match
   `^apifootball;[0-9]+$`, all `start` in the future, constants correct; and
   the snapshot re-refreshed on S3's re-run.
7. S7: `make lint` + `make test` exit 0 on the unchanged commit.
8. `git diff` for this task touches ONLY `docs/SMOKE_0003_EVIDENCE.md`,
   `docs/ROADMAP.md` (coordinator), `LOG.md`.
9. No secrets in any committed file (the API key appears nowhere in the diff).

## Verifier checklist (mirror of DoD + housekeeping)
- [ ] AC1–AC7 — corroborate by independently re-running the queries in the
      evidence file against the live DBs (do not take the file's word)
- [ ] AC8 — diff confined to evidence/roadmap/log files
- [ ] AC9 — no secrets committed
- [ ] No `DECISIONS.md` violated (D4 gating/atomicity observed live; bronze
      untouched by the procedure)
- [ ] Working tree clean on handoff; `LOG.md` line with real SHA

## Notes for the implementor
- **You are an operator this cycle, not a coder.** The deliverable is evidence.
  Copy actual command output into the evidence file — summaries don't count.
- The projection hook only fires when `MATCHER_DB_DSN` is set (accepted 0001
  guard) — confirm env is loaded before S1 or S6 will be vacuously empty.
- **S1/S6 need a `succeeded` run, not `partial`.** `_terminal_status`
  (`runner.py:194`) returns `succeeded` only when Phase A *and* Phase B have zero
  failures; a single flaky fixture (e.g. a transient 200-with-`errors`) yields
  `partial`, and per D4 the projection will NOT refresh — so S6 would go stale.
  If a run comes back `partial` from transient noise, narrow the `--leagues`
  subset / re-run to obtain a clean `succeeded` run for S6. A **deterministic**
  `partial` (the same item fails every time) is a STOP-and-escalate finding, not
  something to paper over.
- S4's kill must be ungraceful (SIGKILL, not Ctrl-C twice politely) — the point
  is checkpoint recovery, not graceful shutdown. Capture the killed run's
  `run_id` (from `ingestion_runs` / the `run.start` log) before killing — you
  need it for `--resume`.
- S5: override the key via the environment for that single invocation; never
  edit `.env` in a way that could get committed. Do NOT chase a live
  `dead_letter` row — the invalid key aborts at the un-isolated `/leagues`
  bootstrap before the DLQ path runs (that asymmetry is a known, arguably-correct
  observation — no work list ⇒ nothing to isolate — record it, don't fix it).
  Prove S5a (fail-safe) and S5b (recovery) instead.
- If any step fails, STOP at that step, capture the evidence, and escalate —
  a failed smoke that surfaces a real bug is a *successful* smoke.
