# 0005 — Full-catalogue live run: quota/duration sizing + scale characterization

**Roadmap item:** §1.11 — Full-catalogue daily run
**Depends on:** 0003 (bounded smoke, PASS `8e69672`), 0004 (projection
hardening, PASS `11493f4`).
**Status:** open

## Goal

0003 proved every mechanism live at ~1% of quota; 0004 removed the projection's
~6 GiB memory ceiling. This task runs the ingestor **unbounded — all
current-season leagues** — once, to produce the two things only a full run can
give: **(a) real quota + wall-clock numbers to size the daily schedule**, and
**(b) the true full-scale failure rate**. Like 0003 it is *operational*:
DB/ledger evidence, ideally **zero production code**. Any needed code change is a
finding that STOPs and escalates.

**This task does NOT re-prove hash-dedup, `--resume`, or DLQ-retryability** —
those are proven at bounded scale (0003, S3/S4/S5). It proves **scale**:
completion, cost, duration, and what fails when 1,500 leagues run at once.

### The terminal-status / projection tension (characterize, do NOT fix here)
Terminal status is binary: `_terminal_status` returns `succeeded` only when
Phase A **and** Phase B have zero failures ([runner.py:194](src/ingestor/orchestrator/runner.py:194)),
and the projection refresh is gated on `succeeded`
([runner.py:114](src/ingestor/orchestrator/runner.py:114), D4). Across ~1,500
leagues a zero-failure run is unlikely, so the full run will probably come back
`partial` — meaning the projection legitimately does **not** refresh and the
prior snapshot stands (D4). **That is expected data for this task, not a
failure.** Whether a daily job needs a "success-with-warnings" tolerance (roadmap
§1.6 names one; the code is binary) is a **follow-up policy decision** that needs
*this run's failure numbers* as input — which is exactly why the observational
run comes first. 0005 records and escalates; it does not change D4 or the
status logic.

## Procedure (in scope)
Run against the real API key (env only) and the live stack, in a **Python 3.12**
runtime (0004's verifier flagged `.venv` is 3.10; the production-representative
run must match the target). Record every command + queried result in
`docs/FULLRUN_0005_EVIDENCE.md` as you go (command, timestamp Berlin, output
snippet). Confirm `MATCHER_DB_DSN` is set (now dialect-tolerant per 0004) and
note the configured `daily_quota` + rate-limit before starting.

### S1 — The full run
- `make ingest` (or the CLI) with **no `--leagues` filter** (all current-season
  leagues) and default `lookback_days`. One run.
- Evidence: `ingestion_runs` row — `run_id`, `status`, non-null `finished_at`,
  full `counters` (`leagues_total`, `fixtures_total`, `phase_a`/`phase_b`
  {ok/skipped/unchanged/failed}); wall-clock start→finish duration; the
  `run.done` log line.

### S2 — Quota accounting (sizes the schedule)
- Evidence: total observed API calls (Phase A ≈ `1 + leagues_total`; Phase B ≈
  `2 × recent-fixtures` — derive from counters/logs), the lowest observed
  `x-ratelimit-*-remaining` (per-minute and daily) and thus headroom, and
  elapsed vs the rate-limit window. Compute a **calls-per-day estimate** and
  state the margin under `daily_quota`.

### S3 — Projection at full scale (the 0004 payoff)
- Record whether the projection step ran (it runs iff S1 = `succeeded`; see S4).
- If it ran: confirm it completed **without OOM** and record its duration and,
  if observable (`docker stats`), peak memory — contrast with the pre-0004
  ~6 GiB / ~12 min. Re-query the sources DB and re-affirm the D3/D6 contract at
  full scale: `count(*) > 0`, every `e_id` matches `^apifootball;[0-9]+$`,
  `min(start) > now()`, constants (`bookmaker_id='apifootball'`,
  `sport_key='football'`, `url IS NULL`).
- If it did **not** run (S1 = `partial`): record that `apifootball_events` still
  holds the prior snapshot (D4), untouched. Not a failure of this task.

### S4 — Terminal status + failure characterization (the headline)
- Record the terminal status (`succeeded` vs `partial`).
- Break down this run's `dead_letter` rows **by `endpoint` and `error_class`**;
  list the top failure modes and rough counts. This is the input a future
  partial-tolerance policy needs.
- If `partial`: document the projection-gating consequence (no refresh this run)
  and escalate it as a **follow-up** (attach the numbers) — do not fix it here.

### S5 — Daily-schedule sizing recommendation
- From S1 (duration) + S2 (quota) write a short recommendation in the evidence
  file: is one full run/day feasible under quota and time? what margin? is the
  rate-limit/concurrency config adequate, or does it need tuning? This is the
  input to the deferred scheduling/cron task — a recommendation, not a cron.

### S6 — Hermetic gates still green (control)
- `make lint` + `make test` exit 0 on the unchanged commit (Python 3.12). No
  code should have changed; this is a control, not a deliverable.

## Out of scope
- **Implementing scheduling/cron** — 0005 only *sizes* it; the daily job is a
  later task.
- **Any production code change.** A bug found here = STOP, escalate with the
  evidence; the fix becomes a scoped follow-up task.
- **Changing D4 or the terminal-status logic.** A `partial`-tolerance /
  success-with-warnings policy is a separate decision-change follow-up *if this
  run's data warrants it* — see S4.
- **Re-proving hash-dedup / `--resume` / DLQ-retryability at scale** — proven in
  0003 (S3/S4/S5). Do not spend a second full quota re-running for these.
- **The matcher's live smoke** (`arbibet-matcher`) — its own repo.
- **V1** (flaky heartbeat test, 0006) / **F2** (stale scheduler image, 0007).

## Files
Created:
- `docs/FULLRUN_0005_EVIDENCE.md` — the evidence log (commands, outputs, counts)

Modified:
- `docs/ROADMAP.md` — coordinator flips `0005 [~]→[x]` + Progress-log ON CLOSE
- `LOG.md` — implementor appends one line on commit

NO production/source files. If one must change, STOP and escalate at
`specs/implementor/notes/0005-full-catalogue-run.md`.

## Acceptance criteria (Definition of Done)
1. S1: `ingestion_runs` shows one full-catalogue run with non-null `finished_at`
   and populated counters; `leagues_total` reflects the full current-season
   catalogue (record the number, ~1,000–1,500, not a handful); evidence records
   `run_id`, wall-clock duration, and terminal status.
2. S2: total observed API-call count recorded with the lowest `x-ratelimit`
   remaining (per-minute + daily); a calls-per-day estimate is computed and
   stated against `daily_quota` with its margin.
3. S3: if S1 = `succeeded`, `apifootball_events` refreshed — row count recorded,
   all `e_id` match `^apifootball;[0-9]+$`, all `start` future, constants
   correct — and the projection completed with **no OOM** (duration recorded;
   memory bounded, per 0004). If S1 = `partial`, the evidence records that the
   projection did not refresh and the prior snapshot stands (D4). Either branch
   is a PASS when correctly evidenced.
4. S4: terminal status recorded, with a `dead_letter` breakdown by `endpoint` +
   `error_class` for this run; if `partial`, the projection-gating consequence is
   documented and raised as a follow-up.
5. S5: a written daily-schedule sizing recommendation (quota margin, duration,
   feasibility, any config-tuning need) is in the evidence file.
6. S6: `make lint` + `make test` exit 0 on the unchanged commit (Python 3.12).
7. `git diff` for this task touches ONLY `docs/FULLRUN_0005_EVIDENCE.md`,
   `docs/ROADMAP.md` (coordinator), `LOG.md`.
8. No secrets in any committed file (API key / DB passwords appear nowhere; DSNs
   password-redacted).

## Verifier checklist (mirror of DoD + housekeeping)
- [ ] AC1–AC6 — corroborate by independently re-querying `ingestion_runs`,
      `dead_letter`, and (sources DB) `apifootball_events` against the live DBs;
      re-run `make lint`/`make test` on the commit (Python 3.12). Do not take the
      evidence file's word.
- [ ] AC7 — diff confined to evidence/roadmap/log files
- [ ] AC8 — no secrets committed
- [ ] No `DECISIONS.md` violated: D4 observed live (projection refreshed **iff**
      the run was `succeeded`; prior snapshot intact on `partial`); bronze
      append-only, untouched by the procedure.
- [ ] Working tree clean on handoff; `LOG.md` line appended

## Notes for the implementor
- **You are an operator this cycle, not a coder.** The deliverable is evidence —
  copy actual command output into the file; summaries don't count.
- **Run in Python 3.12** (the target), not the 3.10 `.venv` — this run stands in
  for production.
- **Expect `partial`.** A full-catalogue run almost certainly has some
  league/fixture failures; `partial` is DATA, not a task failure. Do NOT STOP for
  it — record the `dead_letter` breakdown and continue. STOP + escalate only for
  a genuine defect: a crash, bronze corruption, a projection OOM, or quota
  blow-through.
- The projection refreshes only on `succeeded` ([runner.py:114](src/ingestor/orchestrator/runner.py:114),
  D4). On a `partial` run it correctly does not — that is the expected S3/S4
  branch, not a bug to fix.
- **Quota safety:** one full run at default lookback should be a few thousand
  calls (Phase A ≈ `1 + leagues`; Phase B ≈ `2 × recent fixtures`) — well under
  the default 100k `daily_quota`, but confirm headroom BEFORE and watch
  `x-ratelimit` DURING. If it trends toward the daily cap, STOP and escalate.
- **One run only.** Do not re-run to re-demonstrate dedup/resume — proven in
  0003. The single full run + the S6 hermetic control is the whole deliverable.
