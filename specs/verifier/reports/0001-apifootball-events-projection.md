# Verifier report — 0001-apifootball-events-projection

**Result:** PASS
**Verified at:** 2026-07-05 19:43 (Berlin)
**Commit:** 602dcf3c3ea3e9732977e7edf86819b964f988ff

Verification env: fresh Python 3.12.10 venv (local `.venv` is 3.10 — per spec a
local-env issue, not a code failure). DB-backed criteria (AC3/AC5/AC7) were run
against the **live `ingestor-postgres` container** (port 5434) via
`TEST_DB_DSN`, so the projection tests actually executed rather than skipping —
full suite ran with **zero skips**.

## Acceptance criteria

1. [PASS] `make lint` and `make test` exit 0; new tests collected.
   evidence: `ruff check .` → "All checks passed!" (0); `mypy src` → "no issues
   found in 31 source files" (0); `pytest -q` → "85 passed, 1 xfailed" (0), all
   5 `test_projection.py` tests among them.

2. [PASS] `matcher_db_dsn` (env `MATCHER_DB_DSN`) in `Settings` + `.env.example`;
   no DSN literal in source.
   evidence: config.py:70-73 `matcher_db_dsn: str = Field(default="", …)`;
   .env.example:33 `MATCHER_DB_DSN=`; grep for a matcher/sources DSN literal in
   source → none.

3. [PASS] Mixed seed (NS+future, NS+past, FT) → exactly one row, full D6 columns.
   evidence: `test_projection_keeps_only_ns_future_with_full_columns` PASSED
   (live DB) — asserts `n==1`, `e_id=="apifootball;101"`,
   `bookmaker_id=="apifootball"`, `sport_key=="football"`, `url IS NULL`,
   `tid=="39"`, `tournament=="PL"`, team names/ids, `start` TIMESTAMPTZ.
   Filter logic at projection.py:114 (`status != "NS" or ts is None or ts <= now_ts`).

4. [PASS] `e_id` uses `;` not `:`.
   evidence: projection.py:124 `f"apifootball;{fid}"`; test asserts
   `";" in e_id and ":" not in e_id`.

5. [PASS] Atomicity: mid-write failure leaves prior snapshot intact.
   evidence: `test_atomic_replace_keeps_prior_snapshot_on_mid_write_failure`
   PASSED (live DB) — monkeypatches `execute_batch` to raise after TRUNCATE;
   after the RuntimeError the table still holds the prior row `[301]`, not empty
   / partial. DDL+TRUNCATE+INSERT share one `with matcher_pool.connection()`
   block; rollback-on-exception (connection.py:45-47) is the guarantee.

6. [PASS] Gating: runs on `succeeded`, not on `partial`/`failed` (DB-free unit).
   evidence: `test_should_project_gate` PASSED — `_should_project("succeeded",
   configured) is True`; `"partial"`/`"failed"` → False; empty DSN → False.
   Hook wired at runner.py:113-114 on the success path only. The empty-DSN
   short-circuit is the coordinator-accepted defensive guard (spec Resolution
   note), not an out-of-spec deviation.

7. [PASS] Latest ingest per `(league_id, season)`.
   evidence: `test_reflects_only_newest_ingest_per_league_season` PASSED (live
   DB) — two ingests for (39,2025) → only newest fixture `[202]`. SQL uses
   `DISTINCT ON (league_id, season) … ORDER BY league_id, season, ingested_at
   DESC` (projection.py:52-56).

8. [PASS] Bronze tables and bronze write path byte-identical.
   evidence: commit touches only .env.example, LOG.md, config.py, runner.py,
   projection.py, tests/test_projection.py — no migrations, no bronze writer.
   projection.py only READS `bronze_fixtures`; the DDL creates
   `apifootball_events` in the sources DB (not in bronze migrations).

9. [PASS] No `DECISIONS.md` violated.
   evidence: D2 field-extraction only (no parse/reshape); D3 all-leagues (no
   league filter in `_LATEST_FIXTURES_SQL`), football-only (`sport_key`
   hardcoded); D4 plain table + one-transaction TRUNCATE+INSERT, grep for
   `materialized view|postgres_fdw|foreign data wrapper` → none; D5 writes to
   `matcher_pool` (sources DB) exclusively within projection.py; D6 column
   contract met. DECISIONS.md not in the commit.

## Housekeeping

- [PASS] Files modified are a subset of §Files
  evidence: the 6 committed files are all in §Files (Created: projection.py,
  test_projection.py; Modified: config.py, .env.example, runner.py, LOG.md).
- [PASS] No new dependencies
  evidence: pyproject.toml not in commit; `execute_batch` is from the existing
  `psycopg2` dependency.
- [PASS] No DECISIONS.md entries violated (see AC9).
- [PASS] docs/ROADMAP.md not modified by implementor
  evidence: ROADMAP.md not in `git show --stat HEAD`; §1.10 still `[~]`.
- [PASS] Working tree clean
  evidence: `git status --porcelain` empty after commit.
- [PASS] `LOG.md` implementor line present; commit is a real SHA
  evidence: LOG.md:23 implementor line for this task; commit 602dcf3 exists.
  (This repo's LOG format does not embed the SHA in the line text; "real SHA"
  read as "a real commit landed," which it did.)

## Findings

PASS — no blocking findings. Observations for the coordinator (do NOT fold into
this closed task):

1. `tid`, `home_id`, `away_id` are stored as **TEXT** (via `_s(...)`), not
   integer — a deliberate choice "mirroring the legacy all_events feed" (commit
   body). D6 names the columns but not their SQL types (only `start` is pinned to
   TIMESTAMPTZ, which is respected), so this is not a D6 violation. Worth a quick
   cross-check with `arbibet-matcher` task 0001 that `ApiFootballSource` reads
   these as text, since the spec asked both sides to stay in lockstep on the
   contract.
2. The projection reads ALL `bronze_fixtures` via `DISTINCT ON` with no
   `sport`/football filter at the SQL level — football-only holds today because
   API-Football is football-only, and `sport_key` is hardcoded. Fine under D3;
   noted only so a future multi-sport source doesn't silently leak in.
