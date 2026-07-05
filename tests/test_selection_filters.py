"""Pure-Python: league + fixture selection logic."""
from __future__ import annotations

from ingestor.selection.fixture_filter import (
    extract_fixture_records,
    select_fixture_ids,
)
from ingestor.selection.league_filter import coverage_by_league, select_leagues


def _league(lid: int, *, current_year: int, coverage_flags: dict[str, bool]) -> dict:
    return {
        "league": {"id": lid, "name": f"L{lid}"},
        "seasons": [
            {"year": current_year - 1, "current": False, "coverage": {"fixtures": coverage_flags}},
            {"year": current_year, "current": True, "coverage": {"fixtures": coverage_flags}},
        ],
    }


# ---- league_filter ----

def test_select_leagues_returns_current_seasons_only() -> None:
    payload = {"response": [_league(39, current_year=2025, coverage_flags={"lineups": True})]}
    works = select_leagues(payload)
    assert len(works) == 1
    assert works[0].league_id == 39
    assert works[0].season == 2025
    assert works[0].coverage == {"fixtures": {"lineups": True}}


def test_select_leagues_seasons_override_returns_those_seasons() -> None:
    """seasons=[...] replaces the current=true filter."""
    payload = {"response": [_league(39, current_year=2025, coverage_flags={"lineups": True})]}
    # _league() helper produces seasons [current_year-1, current_year]
    works = select_leagues(payload, seasons=[2024, 2025])
    years = sorted(w.season for w in works)
    assert years == [2024, 2025]


def test_select_leagues_seasons_override_can_skip_current() -> None:
    """If seasons doesn't include current, current is NOT returned."""
    payload = {"response": [_league(39, current_year=2025, coverage_flags={"lineups": True})]}
    works = select_leagues(payload, seasons=[2024])
    assert len(works) == 1
    assert works[0].season == 2024


def test_select_leagues_seasons_and_subset_compose() -> None:
    payload = {"response": [
        _league(39, current_year=2025, coverage_flags={"lineups": True}),
        _league(140, current_year=2025, coverage_flags={"lineups": True}),
    ]}
    works = select_leagues(payload, subset=[39], seasons=[2024])
    assert len(works) == 1
    assert works[0].league_id == 39
    assert works[0].season == 2024


def test_select_leagues_subset_filter() -> None:
    payload = {
        "response": [
            _league(39, current_year=2025, coverage_flags={"events": True}),
            _league(140, current_year=2025, coverage_flags={"events": True}),
        ]
    }
    works = select_leagues(payload, subset=[140])
    assert [w.league_id for w in works] == [140]


def test_select_leagues_handles_missing_fields() -> None:
    payload = {
        "response": [
            {"league": {}, "seasons": [{"year": 2025, "current": True}]},
            {"league": {"id": 39}, "seasons": [{"current": True}]},  # missing year
            _league(140, current_year=2025, coverage_flags={"lineups": True}),
        ]
    }
    works = select_leagues(payload)
    assert [w.league_id for w in works] == [140]


def test_coverage_by_league_lookup() -> None:
    payload = {"response": [_league(39, current_year=2025, coverage_flags={"events": True})]}
    works = select_leagues(payload)
    lookup = coverage_by_league(works)
    assert lookup[39] == {"fixtures": {"events": True}}


# ---- fixture_filter ----

def _fix(fid: int, *, lid: int, season: int, status: str, ts: int) -> dict:
    return {
        "fixture": {"id": fid, "timestamp": ts, "status": {"short": status}},
        "league": {"id": lid, "season": season},
    }


def test_extract_records_skips_sparse() -> None:
    payload = {
        "response": [
            _fix(1, lid=39, season=2025, status="FT", ts=1_700_000_000),
            {"fixture": {"id": 2}, "league": {"id": 39}},  # sparse: no status/ts/season
            _fix(3, lid=39, season=2025, status="1H", ts=1_700_000_100),
        ]
    }
    recs = extract_fixture_records(payload)
    assert [r.fixture_id for r in recs] == [1, 3]


def test_select_filters_status_and_lookback_and_coverage() -> None:
    NOW = 1_700_000_000
    DAY = 86_400
    # build via the public extractor for fidelity
    payload = {
        "response": [
            _fix(1, lid=39, season=2025, status="FT", ts=NOW - DAY),          # keep
            _fix(2, lid=39, season=2025, status="NS", ts=NOW - DAY),          # bad status
            _fix(3, lid=39, season=2025, status="FT", ts=NOW - 30 * DAY),     # too old
            _fix(4, lid=99, season=2025, status="FT", ts=NOW - DAY),          # uncovered league
            _fix(5, lid=39, season=2025, status="FT", ts=NOW - DAY),          # dupe of league/time but unique id → keep
        ]
    }
    records = extract_fixture_records(payload)
    coverage = {
        39: {"fixtures": {"lineups": True}},
        99: {"fixtures": {"lineups": False, "events": False}},
    }
    out = select_fixture_ids(
        records, coverage,
        statuses=["FT", "1H"], lookback_days=14, now_ts=NOW,
    )
    assert out == [1, 5]


def test_select_status_case_insensitive() -> None:
    NOW = 1_700_000_000
    records = extract_fixture_records({
        "response": [_fix(1, lid=39, season=2025, status="ft", ts=NOW)]
    })
    out = select_fixture_ids(
        records, {39: {"fixtures": {"lineups": True}}},
        statuses=["FT"], lookback_days=1, now_ts=NOW,
    )
    assert out == [1]


def test_select_requires_any_flag_not_all() -> None:
    NOW = 1_700_000_000
    records = extract_fixture_records({
        "response": [_fix(1, lid=39, season=2025, status="FT", ts=NOW)]
    })
    # Only `events` is true, but that's enough.
    out = select_fixture_ids(
        records, {39: {"fixtures": {"events": True, "lineups": False}}},
        statuses=["FT"], lookback_days=1, now_ts=NOW,
    )
    assert out == [1]


def test_select_dedups_repeated_ids() -> None:
    NOW = 1_700_000_000
    records = [
        *extract_fixture_records({"response": [_fix(1, lid=39, season=2025, status="FT", ts=NOW)]}),
        *extract_fixture_records({"response": [_fix(1, lid=39, season=2025, status="FT", ts=NOW)]}),
    ]
    out = select_fixture_ids(
        records, {39: {"fixtures": {"lineups": True}}},
        statuses=["FT"], lookback_days=1, now_ts=NOW,
    )
    assert out == [1]


# ---- date range overrides ----

def test_select_from_to_range_overrides_lookback() -> None:
    """A from/to window picks fixtures in the range, ignoring lookback_days."""
    DAY = 86_400
    NOW = 1_700_000_000
    payload = {
        "response": [
            _fix(1, lid=39, season=2025, status="FT", ts=NOW - 100 * DAY),  # in range
            _fix(2, lid=39, season=2025, status="FT", ts=NOW - 50 * DAY),   # in range
            _fix(3, lid=39, season=2025, status="FT", ts=NOW - 200 * DAY),  # before range
            _fix(4, lid=39, season=2025, status="FT", ts=NOW - 10 * DAY),   # after range
        ]
    }
    records = extract_fixture_records(payload)
    out = select_fixture_ids(
        records, {39: {"fixtures": {"lineups": True}}},
        statuses=["FT"], lookback_days=1, now_ts=NOW,  # lookback would alone keep #4 only
        from_ts=NOW - 150 * DAY, to_ts=NOW - 40 * DAY,
    )
    assert out == [1, 2]


def test_select_from_only_open_end() -> None:
    """--from alone = from that date until effectively forever."""
    DAY = 86_400
    NOW = 1_700_000_000
    payload = {
        "response": [
            _fix(1, lid=39, season=2025, status="FT", ts=NOW - 5 * DAY),
            _fix(2, lid=39, season=2025, status="FT", ts=NOW - 30 * DAY),  # before from
        ]
    }
    records = extract_fixture_records(payload)
    out = select_fixture_ids(
        records, {39: {"fixtures": {"lineups": True}}},
        statuses=["FT"], lookback_days=1, now_ts=NOW,
        from_ts=NOW - 10 * DAY,
    )
    assert out == [1]


def test_select_to_only_open_start() -> None:
    """--to alone = everything up to that date."""
    DAY = 86_400
    NOW = 1_700_000_000
    payload = {
        "response": [
            _fix(1, lid=39, season=2025, status="FT", ts=NOW - 30 * DAY),
            _fix(2, lid=39, season=2025, status="FT", ts=NOW - 5 * DAY),  # after to
        ]
    }
    records = extract_fixture_records(payload)
    out = select_fixture_ids(
        records, {39: {"fixtures": {"lineups": True}}},
        statuses=["FT"], lookback_days=1, now_ts=NOW,
        to_ts=NOW - 10 * DAY,
    )
    assert out == [1]
