"""Build docs/ingestion-failure-report.pdf from the live ingestor database.

Run from the repo root (Postgres must be up on POSTGRES_HOST_PORT):

    .venv\\Scripts\\python docs\\_build_failure_report.py

Live (re-queried every build): run-status counts, dead-letter totals and causes,
missed scheduled days, the three charts, the current status of every run named
in the analysis, and any failed/partial run since the analysis cutoff.
Also writes docs/img/run-calendar.png and docs/img/api-calls.png (used by README).

Static: the context notes of the 2026-09-21 analysis (RESUMED_AFTER_CRASH, CONTEXT). They came from the scheduler's
/var/log/ingest.log (run.crashed events) and a /status probe, and that log is
wiped whenever the scheduler container is recreated.

Needs: reportlab, matplotlib, psycopg2 (in the project venv).
"""
from __future__ import annotations

import io
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import psycopg2  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

sys.path.insert(0, str(Path(__file__).parent))
from _build_pdf import _code, _make_table, _section_rule, _styles  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "ingestion-failure-report.pdf"
# README images, rewritten on every build.
IMG_DIR = ROOT / "docs" / "img"
BERLIN = ZoneInfo("Europe/Berlin")

# Scheduled runs are tagged by their Berlin start hour. The cron moved from
# 02:00 to 07:00 on 2026-09-21; the hour after each slot covers slow starts.
SCHEDULE_CHANGE = date(2026, 9, 22)
FIRST_SCHEDULED_DAY = date(2026, 6, 8)
# Runs after this instant are listed in "Runs since the analysis".
ANALYSIS_CUTOFF = datetime(2026, 9, 21, 10, 0, tzinfo=BERLIN)

# Crashed runs that were later resumed to success: finish_run overwrote their
# stored error, so the cause comes from the scheduler log (analysis 2026-09-21).
RESUMED_AFTER_CRASH = {
    "6e8e95b2": "Daily quota exhausted",
    "28e903ea": "Daily quota exhausted",
    "57c6e271": "Daily quota exhausted",
}
# Human context for notable runs (analysis 2026-09-21).
CONTEXT = {
    "6690374b": "Manual backfill, killed after ~20 h; 8 checkpoints left pending",
    "d3f8301c": "Start of 8 nights of DNS failures on the host (06-23..06-30)",
    "006702be": "Deliberate invalid-key test (task 0003 smoke)",
    "851d7576": "Quota spent by 5 test runs that day (task 0007)",
    "6ff51833": "Subscription expired 08-06",
    "272ad182": "Subscription lapsed; key on Free plan",
    "41ff3688": "Backfill 1e184047 running across midnight",
    "74b4af46": "Backfill 1e184047 still running",
    "80a18644": "After a 5,652-call day",
    "6e8e95b2": "Backfill f0743395 running across midnight",
}

# --- chart tokens (dataviz reference palette, light mode) ---
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES_1 = "#2a78d6"  # blue: scheduled runs
SERIES_2 = "#eb6834"  # orange: manual runs / backfills
STATUS = {
    "succeeded": ("#0ca30c", "white", "✓", "Succeeded"),
    "partial": ("#fab219", INK, "!", "Partial"),
    "failed": ("#d03b3b", "white", "✕", "Failed"),
    "none": (GRID, MUTED, "–", "No run"),
}

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"],
    "font.size": 8.5,
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK_2,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
})


# ---------------------------------------------------------------- data

def _read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _connect(env: dict[str, str]):
    return psycopg2.connect(
        host="localhost",
        port=int(env.get("POSTGRES_HOST_PORT", "5432")),
        user=env["POSTGRES_USER"],
        password=env["POSTGRES_PASSWORD"],
        dbname=env["POSTGRES_DB"],
    )


def _is_scheduled(r: dict) -> bool:
    a = r["args"] or {}
    if a.get("from_ts") or a.get("to_ts") or a.get("league_subset_override") \
            or a.get("seasons_override"):
        return False
    hour = r["started"].hour
    slot = (2, 3) if r["started"].date() < SCHEDULE_CHANGE else (7, 8)
    return hour in slot


def _calls(r: dict) -> int:
    """Estimated API calls: /leagues + one per attempted league + one per Phase-B task."""
    c = r["counters"] or {}
    if not c:
        return 0
    n = 1
    for phase in ("phase_a", "phase_b"):
        p = c.get(phase) or {}
        n += sum(int(p.get(k, 0)) for k in ("ok", "failed", "unchanged"))
    return n


def _cause(error_class: str, status: int | None, msg: str) -> str:
    m = msg.lower()
    if "free plans" in m:
        return "Plan restriction (Free plan)"
    if "limit for the day" in m:
        return "Daily quota exhausted"
    if status == 429 or "ratelimit" in m or "429" in m:
        return "Per-minute rate limit"
    if error_class == "ConnectError" or "name resolution" in m or "hostname" in m:
        return "Network (DNS)"
    return f"Other ({error_class})"


def _run_cause(err: str) -> str:
    """Classify the exception string a crashed run stored in counters.error."""
    if "client error 403" in err:
        return "HTTP 403 (key rejected)"
    return _cause(err.split(":", 1)[0], None, err)


def load() -> dict:
    env = _read_env()
    with _connect(env) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT r.run_id::text, r.started_at, r.finished_at, r.status, r.args,
                   r.counters, r.last_heartbeat_at,
                   (SELECT count(*) FROM dead_letter d WHERE d.run_id = r.run_id)
              FROM ingestion_runs r ORDER BY r.started_at""")
        runs = [{
            "id": row[0], "started": row[1].astimezone(BERLIN),
            "finished": row[2], "status": row[3], "args": row[4],
            "counters": row[5], "heartbeat": row[6], "dead": row[7],
        } for row in cur.fetchall()]
        cur.execute("""
            SELECT run_id::text, failed_at, error_class, http_status, error_message
              FROM dead_letter""")
        dead = [{
            "run": row[0], "at": row[1].astimezone(BERLIN),
            "cause": _cause(row[2], row[3], row[4]),
        } for row in cur.fetchall()]
    for r in runs:
        r["scheduled"] = _is_scheduled(r)
        r["calls"] = _calls(r)
    return {"runs": runs, "dead": dead,
            "daily_quota": int(env.get("DAILY_QUOTA", "7500"))}


def scheduled_by_day(runs: list[dict]) -> dict[date, dict]:
    out: dict[date, dict] = {}
    for r in runs:
        if r["scheduled"]:
            out.setdefault(r["started"].date(), r)
    return out


def missed_days(runs: list[dict], today: date) -> list[date]:
    have = scheduled_by_day(runs)
    d, out = FIRST_SCHEDULED_DAY, []
    while d <= today:
        if d not in have:
            out.append(d)
        d += timedelta(days=1)
    return out


def _ranges(days: list[date]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(days):
        j = i
        while j + 1 < len(days) and days[j + 1] - days[j] == timedelta(days=1):
            j += 1
        a, b = days[i], days[j]
        n = j - i + 1
        out.append(a.strftime("%m-%d") if n == 1
                   else f"{a:%m-%d} .. {b:%m-%d} ({n} days)")
        i = j + 1
    return out


# ---------------------------------------------------------------- charts

def _png(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=220, bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)
    buf.seek(0)
    return buf


def _title(fig, title: str, sub: str) -> None:
    fig.text(0.0, 1.0, title, ha="left", va="bottom", fontsize=10.5,
             fontweight="semibold", color=INK, transform=fig.transFigure)
    fig.text(0.0, 0.985, sub, ha="left", va="top", fontsize=8, color=INK_2,
             transform=fig.transFigure)


def chart_calendar(runs: list[dict], today: date) -> io.BytesIO:
    """One cell per day: outcome of that day's scheduled run."""
    by_day = scheduled_by_day(runs)
    months = []
    m = date(FIRST_SCHEDULED_DAY.year, FIRST_SCHEDULED_DAY.month, 1)
    while m <= today:
        months.append(m)
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)

    fig, ax = plt.subplots(figsize=(7.0, 0.42 * len(months) + 0.9))
    fig.subplots_adjust(left=0.09, right=1.0, top=0.9, bottom=0.2)
    counts: Counter[str] = Counter()
    for row, m in enumerate(months):
        y = len(months) - 1 - row
        ax.text(-0.6, y + 0.45, m.strftime("%b"), ha="right", va="center",
                color=INK_2, fontsize=8.5)
        for dom in range(1, 32):
            try:
                d = date(m.year, m.month, dom)
            except ValueError:
                continue
            if d < FIRST_SCHEDULED_DAY or d > today:
                continue
            r = by_day.get(d)
            key = "none" if r is None else (
                r["status"] if r["status"] in STATUS else "failed")
            counts[key] += 1
            fill, glyph_c, glyph, _ = STATUS[key]
            ax.add_patch(FancyBboxPatch(
                (dom - 1 + 0.06, y + 0.06), 0.88, 0.78,
                boxstyle="round,pad=0,rounding_size=0.12",
                facecolor=fill, edgecolor="none"))
            ax.text(dom - 1 + 0.5, y + 0.45, glyph, ha="center", va="center",
                    color=glyph_c, fontsize=7, fontfamily="DejaVu Sans",
                    fontweight="bold")
    for dom in (1, 5, 10, 15, 20, 25, 30):
        ax.text(dom - 0.5, len(months) + 0.1, str(dom), ha="center", va="bottom",
                color=MUTED, fontsize=7.5)
    ax.set_xlim(-2.2, 31)
    ax.set_ylim(-0.2, len(months) + 0.7)
    ax.axis("off")

    # Legend: swatch + glyph + label + count (never colour alone).
    x = 0.09
    for key in ("succeeded", "partial", "failed", "none"):
        fill, glyph_c, glyph, label = STATUS[key]
        fig.patches.append(FancyBboxPatch(
            (x, 0.03), 0.022, 0.07, boxstyle="round,pad=0,rounding_size=0.004",
            transform=fig.transFigure, facecolor=fill, edgecolor="none"))
        fig.text(x + 0.011, 0.065, glyph, ha="center", va="center", color=glyph_c,
                 fontsize=6.5, fontfamily="DejaVu Sans", fontweight="bold")
        fig.text(x + 0.03, 0.065, f"{label}  {counts[key]}", ha="left",
                 va="center", color=INK_2, fontsize=8)
        x += 0.2
    _title(fig, "Scheduled run outcome by day",
           f"First scheduled run of each day, {FIRST_SCHEDULED_DAY:%d %b} to "
           f"{today:%d %b %Y}. A run later resumed to success counts as succeeded.")
    return _png(fig)


def chart_calls(runs: list[dict], quota: int, today: date) -> io.BytesIO:
    """Estimated API calls per day, scheduled vs manual, against the daily limit."""
    sched: defaultdict[date, int] = defaultdict(int)
    manual: defaultdict[date, int] = defaultdict(int)
    for r in runs:
        (sched if r["scheduled"] else manual)[r["started"].date()] += r["calls"]
    start = min(r["started"].date() for r in runs)
    days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    xs = list(range(len(days)))
    s = [sched[d] for d in days]
    mnl = [manual[d] for d in days]

    fig, ax = plt.subplots(figsize=(7.0, 2.9))
    fig.subplots_adjust(left=0.08, right=0.99, top=0.84, bottom=0.1)
    ax.bar(xs, s, width=0.8, color=SERIES_1, edgecolor=SURFACE, linewidth=0.6,
           label="Scheduled run", zorder=2)
    ax.bar(xs, mnl, width=0.8, bottom=s, color=SERIES_2, edgecolor=SURFACE,
           linewidth=0.6, label="Manual run / backfill", zorder=2)
    ax.axhline(quota, color=INK_2, linewidth=1, zorder=3)
    ax.text(len(days) - 0.5, quota, f"Current daily limit {quota:,}", ha="right",
            va="bottom", color=INK, fontsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.6, zorder=0)
    ax.yaxis.set_major_locator(MaxNLocator(5, integer=True))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ticks = [i for i, d in enumerate(days) if d.day == 1]
    ax.set_xticks(ticks, [days[i].strftime("%b") for i in ticks])
    ax.set_xlim(-1, len(days))

    # Label only the biggest day (usually a backfill), not every bar.
    totals = [a + b for a, b in zip(s, mnl, strict=True)]
    peak = max(range(len(days)), key=totals.__getitem__)
    ax.annotate(f"{days[peak]:%d %b}: {totals[peak]:,}", (peak, totals[peak]),
                xytext=(6, -2), textcoords="offset points", ha="left", va="top",
                color=INK, fontsize=8)
    ax.set_ylim(0, max(totals) * 1.08)
    ax.legend(loc="upper right", bbox_to_anchor=(1, 1.04), ncols=2, frameon=False,
              fontsize=8, handlelength=1, handleheight=1, labelcolor=INK_2)
    _title(fig, "Estimated API calls per day",
           "Leagues + fixture tasks + 1 per run, from run counters, by the day the run "
           "started. Crashed runs count as 0. The limit\nwas 75,000/day (Ultra) until "
           "2026-08-06; the line shows today's limit from .env.")
    return _png(fig)


def chart_dead_letters(dead: list[dict]) -> io.BytesIO:
    by_cause = Counter(d["cause"] for d in dead).most_common()
    labels = [c for c, _ in by_cause][::-1]
    vals = [n for _, n in by_cause][::-1]
    fig, ax = plt.subplots(figsize=(7.0, 0.36 * len(labels) + 0.9))
    fig.subplots_adjust(left=0.28, right=0.93, top=0.84, bottom=0.04)
    ax.barh(labels, vals, height=0.5, color=SERIES_1, zorder=2)
    for y, v in enumerate(vals):
        ax.text(v, y, f"  {v:,}", va="center", ha="left", color=INK, fontsize=8)
    ax.xaxis.set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_color(AXIS)
    ax.tick_params(axis="y", length=0, labelcolor=INK_2, labelsize=8.5)
    ax.set_xlim(0, max(vals) * 1.12)
    _title(fig, "Dead-lettered calls by cause",
           f"All {len(dead):,} rows in dead_letter. Each is a league or fixture "
           "that a run gave up on after retries.")
    return _png(fig)


def _export(buf: io.BytesIO, name: str) -> io.BytesIO:
    """Save a chart for the README and hand back a fresh buffer for the PDF."""
    IMG_DIR.mkdir(exist_ok=True)
    (IMG_DIR / name).write_bytes(buf.getvalue())
    return io.BytesIO(buf.getvalue())


def _img(buf: io.BytesIO, width_mm: float = 170) -> Image:
    img = Image(buf)
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth = width_mm * mm
    img.drawHeight = width_mm * mm * ratio
    return img


# ---------------------------------------------------------------- document

def build() -> None:
    data = load()
    runs, dead = data["runs"], data["dead"]
    now = datetime.now(BERLIN)
    today = now.date()
    status_of = {r["id"][:8]: r["status"] for r in runs}
    s = _styles()
    B = lambda t: Paragraph(t, s["Body"])  # noqa: E731
    H = lambda t: Paragraph(t, s["H1"])  # noqa: E731

    def _on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#6b6f80"))
        canvas.drawString(20 * mm, 12 * mm, "API-Football Ingestor · Ingestion Failure Report")
        canvas.drawCentredString(A4[0] / 2, 12 * mm, f"Generated {now:%Y-%m-%d %H:%M}")
        canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title="API-Football Ingestor Ingestion Failure Report", author="Ingestor",
    )
    story: list = []
    first = runs[0]["started"].date()
    story.append(Paragraph("Ingestion Failure Report", s["TitleBig"]))
    story.append(Paragraph(
        f"All runs {first:%Y-%m-%d} to {today:%Y-%m-%d} &middot; bronze ingestor",
        s["Subtitle"]))
    story.append(_section_rule())
    story.append(Spacer(1, 10))

    # ---- 1. Summary (live) ----
    story.append(H("1. Summary"))
    st = Counter(r["status"] for r in runs)
    stale = [r for r in runs if r["status"] == "running" and r["heartbeat"]
             and (now - r["heartbeat"].astimezone(BERLIN)) > timedelta(minutes=10)]
    live = st["running"] - len(stale)
    running_note = ", ".join(f"{r['id'][:8]} orphan since {r['started']:%Y-%m-%d}"
                             for r in stale)
    if live:
        running_note = f"{live} in progress" + (f"; {running_note}" if running_note else "")
    story.append(_make_table(s, ["Run status", "Count", "Meaning"], [
        ("succeeded", f"{st['succeeded']}", "All work finished; projection refreshed"),
        ("partial", f"{st['partial']}", "Run finished, some leagues/fixtures dead-lettered"),
        ("failed", f"{st['failed']}", "Run aborted; nothing ingested"),
        ("running", f"{st['running']}", running_note or "&mdash;"),
    ], col_widths=[30 * mm, 18 * mm, 122 * mm]))
    story.append(Spacer(1, 6))
    missed = missed_days(runs, today)
    story.append(B(
        f"<b>{len(runs)} runs</b> in total. <b>{len(missed)} days had no scheduled run.</b> "
        f"<b>{len(dead):,} dead-letter rows</b> in total."))
    story.append(_img(_export(chart_calendar(runs, today), "run-calendar.png")))

    # ---- Findings (static analysis) ----
    story.append(B("<b>Findings (analysis of 2026-09-21)</b>"))
    for t in [
        "<b>Two causes explain every whole-run failure.</b> In late June, 8 nights in a "
        "row failed on <b>DNS</b>: the host could not resolve the API hostname at 02:00. "
        "From August on, every scheduled failure was the <b>daily quota</b>: the run died "
        "within 60&nbsp;s at the <font face='Courier'>/leagues</font> bootstrap call with "
        "<i>&quot;You have reached the request limit for the day&quot;</i>.",
        "<b>The configured quota was 10&times; too high.</b> <font face='Courier'>/status</font> "
        "reported plan <b>Pro, limit_day = 7,500</b>, while <font face='Courier'>.env</font> "
        "had <font face='Courier'>DAILY_QUOTA=75000</font> from the old Ultra plan, so the "
        f"internal limiter never throttled. <i>Now: DAILY_QUOTA={data['daily_quota']:,}.</i>",
        "<b>Backfills that ran past midnight used up the next day's quota.</b> 1e184047 "
        "(08-26 to 08-28) lines up with failed scheduled runs on 08-27 and 08-28. f0743395 "
        "(09-15 to 09-16) lines up with the failure on 09-16.",
        "<b>The old 02:00 Berlin slot is exactly 00:00 UTC in summer</b>, when the daily "
        "counter rolls over. All 11 logged crashes were rejected between 00:00:14 and "
        "00:01:42 UTC. The run moved to 07:00 Berlin on 2026-09-21.",
        "<b>Subscription lapses</b>: the plan expired 2026-08-06. The run failed on 08-07 "
        "and 08-09, and on 08-08 the key was on a Free plan. The plan seen on 09-21 "
        "ends <b>2026-09-26</b>.",
        "<b>Per-minute rate limiting</b> (HTTP 429 or in-body <font face='Courier'>rateLimit</font>) "
        "caused all partial runs, usually 1&ndash;11 items each.",
    ]:
        story.append(B("&bull; " + t))

    # ---- 2. Quota ----
    story.append(PageBreak())
    story.append(H("2. Quota usage"))
    story.append(_img(_export(chart_calls(runs, data["daily_quota"], today), "api-calls.png")))
    sched_calls = sorted(r["calls"] for r in runs if r["scheduled"] and r["calls"])
    if sched_calls:
        med = sched_calls[len(sched_calls) // 2]
        story.append(B(
            f"A scheduled run uses <b>{sched_calls[0]:,}&ndash;{sched_calls[-1]:,}</b> calls "
            f"(median {med:,}), or up to {sched_calls[-1] / data['daily_quota']:.0%} of the "
            f"{data['daily_quota']:,} daily limit. Any backfill on the same day has to "
            "fit in what's left, or it eats into the next day's quota."))
    story.append(B(
        "<b>Open question:</b> on some days the scheduled run hit the limit even though "
        "the ingestor used well under 7,500 calls the previous UTC day. Either the "
        "API's counter resets some time after 00:00 UTC, or something else uses the key. "
        "Logging <font face='Courier'>x-ratelimit-requests-remaining</font> (task 0009) "
        "would settle it."))

    # ---- 3. Whole-run failures (live causes + static context) ----
    story.append(H("3. Whole-run failures"))
    story.append(B(
        "Each crashed run stores its exception in <font face='Courier'>ingestion_runs."
        "counters-&gt;'error'</font>, so causes come live from the database. A run that "
        "was later resumed to success has its error overwritten. Those runs are listed "
        "with the cause taken from the scheduler log. <i>Context</i> is the 2026-09-21 "
        "analysis. Times are Berlin time."))
    by_id = {r["id"][:8]: r for r in runs}
    rows = []
    for r in runs:
        err = (r["counters"] or {}).get("error")
        if r["status"] != "failed" and r["id"][:8] not in RESUMED_AFTER_CRASH:
            continue
        cause = (_run_cause(err) if err
                 else RESUMED_AFTER_CRASH.get(r["id"][:8], "No error recorded"))
        rows.append((r["id"][:8], f"{r['started']:%m-%d %H:%M}", cause,
                     CONTEXT.get(r["id"][:8], ""), r["status"]))
    story.append(_make_table(s, ["Run", "Started", "Cause", "Context", "Status now"], rows,
                             col_widths=[20 * mm, 22 * mm, 38 * mm, 70 * mm, 20 * mm]))
    causes = Counter(row[2] for row in rows)
    story.append(Spacer(1, 4))
    story.append(B("<b>By cause:</b> " + ", ".join(f"{c} {n}" for c, n in causes.most_common())
                   + f". ({len([k for k in RESUMED_AFTER_CRASH if k in by_id])} of these "
                   "were resumed afterwards.)"))
    story.append(Spacer(1, 6))
    story.append(B(
        "<b>Why retries don't help:</b> the client treats the day-limit message as "
        "retryable. It retries <font face='Courier'>/leagues</font> 7 times over about "
        "40 s and then crashes, but a daily limit won't clear in 40 s."))

    # ---- 4. Dead letters (live) ----
    story.append(KeepTogether([H("4. Partial runs and dead letters"),
                               _img(chart_dead_letters(dead))]))
    per_run: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for d in dead:
        per_run[d["run"]][d["cause"]] += 1
    part_rows = []
    for r in runs:
        if r["status"] != "partial":
            continue
        causes = "; ".join(f"{c} ({n})" for c, n in per_run[r["id"]].most_common())
        part_rows.append((r["id"][:8], f"{r['started']:%m-%d %H:%M}",
                          f"{r['dead']:,}", causes or "&mdash;"))
    story.append(_make_table(s, ["Run", "Started", "Dead letters", "Causes"], part_rows,
                             col_widths=[22 * mm, 26 * mm, 24 * mm, 98 * mm]))

    # ---- 5. Missed days (live) ----
    story.append(H("5. Days with no scheduled run"))
    story.append(B(
        "These days have no scheduled run row at all, so the scheduler never launched "
        "the ingestor. The usual reason is that the PC or Docker Desktop wasn't running "
        "at the scheduled time. Backfill a gap with "
        "<font face='Courier'>--from/--to</font>."))
    story.append(_code(s, "\n".join(_ranges(missed)) or "None"))

    # ---- 6. Since the analysis (live) ----
    story.append(H("6. Runs since the analysis"))
    later = [r for r in runs if r["started"] >= ANALYSIS_CUTOFF
             and r["status"] in ("failed", "partial")]
    if later:
        story.append(B(
            "Failed or partial runs started after 2026-09-21 10:00. Check the scheduler "
            "log for failed runs before it's recreated."))
        story.append(_make_table(s, ["Run", "Started", "Status", "Dead-letter causes"], [
            (r["id"][:8], f"{r['started']:%Y-%m-%d %H:%M}", r["status"],
             "; ".join(f"{c} ({n})" for c, n in per_run[r["id"]].most_common())
             or "none recorded (crashed before Phase A: see log)")
            for r in later
        ], col_widths=[22 * mm, 34 * mm, 20 * mm, 94 * mm]))
    else:
        story.append(B("No failed or partial runs since 2026-09-21 10:00."))

    # ---- 7. Recommendations ----
    story.append(H("7. Recommendations"))
    story.append(_make_table(s, ["#", "Action", "Status (09-21)"], [
        ("1", "Move the cron from 02:00 to 07:00 Berlin", "Done"),
        ("2", "Set DAILY_QUOTA to the plan's real limit (7,500)", "Done"),
        ("3", "Renew the API-Football subscription before <b>2026-09-26</b>", "Owner action"),
        ("4", "Split backfills into date chunks that fit one day's quota, leaving "
              "~3,000 calls for the scheduled run; never run them past 00:00 UTC", "Practice"),
        ("5", "Make the day-limit response non-retryable: fail fast, record the reason",
         "Coordinator task"),
        ("6", "Persist /var/log/ingest.log on a volume (recreating the scheduler wipes it)",
         "Coordinator task"),
        ("7", "Log x-ratelimit-requests-remaining on each run (task 0009)", "Backlog"),
        ("8", "Close orphan run ba83af6a (status running since 06-18)", "Housekeeping"),
    ], col_widths=[8 * mm, 127 * mm, 35 * mm], cmd_col=-1))
    story.append(Paragraph("<b>Regenerate this report</b>", s["Body"]))
    story.append(_code(s, r".venv\Scripts\python docs\_build_failure_report.py"))

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    print(f"OK: {OUTPUT}")


if __name__ == "__main__":
    build()
