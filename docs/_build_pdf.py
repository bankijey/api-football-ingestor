"""One-off PDF builder for the operator reference. Safe to delete."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT = Path(r"C:\Users\Dumebi\Arbibet\api-football-ingestor\docs\ingestor-commands.pdf")

# --- palette ---
INDIGO = colors.HexColor("#1f2a5e")
ACCENT = colors.HexColor("#2c7be5")
GREY_BG = colors.HexColor("#f4f6fb")
GREY_BORDER = colors.HexColor("#d4d8e3")
CODE_BG = colors.HexColor("#1e1e2e")
CODE_FG = colors.HexColor("#e8eaf2")


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(
        "TitleBig", parent=s["Title"],
        fontName="Helvetica-Bold", fontSize=24, leading=28,
        textColor=INDIGO, alignment=TA_LEFT, spaceAfter=4,
    ))
    s.add(ParagraphStyle(
        "Subtitle", parent=s["Normal"],
        fontName="Helvetica", fontSize=13, leading=16,
        textColor=colors.HexColor("#4a5275"), alignment=TA_LEFT, spaceAfter=10,
    ))
    s.add(ParagraphStyle(
        "H1", parent=s["Heading1"],
        fontName="Helvetica-Bold", fontSize=15, leading=19,
        textColor=INDIGO, spaceBefore=14, spaceAfter=6,
        borderPadding=(0, 0, 4, 0),
    ))
    s.add(ParagraphStyle(
        "Body", parent=s["Normal"],
        fontName="Helvetica", fontSize=10, leading=14,
        spaceAfter=6,
    ))
    s.add(ParagraphStyle(
        "BodyMono", parent=s["Normal"],
        fontName="Courier", fontSize=9, leading=12,
        textColor=colors.HexColor("#222"),
    ))
    s.add(ParagraphStyle(
        "CellMono", parent=s["Normal"],
        fontName="Courier", fontSize=8.5, leading=11,
        textColor=colors.HexColor("#1a1a2e"),
    ))
    s.add(ParagraphStyle(
        "CellText", parent=s["Normal"],
        fontName="Helvetica", fontSize=9, leading=12,
    ))
    s.add(ParagraphStyle(
        "CodeBlock", parent=s["Normal"],
        fontName="Courier", fontSize=9, leading=12,
        textColor=CODE_FG, backColor=CODE_BG,
        borderPadding=(8, 8, 8, 8),
        spaceBefore=4, spaceAfter=10,
        leftIndent=0, rightIndent=0,
    ))
    return s


def _section_rule():
    t = Table([[""]], colWidths=[170 * mm], rowHeights=[1])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ACCENT)]))
    return t


def _make_table(styles, header, rows, col_widths, cmd_col=0):
    """Build a striped table; `cmd_col` index uses monospace styling."""
    data = [[Paragraph(f"<b>{h}</b>", styles["CellText"]) for h in header]]
    for r in rows:
        cells = []
        for i, val in enumerate(r):
            style = styles["CellMono"] if i == cmd_col else styles["CellText"]
            cells.append(Paragraph(val, style))
        data.append(cells)

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY_BG]),
        ("GRID", (0, 0), (-1, -1), 0.4, GREY_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
    ]))
    return t


def _code(styles, text):
    # Escape XML
    safe = (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br/>"))
    return Paragraph(safe, styles["CodeBlock"])


def _on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#6b6f80"))
    # Footer left: project label
    canvas.drawString(20 * mm, 12 * mm, "API-Football Ingestor · Operator Reference")
    # Footer center: date
    canvas.drawCentredString(A4[0] / 2, 12 * mm, "June 2026")
    # Footer right: page number
    canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title="API-Football Ingestor Operator Reference",
        author="Ingestor",
    )
    story = []

    # ---- Title block ----
    story.append(Paragraph("API-Football Ingestor", styles["TitleBig"]))
    story.append(Paragraph("Operator Reference", styles["TitleBig"]))
    story.append(Paragraph("Bronze layer commands, scheduler, and date-range backfills",
                           styles["Subtitle"]))
    story.append(_section_rule())
    story.append(Spacer(1, 10))

    # ---- 1. Overview ----
    story.append(Paragraph("1. Overview", styles["H1"]))
    story.append(Paragraph(
        "The ingestor fetches data from API-Football into a Postgres "
        "<i>bronze layer</i> (raw, append-only). It runs on demand from your "
        "terminal and automatically once a day via a scheduler container.",
        styles["Body"]))
    story.append(Paragraph("Three containers make up the stack:", styles["Body"]))
    story.append(Paragraph(
        "• <b>ingestor-postgres</b> &mdash; the database (always running on host port 5434)",
        styles["Body"]))
    story.append(Paragraph(
        "• <b>ingestor-scheduler</b> &mdash; a small cron container that triggers the "
        "nightly run at 02:00 Europe/Berlin",
        styles["Body"]))
    story.append(Paragraph(
        "• <b>ingestor</b> &mdash; the actual ingestor (built on demand; profile <font face='Courier'>cli</font>)",
        styles["Body"]))
    story.append(Paragraph(
        "All commands assume your working directory is "
        "<font face='Courier'>C:\\Users\\Dumebi\\Arbibet\\api-football-ingestor</font>.",
        styles["Body"]))

    # ---- 2. Stack lifecycle ----
    story.append(Paragraph("2. Stack lifecycle", styles["H1"]))
    story.append(_make_table(styles,
        ["Command", "What it does"],
        [
            ("docker compose up -d postgres",
             "Start just the database (always-on)"),
            ("docker compose --profile scheduler up -d scheduler",
             "Start the cron scheduler"),
            ("docker compose ps",
             "List running containers + their host ports"),
            ("docker compose down",
             "Stop everything (database files persist)"),
            ("docker compose down -v",
             "Stop everything AND delete the database. Use with care"),
        ],
        col_widths=[95 * mm, 75 * mm]))

    # ---- 3. Running — daily / one-off ----
    story.append(Paragraph("3. Running the ingestor &mdash; daily / one-off", styles["H1"]))
    story.append(_make_table(styles,
        ["Command", "What it does"],
        [
            ("docker compose run --rm ingestor ingest",
             "Full ingest now: all leagues, current season, last 2 days of fixtures"),
            ("docker compose run --rm ingestor ingest --leagues 39,140",
             "Only Premier League + La Liga"),
            ("docker compose run --rm ingestor ingest --season 2024",
             "Override the season"),
            ("docker compose run --rm ingestor ingest --lookback-days 7",
             "Override the rolling window (default 2)"),
            ("docker compose run --rm ingestor ingest --resume &lt;run-uuid&gt;",
             "Resume an interrupted run"),
            ("docker compose run --rm ingestor ingest --no-migrate",
             "Skip schema migration step"),
            ("docker compose run --rm ingestor migrate",
             "Apply schema migrations only"),
        ],
        col_widths=[100 * mm, 70 * mm]))

    # ---- 4. Historical backfills ----
    story.append(PageBreak())
    story.append(Paragraph("4. Running the ingestor &mdash; historical backfills (NEW)",
                           styles["H1"]))
    story.append(Paragraph(
        "Use <font face='Courier'>--from</font> and <font face='Courier'>--to</font> "
        "(format <font face='Courier'>DD-MM-YYYY</font>) to pull fixture details and "
        "halftime statistics for a specific historical window. These flags override "
        "<font face='Courier'>--lookback-days</font>. Both dates are inclusive.",
        styles["Body"]))
    story.append(_make_table(styles,
        ["Command", "What it does"],
        [
            ("docker compose run --rm ingestor ingest --from 01-03-2025 --to 31-03-2025",
             "Backfill all fixtures in March 2025"),
            ("docker compose run --rm ingestor ingest --from 01-01-2025 --to 31-01-2025 --leagues 39",
             "Premier League only, January 2025"),
            ("docker compose run --rm ingestor ingest --from 15-04-2025",
             "From that date until now"),
            ("docker compose run --rm ingestor ingest --to 31-12-2024",
             "Everything up to end of 2024"),
        ],
        col_widths=[110 * mm, 60 * mm]))
    story.append(Paragraph(
        "<b>Note:</b> Phase A still fetches every league's fixtures as usual; the "
        "date filter only affects which fixtures get the rich details + halftime "
        "stats (Phase B).",
        styles["Body"]))

    # ---- 5. Rebuilding ----
    story.append(Paragraph("5. Rebuilding after code changes", styles["H1"]))
    story.append(_make_table(styles,
        ["Command", "What it does"],
        [
            ("docker compose build ingestor",
             "Rebuild the ingestor image after Python code changes"),
            ("docker compose --profile scheduler up -d --force-recreate scheduler",
             "Restart scheduler so it picks up new .env values or compose changes"),
        ],
        col_widths=[100 * mm, 70 * mm]))

    # ---- 6. Inspecting & debugging ----
    story.append(Paragraph("6. Inspecting &amp; debugging", styles["H1"]))
    story.append(_make_table(styles,
        ["Command", "What it does"],
        [
            ("docker compose logs -f postgres",
             "Follow Postgres logs"),
            ("docker exec ingestor-scheduler crontab -l",
             "Show the active cron schedule"),
            ("docker exec ingestor-scheduler date",
             "Confirm scheduler timezone (should show CEST/CET)"),
            ("docker exec ingestor-scheduler tail -f /var/log/ingest.log",
             "Watch nightly run logs in real time"),
            ("docker exec ingestor-scheduler tail -n 500 /var/log/ingest.log",
             "Last 500 log lines"),
            ("docker exec -it ingestor-postgres psql -U ingestor -d ingestor",
             "Open psql shell inside Postgres"),
        ],
        col_widths=[100 * mm, 70 * mm]))

    # ---- 7. Manual trigger ----
    story.append(Paragraph("7. Manual scheduler trigger", styles["H1"]))
    story.append(Paragraph(
        "Trigger the same run the cron will fire at 2 a.m., immediately:",
        styles["Body"]))
    story.append(_code(styles,
        'docker exec ingestor-scheduler sh -c '
        '"docker compose -f /workspace/docker-compose.yml run --rm ingestor ingest"'))

    # ---- 8. SQL snippets ----
    story.append(PageBreak())
    story.append(Paragraph("8. Useful SQL snippets", styles["H1"]))
    story.append(Paragraph(
        "Run these in DBeaver (Host=<font face='Courier'>localhost</font>, "
        "Port=<font face='Courier'>5434</font>, DB=<font face='Courier'>ingestor</font>, "
        "User=<font face='Courier'>ingestor</font>, Password=<font face='Courier'>ingestor</font>) "
        "or via <font face='Courier'>psql</font>.",
        styles["Body"]))

    story.append(Paragraph("<b>Most recent runs</b>", styles["Body"]))
    story.append(_code(styles,
        "SELECT run_id, started_at, finished_at, status\n"
        "FROM ingestion_runs\n"
        "ORDER BY started_at DESC\n"
        "LIMIT 10;"))

    story.append(Paragraph("<b>Dead-letter summary for the latest run</b>", styles["Body"]))
    story.append(_code(styles,
        "SELECT endpoint, error_class, count(*)\n"
        "FROM dead_letter\n"
        "WHERE run_id = (SELECT run_id FROM ingestion_runs\n"
        "                ORDER BY started_at DESC LIMIT 1)\n"
        "GROUP BY 1, 2\n"
        "ORDER BY 3 DESC;"))

    story.append(Paragraph("<b>Row counts per bronze table</b>", styles["Body"]))
    story.append(_code(styles,
        "SELECT 'bronze_leagues' AS table, count(*) FROM bronze_leagues\n"
        "UNION ALL SELECT 'bronze_fixtures', count(*) FROM bronze_fixtures\n"
        "UNION ALL SELECT 'bronze_fixture_details', count(*) FROM bronze_fixture_details\n"
        "UNION ALL SELECT 'bronze_halftime_stats', count(*) FROM bronze_halftime_stats;"))

    story.append(Paragraph("<b>Find fixtures missing detail records (gaps)</b>", styles["Body"]))
    story.append(_code(styles,
        "SELECT f.fixture_id\n"
        "FROM (SELECT DISTINCT (payload->'response'->0->'fixture'->>'id')::bigint AS fixture_id\n"
        "      FROM bronze_fixtures) f\n"
        "LEFT JOIN bronze_fixture_details d ON d.fixture_id = f.fixture_id\n"
        "WHERE d.fixture_id IS NULL\n"
        "LIMIT 50;"))

    # ---- 9. Config knobs ----
    story.append(PageBreak())
    story.append(Paragraph("9. Configuration knobs (.env)", styles["H1"]))
    story.append(Paragraph(
        "Edit <font face='Courier'>C:\\Users\\Dumebi\\Arbibet\\api-football-ingestor\\.env</font> "
        "then either rebuild (for code-affecting settings) or just rerun "
        "(for runtime settings).",
        styles["Body"]))
    story.append(_make_table(styles,
        ["Setting", "Default", "What it controls"],
        [
            ("RATE_LIMIT_PER_MIN", "240",
             "Calls per minute (kept under the 300 plan cap as safety margin)"),
            ("RATE_LIMIT_WINDOW_SEC", "65", "Sliding window length"),
            ("DAILY_QUOTA", "75000", "Daily call cap"),
            ("THREAD_POOL_SIZE", "8", "Parallel workers"),
            ("LOOKBACK_DAYS", "2",
             "Default rolling Phase-B window (now 2 for daily runs)"),
            ("HTTP_RETRY_MAX_ATTEMPTS", "7", "Max retries per failed call"),
            ("TZ", "Europe/Berlin", "Scheduler timezone"),
            ("POSTGRES_HOST_PORT", "5434", "Host port for DBeaver"),
        ],
        col_widths=[55 * mm, 30 * mm, 85 * mm]))

    # ---- 10. Glossary ----
    story.append(Paragraph("10. Glossary", styles["H1"]))
    story.append(_make_table(styles,
        ["Term", "Plain-English meaning"],
        [
            ("Bronze layer",
             "The raw, untouched copy of API responses. Append-only"),
            ("Phase A / Phase B",
             "A = fetch leagues + their fixtures. B = for each fixture, fetch rich details + halftime stats"),
            ("Rate limit", "Max calls per minute the API allows"),
            ("Quota", "Bigger daily ceiling"),
            ("Dead letter",
             "Table of permanently-failed calls &mdash; needs human attention"),
            ("Retryable / non-retryable",
             "Temporary problems are retried; permanent ones aren't"),
            ("Retry-After", "A header telling us exactly how long to wait"),
            ("Idempotent",
             "Running twice gives the same result as once &mdash; safe to resume"),
            ("Cron", "A scheduler. \"0 2 * * *\" = every day at 02:00"),
            ("DSN", "Database connection string"),
            ("Hash dedup",
             "Fingerprint the response, skip storing if it matches last fingerprint"),
        ],
        col_widths=[55 * mm, 115 * mm],
        cmd_col=-1))  # no monospace column

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    print(f"OK: {OUTPUT}")


if __name__ == "__main__":
    build()
