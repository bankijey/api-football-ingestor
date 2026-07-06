# 0007 escalation — autonomous scheduled run cannot reach `succeeded`; projection never refreshes

**Action:** escalated. **To:** coordinator.

---

## UPDATE (amended attempt, 2026-07-06 ~19:30 UTC) — isolated fire `failed` on DAILY-QUOTA exhaustion

The coordinator amendment re-scoped D3 to a **single isolated fire** after ≥2 h
quiescence, on the hypothesis that the first attempt's partials were self-induced
per-minute 429s. That isolated fire was executed exactly as amended — crond-fired
run `851d7576` at 19:27 UTC, after a clean quiescence window (last prior fire
17:21 UTC; quiescence reached 19:25:51 UTC) — and it **`failed`**, but on a
**different, more fundamental** cause: the **account's daily API request quota is
exhausted** ("You have reached the request limit for the day"). The error hit the
**`/leagues` bootstrap**, so the run aborted in 39 s before building any work list
(`status='failed'`, zero `dead_letter`, no projection step reached).

**This changes the root cause.** The amendment's isolation hypothesis addressed
*per-minute* 429 contention; the real blocker now is *daily* quota depletion,
which **time-isolation cannot fix** (a daily quota resets once/day, not after 2 h
of quiet). So **no run can `succeed` on this key until the quota resets** — the
proof is impossible today. Context: 5 full-catalogue runs fired on this key today
(2 succeeded incl. the 00:00-UTC stale-image cron, 2 partial, this failed) plus
heavy Phase-B fetching; the budget was largely consumed by this task's own
repeated testing (and possibly other consumers sharing the key). Exact
remaining-quota is unlogged (roadmap **0009**), so the cap/reset time is
unconfirmed.

**Per the bounded protocol I did NOT re-trigger.** Crontab disarmed/restored to
`0 2 * * *` at 19:30:55 UTC; the real production cron remains armed for tonight
**00:00 UTC (02:00 CEST)** — now on the rebuilt projection-carrying image.

### Revised options

1. **Verify the already-scheduled real 2 am / 00:00-UTC cron (recommended).** It
   is the amendment's *preferred* isolated vehicle, is already scheduled, now runs
   the correct image (`d764187325a2`), and fires against tonight's quota reset. If
   the daily quota resets by 00:00 UTC and no other consumer drains it first, that
   run should `succeed` and `projection.built` → D3/D4 proven with **zero further
   API spend today**. A verifier/fresh session checks `ingestion_runs` +
   `apifootball_events` + the scheduler `ingest.log` tomorrow morning. Risk:
   00:00 UTC sits on a common reset boundary — if the reset lags or the key is
   shared, it too may fail; then options 2/3 apply.
2. **Quota budgeting / dedicated key (→ 0008, possibly 0009 first).** If the real
   daily cap is materially below the assumed 75 k, or the key is shared with the
   scraper/matcher, a daily full run (~2 k calls) plus other load can exhaust it —
   0008 (daily scheduling) must size against the *real* cap and isolate the key,
   and 0009 (log `x-ratelimit-*-remaining`) should land first to measure it.
3. **Do NOT relax the `succeeded` gate for this (0010 partial-tolerance is a red
   herring here).** A quota-exhausted run `fails` at bootstrap with an *empty*
   catalogue — there is nothing to project. Partial-tolerance addresses a few
   failed leagues in an otherwise-complete run; it would not (and should not)
   salvage a bootstrap-failed run. So 0010 is not the fix for this finding.

**Recommendation:** option 1 — let the real 00:00-UTC cron be the proof and verify
it tomorrow; queue option 2 (0009 quota measurement → 0008 quota-aware schedule +
key isolation) as the durable fix. The systemic-drift hand-off to **0008** stands
regardless.

---

## Original escalation (first attempt — two per-minute-429 partials) — retained as history

## Summary

D1 and D2 completed cleanly: `:latest` was rebuilt from current source
(`d764187325a2`, import-check `ingestor.projection` exit 0) and the live
scheduler (`ingestor-scheduler` compose cron) was identified. But **D3/D4 — the
"deployed AND verified" gate — cannot be met.** Two consecutive **autonomous,
crond-fired** full-catalogue runs of the rebuilt image both returned
**`partial`** (Phase-A `failed` = 3, then 9), every failure a transient **HTTP
429** rate-limit on `fixtures_by_league`. Because the projection is gated on
`ingestion_runs.status = 'succeeded'` (D4), it never rebuilt — `apifootball_events`
stayed at the prior 0005 snapshot (42,399 rows, unchanged). Per the D3 protocol
(re-trigger once; if still `partial`, i.e. **systematically** `partial`, STOP and
escalate — the partial-tolerance policy is a later task), I stopped rather than
keep re-triggering, since deciding to refresh on `partial` is out of scope here.

The D4 gate itself is proven **correct** (a non-`succeeded` run leaves the
snapshot untouched — all-or-nothing). What is unproven is a `succeeded`
autonomous run, because the scheduled full run is systematically 429-partial in
this window.

## Evidence (all commands + output in `docs/DEPLOY_0007_EVIDENCE.md`)

- **Rebuilt image (D1):** `api-football-ingestor:latest` =
  `sha256:d764187325a2…`, Created `2026-07-06T17:04:51Z`; `docker run … python -c
  "import ingestor.projection"` → `projection present`, exit 0.
- **Scheduler (D2):** `ingestor-scheduler` (`docker:27-cli`), crontab `0 2 * * *`,
  cron cmd `docker compose run --rm ingestor ingest` — **no build step**. Its
  `/var/log/ingest.log` shows 20 prior `succeeded` runs with **0**
  `projection.built` lines (F2: production ran stale pre-0001 images).
- **Run 1 (cron 19:08 CEST):** run_id `c7f82ae2-99b8-4a67-b2cd-bec1cce34154`,
  `status=partial`, phase_a failed=3 (leagues 503/813/1049, all 429).
- **Run 2 (cron 19:21 CEST, the one re-trigger):** run_id
  `4befe5d5-0bac-476b-a6e1-81183ee24280`, `status=partial`, phase_a failed=9, all
  `RetryableHttpError / 429` on `fixtures_by_league`.
- **Projection:** 0 `projection.built` in either run; `apifootball_events` still
  42,399 rows (== 0005 snapshot). Gate correct; DoD gate unmet.
- **D5:** crontab restored to `0 2 * * *`; scheduler left `Up`. Test crons removed.

## Why this is a real block, and a caveat worth weighing

The 429s are transient, but they recurred and **worsened** on the immediate
re-trigger (3 → 9), so a naive "just re-run" does not reliably yield `succeeded`.

**Caveat (please weigh):** my test fired two full-catalogue runs ~13 min apart,
on top of 0005's manual full run at 16:03 — three ~2,000-call runs inside ~90
min. The real production cadence is **one** run/day at 02:00 in isolation. It is
plausible the 429s are partly self-inflicted by rapid back-to-back triggering and
that a genuinely isolated 2am run would succeed (0005, run in isolation, had 0
failures). I could not prove that either way without leaving the test window;
proving it would mean waiting for a real isolated 2am fire, which the task did not
scope.

## Options

1. **Re-scope 0007 to an isolated single autonomous fire (recommended).** Arm the
   cron once, in isolation (no other full runs for ≥1–2 h beforehand — ideally
   let the real 02:00 fire, or a single near-future fire after a quiet window),
   and take the `succeeded` + `projection.built` + refreshed-count evidence from
   that one clean run. Cheapest path to the DoD if the 429s are indeed
   test-induced. Risk: if it still comes back `partial`, it confirms option 2/3.
2. **Prioritise the partial-tolerance / success-with-warnings policy before
   0007's proof.** If a scheduled full run over ~1,231 leagues realistically
   incurs a few transient 429s, gating the projection on strict `succeeded` means
   the daily projection starves on any flaky day. A policy that refreshes the
   projection on `partial` under a failure-rate threshold (e.g. <1 % leagues
   failed) would unblock this. This is the deferred partial-tolerance task —
   0007 explicitly says escalate to it. Bigger scope; touches D4 semantics
   (coordinator/human call, likely a DECISIONS entry).
3. **Soften the rate limiter / retry budget** so full runs don't exhaust retries
   on 429 (e.g. more attempts, longer backoff, lower `RATE_LIMIT_PER_MIN`). A
   real code change (out of 0007's zero-code scope) — a separate task, and it
   competes with option 1's simpler hypothesis that the load was test-induced.

**Recommendation:** option 1 — retry the proof as a **single isolated** autonomous
fire (the daily cadence 0007 actually targets), since the most likely cause is my
back-to-back triggering, not a production defect. Keep option 2 queued as the
durable fix if isolation doesn't clear it. Either way, the systemic drift hand-off
to **0008** (scheduled path never rebuilds `:latest`) stands regardless.

## Current state

- **Committed:** this note + the `LOG.md` `escalated` line only.
- **Staged, uncommitted (escalation carve-out):** `docs/DEPLOY_0007_EVIDENCE.md`
  — the full evidence log (D1/D2 met, D3/D4 blocked, D5 restored, 0008 hand-off).
  Salvage or discard per the coordinator's decision.
- **Live deployment:** crontab back to `0 2 * * *`; `ingestor-scheduler` running;
  `:latest` is the rebuilt projection-carrying image; `apifootball_events`
  untouched at the 0005 snapshot. No repo code/compose changed.
