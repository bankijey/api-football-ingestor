"""Turn Phase-A fixture payloads into the Phase-B work list (fixture_ids).

Filters applied (all must pass):
  * fixture.status.short ∈ configured statuses (e.g. FT/AET/PEN, plus optional live)
  * fixture.timestamp inside the requested time window:
        - if `from_ts` / `to_ts` are given, use that exact range (inclusive);
        - otherwise fall back to `[now - lookback_days, now]`.
  * league has at least one of the configured coverage flags
    (default: lineups / statistics_fixtures / statistics_players / events)

The coverage check is the gate that keeps us from spending API calls on
fixtures the rich endpoint won't actually enrich.
"""
from __future__ import annotations

import time
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Any

DEFAULT_RICH_FLAGS: tuple[str, ...] = (
    "lineups",
    "statistics_fixtures",
    "statistics_players",
    "events",
)


@dataclass(frozen=True)
class FixtureRecord:
    fixture_id: int
    league_id: int
    season: int
    status: str
    timestamp: int  # epoch seconds


def extract_fixture_records(fixtures_payload: dict[str, Any]) -> list[FixtureRecord]:
    """Flatten a /fixtures?league=… response into typed records.

    Skips entries missing any required field rather than raising — the API
    occasionally returns sparse objects for in-flux fixtures.
    """
    out: list[FixtureRecord] = []
    for item in fixtures_payload.get("response", []) or []:
        fixture = item.get("fixture") or {}
        league = item.get("league") or {}
        fid = fixture.get("id")
        lid = league.get("id")
        season = league.get("season")
        status = (fixture.get("status") or {}).get("short")
        ts = fixture.get("timestamp")
        if fid is None or lid is None or season is None or status is None or ts is None:
            continue
        out.append(FixtureRecord(
            fixture_id=int(fid),
            league_id=int(lid),
            season=int(season),
            status=str(status),
            timestamp=int(ts),
        ))
    return out


def select_fixture_ids(
    records: Iterable[FixtureRecord],
    coverage_by_league: dict[int, dict[str, Any]],
    *,
    statuses: Collection[str],
    lookback_days: int,
    now_ts: int | None = None,
    required_any_flags: Collection[str] = DEFAULT_RICH_FLAGS,
    from_ts: int | None = None,
    to_ts: int | None = None,
) -> list[int]:
    """Return distinct fixture_ids in input order, after applying all filters.

    Time window:
      * If `from_ts` and/or `to_ts` are passed, they take precedence over
        `lookback_days`. Either may be None for an open-ended bound.
      * Otherwise the legacy `[now - lookback_days, now]` window is used.
    """
    now = now_ts if now_ts is not None else int(time.time())
    use_range = from_ts is not None or to_ts is not None
    if use_range:
        lo = from_ts if from_ts is not None else 0
        hi = to_ts if to_ts is not None else (1 << 62)
    else:
        lo = now - lookback_days * 86_400
        hi = 1 << 62  # effectively +inf — legacy behaviour
    statuses_set = {s.upper() for s in statuses}
    flags = tuple(required_any_flags)

    seen: set[int] = set()
    out: list[int] = []
    for r in records:
        if r.status.upper() not in statuses_set:
            continue
        if r.timestamp < lo or r.timestamp > hi:
            continue
        cov = coverage_by_league.get(r.league_id) or {}
        fixtures_cov = cov.get("fixtures") or {}
        if not any(fixtures_cov.get(f) for f in flags):
            continue
        if r.fixture_id in seen:
            continue
        seen.add(r.fixture_id)
        out.append(r.fixture_id)
    return out
