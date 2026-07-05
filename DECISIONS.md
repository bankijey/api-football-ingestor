# Decisions

Locked design decisions for the API-Football Bronze Ingestor. **Do not
relitigate in a task.** If a decision genuinely needs to change, open a
coordinator task titled `NNNN-decision-change-<slug>.md` proposing the change
and its migration cost. Otherwise treat this file as authoritative.

Bronze-layer design is already documented in `CLAUDE.md` (hard rules) and
`docs/ROADMAP.md` (what's built). The decisions below are the ones added when
governance was adopted and API-Football was wired into the matcher. Each entry:
the decision, then a one-line rationale.

---

## D1 — Three-agent spec-driven workflow (adopted 2026-07-05)
Replaces the prior solo "small reviewable steps" style. Coordinator writes the
task spec under `specs/coordinator/tasks/`; implementor implements; verifier
checks against the DoD and writes a report under `specs/verifier/reports/`. One
task per cycle; implementor cannot self-grade; verifier cannot implement; a
failed task becomes a coordinator follow-up. Rationale: platform-wide
consistency with `arbibet-markets` and `arbibet-matcher`, and the cross-DB
projection write (D5) benefits from independent verification.

## D2 — Scope amendment: one serving projection allowed
Bronze-only is amended for exactly ONE table: `apifootball_events`, a materialized
projection over `bronze_fixtures`. It performs field-extraction only (no parsing,
no reshaping of payloads) and exists solely to serve the matcher as an event
source. This is not the Silver layer and does not open Silver scope. Rationale:
the matcher needs an `all_events`-shaped feed; a thin projection is the minimal
way to provide it without standing up Silver.

## D3 — Projection source and shape
`apifootball_events` is derived from `bronze_fixtures` (the Phase-A league-grain
catalogue), taking the latest ingest per `(league_id, season)`, filtered to
`status = NS` and `start > NOW()`, for **all leagues** API-Football covers,
football only. Rationale: all-leagues (not just HF-selected) because the
projection also serves later market-data analysis; NS + future because the
matcher consumes unstarted events.

## D4 — Physical snapshot table, atomically replaced after ANY successful run
`apifootball_events` is a physical **table** in the sources DB, rebuilt as the
final step of an ingestor run, gated on `ingestion_runs.status = 'succeeded'` —
on **any** successful run, not only the 2am schedule. The ingestor computes the
projection rows from its local `bronze_fixtures` and replaces the sources-DB
table in a **single transaction** (build into a staging table, then swap; or
`TRUNCATE`+`INSERT` within one `BEGIN…COMMIT`) so the matcher only ever sees a
complete prior snapshot or a complete new one. A non-successful run leaves the
prior snapshot untouched.

**Corrects an earlier draft** that said "materialized view /
`REFRESH MATERIALIZED VIEW CONCURRENTLY`." A Postgres materialized view cannot
reference a table in another database, and per D5 the source (`bronze_fixtures`)
and target (`apifootball_events`) are in different DBs — so a matview is
impossible without FDW, which we rejected. "Materialized" therefore means an
ingestor-maintained snapshot table; atomicity is the wrapping transaction, not
`REFRESH`. Rationale: same all-or-nothing freshness the matcher needs, local to
the sources DB, with no FDW dependency.

## D5 — Option B: projection is written into the matcher's DB
The ingestor writes `apifootball_events` into the matcher's `POSTGRES_URL`
database (the same pattern the scraper uses for `all_events`); the matcher reads
it locally. The ingestor gains write credentials to the sources DB. The
matcher-facing atomicity (D4) is a sources-DB-local transaction. Mirrored in
`arbibet-matcher/DECISIONS.md` D12. Rationale: the matcher is single-DB (its
D2); data reaches it by being written in, not JOINed across DBs.

## D6 — Column contract (matcher `EVENT_COLUMNS`)
Projection rows conform to the matcher's source contract:
`e_id = "apifootball;<fixture_id>"` (**semicolon** delimiter),
`bookmaker_id = "apifootball"`, `sport_key = "football"`,
`start` = kickoff (`TIMESTAMPTZ`, Berlin render), `tid` = league_id,
`tournament` = league name, `home_team`/`away_team`, `home_id`/`away_id` =
API-Football team ids, `url` = NULL. Rationale: the matcher's `ApiFootballSource`
reads these directly; a colon delimiter would break `bookmaker_id` derivation
downstream.
