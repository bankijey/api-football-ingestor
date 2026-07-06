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

### S5 — DLQ + retryability (exit criterion)
- Deterministic failure: one tiny run with an **invalid API key** (env
  override for that invocation only) so fetches fail terminally.
- Evidence: `dead_letter` rows with error class + endpoint populated. Then
  re-run with the valid key: the same items succeed (retryable proven).
  Restore env afterwards; note both invocations in the evidence file.

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
5. S5: invalid-key run produces `dead_letter` rows; valid-key re-run succeeds
   on the same items (retryable).
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
- S4's kill must be ungraceful (SIGKILL, not Ctrl-C twice politely) — the point
  is checkpoint recovery, not graceful shutdown.
- S5: override the key via the environment for that single invocation; never
  edit `.env` in a way that could get committed.
- If any step fails, STOP at that step, capture the evidence, and escalate —
  a failed smoke that surfaces a real bug is a *successful* smoke.
