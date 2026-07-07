"""Turn a /leagues payload into a worklist of (league, current_season, coverage).

Why coverage is kept here: Phase B fixture filtering needs to consult per-league
coverage flags (lineups / events / statistics_*). Carrying it on LeagueWork
avoids a second pass over the leagues payload later.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LeagueWork:
    league_id: int
    season: int
    coverage: dict[str, Any]


def select_leagues(
    leagues_payload: dict[str, Any],
    *,
    subset: Iterable[int] | None = None,
    seasons: Iterable[int] | None = None,
) -> list[LeagueWork]:
    """Return one LeagueWork per (league, season).

    Season filter:
      * If `seasons` is given, keep every league-season pair whose year is in
        the set (used for historical backfills like 2019..2022).
      * Otherwise keep only the season the API marks `current=true`
        (default, used by the daily run).

    Skips: malformed entries; leagues not in `subset` when `subset` is set;
    seasons not in `seasons` when that filter is active.
    """
    subset_set: set[int] | None = set(subset) if subset else None
    seasons_set: set[int] | None = set(seasons) if seasons else None
    out: list[LeagueWork] = []
    for item in leagues_payload.get("response", []) or []:
        league = item.get("league") or {}
        lid = league.get("id")
        if lid is None:
            continue
        lid_int = int(lid)
        if subset_set is not None and lid_int not in subset_set:
            continue
        for season in item.get("seasons") or []:
            year = season.get("year")
            if year is None:
                continue
            if seasons_set is not None:
                if int(year) not in seasons_set:
                    continue
            elif not season.get("current"):
                continue
            out.append(LeagueWork(
                league_id=lid_int,
                season=int(year),
                coverage=season.get("coverage") or {},
            ))
    return out


def coverage_by_league(works: Iterable[LeagueWork]) -> dict[int, dict[str, Any]]:
    """Lookup helper: league_id → coverage dict. Last-write-wins on dupes."""
    return {w.league_id: w.coverage for w in works}
