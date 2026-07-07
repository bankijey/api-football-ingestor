# 0004 — Projection hardening: streaming read (F3) + DSN dialect normalization (F1)

**Roadmap item:** §1.11 — Projection hardening before the full-catalogue run
**Depends on:** 0003 (live smoke, PASS `8e69672`).
**Gates:** 0005 (full-catalogue daily run) — do not run the unbounded catalogue
until this lands.
**Status:** open

## Goal

The 0003 live smoke passed but its verifier surfaced two projection-path risks
that the full-catalogue run (0005) would hit hardest. This task hardens the
`apifootball_events` projection (D2–D6) **without changing its output**, so the
expensive unbounded run is safe:

- **F3 (memory):** `projection._read_rows` does `cur.fetchall()` on
  `_LATEST_FIXTURES_SQL`, materializing **all** ~7,894 latest bronze
  league-season JSONB payloads into Python at once (~6 GiB / ~12 min cold,
  approaching the container ceiling — and it grows with bronze). The catalogue
  run enlarges bronze, so the post-run projection (D4: runs on **any** success)
  is the likeliest OOM.
- **F1 (DSN footgun):** `matcher_db_dsn` is handed straight to psycopg2. D5's
  source URL is the matcher's `POSTGRES_URL`, which natively carries the
  SQLAlchemy dialect suffix (`postgresql+psycopg2://…`) that raw psycopg2
  rejects. An operator copying it verbatim silently flips every run's projection
  step to failure with no snapshot refresh.

This is robustness only. The projected **row set and column contract are
unchanged** (D2 field-extraction only; D3 NS+future/all-leagues; D4 atomic
single-transaction replace; D6 `EVENT_COLUMNS`) — every existing
`test_projection.py` assertion must still pass byte-for-byte.

## In scope

### F3 — stream the bronze read (design decision: server-side cursor)
In `src/ingestor/projection.py`, replace the `fetchall()` in `_read_rows`
(projection.py:92-95) with a psycopg2 **named (server-side) cursor** that
streams payloads in bounded batches, keeping the existing `_to_row` extraction
unchanged. Shape:

```python
_ITERSIZE = 200  # payloads resident per fetch batch — a module constant

def _read_rows(bronze_pool: ConnectionPool, now_ts: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with bronze_pool.connection() as conn:
        with conn.cursor(name="apifootball_proj_read") as cur:
            cur.itersize = _ITERSIZE
            cur.execute(_LATEST_FIXTURES_SQL)
            for (payload,) in cur:                    # streamed, not fetchall
                for fixture in (payload or {}).get("response") or []:
                    row = _to_row(fixture, now_ts)
                    if row is not None:
                        rows.append(row)
    return rows
```

Peak resident input drops from "every payload" to one `itersize` batch. The
named cursor lives inside the pool's transaction (connection.py:38-49) and is
fully consumed before `commit()`, so it is safe. `_to_row`, `_LATEST_FIXTURES_SQL`,
`_INSERT_SQL`, `_write_atomic`, and `build_projection` are unchanged.

- The output `rows` list is NOT the memory problem (only NS+future fixtures
  survive `_to_row`, a small subset) — do NOT batch/stream the write side.

### F1 — normalize the matcher DSN dialect
In `src/ingestor/config.py`, add a `@field_validator("matcher_db_dsn", mode="before")`
that strips a `+<driver>` suffix from the URL scheme so a SQLAlchemy-style DSN
works with raw psycopg2:

- `postgresql+psycopg2://u:p@h:5432/db` → `postgresql://u:p@h:5432/db`
- `postgres+psycopg2://…`               → `postgres://…` (base scheme kept as-is)
- `postgresql://…` / `postgres://…`     → unchanged (idempotent)
- `""` (unconfigured)                   → `""` (projection stays skipped — D5)

Only the scheme token before `://` is touched (split once on `+`); everything
after `://` is byte-identical. Scope to `matcher_db_dsn` **only** — `db_dsn` is
ours and is out of scope.

### Docs
Update `.env.example:32` `MATCHER_DB_DSN=` with a one-line comment noting the
`postgresql://` form is expected and a `+psycopg2` dialect suffix is accepted
(auto-normalized).

## Out of scope
- **Running the full catalogue** — that is 0005, gated on this task.
- **Any change to the projected row set / columns / atomicity** (D2/D3/D4/D6).
  Output must be identical; this is robustness, not a behavior change.
- **SQL-side jsonb extraction / a rewrite of `_to_row`** — considered and
  deferred; the server-side cursor solves F3 at far lower risk. Do not rewrite
  the extraction into SQL.
- **Normalizing `db_dsn`** or touching the connection pool / bronze write path.
- **V1** (flaky `test_heartbeat_ticks_at_interval`) — separate follow-up (0006).
- **F2** (rebuild/redeploy the stale scheduler image) — separate ops follow-up
  (0007); not a code change in this repo.

## Files
Modified:
- `src/ingestor/projection.py` — server-side cursor streaming in `_read_rows`
- `src/ingestor/config.py` — `matcher_db_dsn` scheme-normalizing validator
- `tests/test_projection.py` — add the streaming test (below)
- `tests/test_config.py` — add the DSN-normalization test (below)
- `.env.example` — comment on the accepted `MATCHER_DB_DSN` form
- `docs/ROADMAP.md` — coordinator flips `0004 [~]→[x]` + Progress-log ON CLOSE
- `LOG.md` — implementor appends one line on commit

No other files. If one must change, STOP and flag at
`specs/implementor/notes/0004-projection-hardening.md`.

## Acceptance criteria (Definition of Done)
1. `make lint` (ruff + mypy) exits 0.
2. `make test` exits 0; **all pre-existing `tests/test_projection.py` tests still
   pass unchanged** (proves the projected row set is byte-identical after F3).
3. F3 static check: `src/ingestor/projection.py` no longer calls `.fetchall()`
   in the bronze read path, and `_read_rows` obtains its cursor via
   `conn.cursor(name=…)` (a server-side cursor).
4. F3 behavior: a new test
   `tests/test_projection.py::test_read_streams_with_server_side_cursor` seeds
   ≥2 latest league-season payloads (one NS+future fixture that projects, one
   non-qualifying, e.g. FT/past), asserts the produced rows equal the expected
   single projected row, AND asserts the bronze read used a **named** cursor
   (spy that `conn.cursor` was called with a non-empty `name`).
5. F1: a new test `tests/test_config.py::test_matcher_dsn_dialect_normalized`
   asserts `Settings(matcher_db_dsn="postgresql+psycopg2://u:p@h:5432/db").matcher_db_dsn
   == "postgresql://u:p@h:5432/db"`; that a bare `postgresql://…` DSN is
   unchanged (idempotent); and that `""` stays `""`.
6. `git diff` for this task touches ONLY the seven files in §Files.
7. No new dependencies (`pyproject.toml` unchanged).
8. No `DECISIONS.md` violated: D2 (still field-extraction, no reshape),
   D3/D6 (row set + `EVENT_COLUMNS` unchanged — AC2), D4 (`_write_atomic`
   untouched), D5 (projection still writes only the sources DB).

## Notes for the implementor
- The whole point is **output-preserving**: if any existing `test_projection.py`
  assertion changes, you have gone too far — the row set must be identical.
- psycopg2 named cursors are auto server-side (WITHOUT HOLD); they must be
  created and fully consumed inside one transaction — the `with
  bronze_pool.connection()` block already provides exactly that.
- For AC4's spy, wrap/replace the pooled connection's `.cursor` to record the
  `name` kwarg, or assert on a captured call — your choice, but the assertion
  must fail if a client-side (unnamed) cursor is used.
- F1 is a pure string normalization at settings-load time; do not touch how the
  DSN is later used to build the pool.

## Verifier checklist (mirror of DoD, plus housekeeping)
- [ ] AC1–AC8 confirmed (run the suite; grep projection.py for `fetchall`/
      `cursor(name=`; run the two new tests by name)
- [ ] No files outside §Files modified
- [ ] No new dependencies added
- [ ] No `DECISIONS.md` entries violated (esp. output-set unchanged — D2/D3/D6)
- [ ] `docs/ROADMAP.md` checkbox not flipped by implementor (coordinator owns it)
- [ ] Working tree clean on handoff; `LOG.md` line appended
