"""Command-line entrypoint: `python -m ingestor.cli ingest [options]`.

Minimal v1 — wires Settings + run_ingestion. Backfill knobs are exposed as
flags so a backfill is just a normal run with different args (per ROADMAP).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
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
    p.add_argument("--season", type=int, default=None)
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

    ns = parser.parse_args(argv)

    if ns.cmd != "ingest":
        parser.print_help()
        return 2

    from_ts, to_ts = _parse_date_range(ns.date_from, ns.date_to)

    settings = get_settings()
    args = RunArgs(
        season_override=ns.season,
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


def _to_epoch(s: str, *, end_of_day: bool) -> int:
    try:
        d = datetime.strptime(s, "%d-%m-%Y").replace(tzinfo=timezone.utc)
    except ValueError as e:
        print(f"error: invalid date {s!r}, expected DD-MM-YYYY: {e}", file=sys.stderr)
        raise SystemExit(2) from e
    if end_of_day:
        d = d.replace(hour=23, minute=59, second=59)
    return int(d.timestamp())


if __name__ == "__main__":
    sys.exit(main())
