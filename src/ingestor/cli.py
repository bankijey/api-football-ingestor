"""Command-line entrypoint: `python -m ingestor.cli ingest [options]`.

Minimal v1 — wires Settings + run_ingestion. Backfill knobs are exposed as
flags so a backfill is just a normal run with different args (per ROADMAP).
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from .config import get_settings
from .orchestrator.runner import RunArgs, run_ingestion

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = REPO_ROOT / "migrations"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingestor")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="Run a one-off bronze ingestion.")
    p.add_argument("--season", type=int, default=None,
                   help="Shorthand for --seasons with a single year.")
    p.add_argument("--seasons", type=str, default=None,
                   help="Comma-separated season years (e.g. 2019,2020,2021,2022). "
                        "When set, replaces the default 'current season only' filter "
                        "and pulls Phase A for every (league, season) pair listed. "
                        "Use for historical backfills.")
    p.add_argument("--leagues", type=str, default=None,
                   help="Comma-separated league ids to restrict Phase A.")
    p.add_argument("--lookback-days", type=int, default=None,
                   help="Override LOOKBACK_DAYS for Phase B selection.")
    p.add_argument("--from", dest="date_from", type=str, default=None,
                   metavar="DD-MM-YYYY",
                   help="Phase-B start date (inclusive). Overrides --lookback-days.")
    p.add_argument("--to", dest="date_to", type=str, default=None,
                   metavar="DD-MM-YYYY",
                   help="Phase-B end date (inclusive). Overrides --lookback-days.")
    p.add_argument("--resume", type=str, default=None,
                   help="Resume an existing run_id (UUID).")
    p.add_argument("--no-migrate", action="store_true",
                   help="Skip applying migrations at startup.")
    p.add_argument("--allow-seasons-without-dates", action="store_true",
                   help="Bypass the safety check that requires --from/--to "
                        "(or --lookback-days) whenever --seasons is set. "
                        "Only use if you really want Phase A to run for historical "
                        "seasons while Phase B's rolling window filters out "
                        "everything (almost never what you want).")

    ns = parser.parse_args(argv)

    if ns.cmd != "ingest":
        parser.print_help()
        return 2

    from_ts, to_ts = _parse_date_range(ns.date_from, ns.date_to)
    seasons = _merge_seasons(ns.season, ns.seasons)
    _guard_seasons_with_window(
        seasons=seasons,
        from_ts=from_ts,
        to_ts=to_ts,
        lookback_days=ns.lookback_days,
        bypass=ns.allow_seasons_without_dates,
    )

    settings = get_settings()
    args = RunArgs(
        seasons_override=seasons,
        league_subset_override=_parse_ids(ns.leagues),
        lookback_days_override=ns.lookback_days,
        resume_run_id=UUID(ns.resume) if ns.resume else None,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    result = run_ingestion(
        settings,
        args=args,
        migrations_dir=None if ns.no_migrate else MIGRATIONS_DIR,
    )
    # Exit non-zero on partial-failure runs so CI / cron notices.
    return 0 if result.status == "succeeded" else 1


def _parse_ids(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def _merge_seasons(single: int | None, multi: str | None) -> list[int] | None:
    """Combine --season (single) and --seasons (csv) into one list, or None.

    Either, both, or neither may be provided. Duplicates are removed.
    """
    out: list[int] = []
    if single is not None:
        out.append(int(single))
    if multi:
        for x in multi.split(","):
            x = x.strip()
            if x:
                out.append(int(x))
    if not out:
        return None
    # Dedup, preserve first-seen order.
    seen: set[int] = set()
    ordered: list[int] = []
    for y in out:
        if y not in seen:
            seen.add(y)
            ordered.append(y)
    return ordered


def _parse_date_range(
    raw_from: str | None,
    raw_to: str | None,
) -> tuple[int | None, int | None]:
    """Parse DD-MM-YYYY date strings into epoch seconds (UTC).

    `from` is the start of its day (00:00 UTC); `to` is the end (23:59:59 UTC)
    so the range is inclusive of both endpoints.
    Raises SystemExit on invalid input or from > to.
    """
    from_ts = _to_epoch(raw_from, end_of_day=False) if raw_from else None
    to_ts = _to_epoch(raw_to, end_of_day=True) if raw_to else None
    if from_ts is not None and to_ts is not None and from_ts > to_ts:
        print(f"error: --from ({raw_from}) is after --to ({raw_to})", file=sys.stderr)
        raise SystemExit(2)
    return from_ts, to_ts


def _guard_seasons_with_window(
    *,
    seasons: list[int] | None,
    from_ts: int | None,
    to_ts: int | None,
    lookback_days: int | None,
    bypass: bool,
) -> None:
    """Refuse if --seasons is passed without a matching Phase-B time window.

    Without --from/--to (or a manual --lookback-days), Phase B keeps only
    fixtures inside the rolling lookback window — typically the last 2 days,
    which never overlaps with a historical season. The result is wasted Phase
    A calls and zero Phase B rows. Hard-fail unless the user opts in.
    """
    if not seasons or bypass:
        return
    if from_ts is not None or to_ts is not None or lookback_days is not None:
        return
    msg = (
        "error: --seasons was passed without --from/--to (or --lookback-days).\n"
        f"  seasons requested : {seasons}\n"
        "  Phase A would fetch every (league, season) pair in this list, but\n"
        "  Phase B's default rolling window (last LOOKBACK_DAYS days) would\n"
        "  not match any historical fixtures — so you'd burn API quota for\n"
        "  zero fixture_details / halftime_stats rows.\n\n"
        "  Almost certainly you want something like:\n"
        f"    --seasons {','.join(map(str, seasons))} "
        f"--from 01-01-{min(seasons)} --to 31-12-{max(seasons)}\n\n"
        "  If you really meant this combination, re-run with\n"
        "  --allow-seasons-without-dates to bypass this check."
    )
    print(msg, file=sys.stderr)
    raise SystemExit(2)


def _to_epoch(s: str, *, end_of_day: bool) -> int:
    try:
        d = datetime.strptime(s, "%d-%m-%Y").replace(tzinfo=UTC)
    except ValueError as e:
        print(f"error: invalid date {s!r}, expected DD-MM-YYYY: {e}", file=sys.stderr)
        raise SystemExit(2) from e
    if end_of_day:
        d = d.replace(hour=23, minute=59, second=59)
    return int(d.timestamp())


if __name__ == "__main__":
    sys.exit(main())
