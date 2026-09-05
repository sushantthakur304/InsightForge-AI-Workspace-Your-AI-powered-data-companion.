from __future__ import annotations

import html
from datetime import datetime
from io import BytesIO
from typing import Any

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from models.schemas import BusinessContext


def _paragraph(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(html.escape(str(text)), style)


def _small_table(rows: list[list[Any]], col_widths: list[float] | None = None) -> Table:
    table = Table([[html.escape(str(cell)) for cell in row] for row in rows], colWidths=col_widths)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ]
        )
    )
    return table


def build_html_report(
    profile: dict[str, Any],
    quality: dict[str, Any],
    analysis: dict[str, Any],
    insights: dict[str, Any],
    audit_log: list[dict[str, Any]],
    context: BusinessContext | None = None,
) -> str:
    context = context or BusinessContext()
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    sections = insights.get("sections", {})
    recommendations = insights.get("recommendations", [])
    scores = quality.get("scores", {})

    def list_items(items: list[str]) -> str:
        return "\n".join(f"<li>{html.escape(str(item))}</li>" for item in items)

    rec_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(rec.get('priority', '')))}</td>"
        f"<td>{html.escape(str(rec.get('recommendation', '')))}</td>"
        f"<td>{html.escape(str(rec.get('evidence', '')))}</td>"
        f"<td>{html.escape(str(rec.get('monitoring_kpi', '')))}</td>"
        "</tr>"
        for rec in recommendations
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>InsightForge AI Management Report</title>
  <style>
    body {{ font-family: Inter, Segoe UI, Arial, sans-serif; margin: 40px; color: #111827; line-height: 1.5; }}
    h1, h2 {{ color: #1e3a8a; }}
    .muted {{ color: #64748b; }}
    .score {{ display: inline-block; padding: 10px 14px; background: #dbeafe; border-left: 4px solid #2563eb; font-weight: 700; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th {{ background: #1e40af; color: white; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 8px; text-align: left; vertical-align: top; }}
    tr:nth-child(even) {{ background: #f8fafc; }}
  </style>
</head>
<body>
  <h1>{html.escape(context.company_or_project or "InsightForge AI Management Report")}</h1>
  <p class="muted">Generated {generated}</p>
  <p class="score">Data-quality score: {html.escape(str(scores.get("overall", "n/a")))}/100</p>

  <h2>Executive Summary</h2>
  <ul>{list_items(sections.get("Executive Summary", []))}</ul>

  <h2>Dataset Overview</h2>
  <table>
    <tr><th>Metric</th><th>Value</th></tr>
    <tr><td>Rows</td><td>{profile.get("row_count", 0)}</td></tr>
    <tr><td>Columns</td><td>{profile.get("column_count", 0)}</td></tr>
    <tr><td>Duplicate rows</td><td>{profile.get("exact_duplicate_rows", 0)}</td></tr>
    <tr><td>Memory usage bytes</td><td>{profile.get("memory_usage_bytes", 0)}</td></tr>
  </table>

  <h2>Data-quality Assessment</h2>
  <table>
    <tr><th>Score</th><th>Value</th></tr>
    {''.join(f'<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>' for k, v in scores.items() if k != 'explanation')}
  </table>

  <h2>Cleaning Actions</h2>
  <p>{len(audit_log)} approved cleaning actions were recorded.</p>

  <h2>Key Findings</h2>
  <ul>{list_items(sections.get("Key Findings", []))}</ul>

  <h2>Trends</h2>
  <ul>{list_items(sections.get("Trends", []))}</ul>

  <h2>Risks and Anomalies</h2>
  <ul>{list_items(sections.get("Risks and Anomalies", []))}</ul>

  <h2>Recommendations</h2>
  <table><tr><th>Priority</th><th>Recommendation</th><th>Evidence</th><th>Monitoring KPI</th></tr>{rec_rows}</table>

  <h2>Data Limitations</h2>
  <ul>{list_items(sections.get("Data Limitations", []))}</ul>

  <h2>Methodology</h2>
  <p>InsightForge AI profiles observable dataset structure, computes quality indicators, applies only user-approved cleaning actions, and generates insights from aggregate statistics. The report does not claim causation or verified real-world accuracy unless reference data is supplied.</p>

  <h2>Appendix: Definitions and Formulas</h2>
  <ul>
    <li>Completeness = non-missing cells divided by total cells.</li>
    <li>Uniqueness penalizes exact duplicate rows.</li>
    <li>IQR outliers fall below Q1 - 1.5 x IQR or above Q3 + 1.5 x IQR.</li>
    <li>Pearson correlation measures linear association from -1 to 1.</li>
  </ul>
</body>
</html>"""


def _chart_image_flowables(charts: list[dict[str, Any]], max_charts: int = 4) -> list[Any]:
    flowables: list[Any] = []
    for chart in charts[:max_charts]:
        fig = chart.get("figure")
        if fig is None:
            continue
        try:
            image_bytes = fig.to_image(format="png", width=900, height=520, scale=2)
        except Exception:
            continue
        image_buffer = BytesIO(image_bytes)
        flowables.append(Image(image_buffer, width=6.4 * inch, height=3.7 * inch))
        flowables.append(Spacer(1, 0.12 * inch))
    return flowables


def generate_pdf_report(
    profile: dict[str, Any],
    quality: dict[str, Any],
    analysis: dict[str, Any],
    insights: dict[str, Any],
    audit_log: list[dict[str, Any]],
    charts: list[dict[str, Any]] | None = None,
    context: BusinessContext | None = None,
) -> bytes:
    context = context or BusinessContext()
    charts = charts or []
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER, rightMargin=0.55 * inch, leftMargin=0.55 * inch, topMargin=0.55 * inch, bottomMargin=0.55 * inch)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CoverTitle", parent=styles["Title"], fontSize=24, leading=30, alignment=TA_CENTER, textColor=colors.HexColor("#1e3a8a")))
    styles.add(ParagraphStyle(name="SectionTitle", parent=styles["Heading2"], textColor=colors.HexColor("#1e40af"), spaceBefore=12))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontSize=9, leading=12))

    scores = quality.get("scores", {})
    sections = insights.get("sections", {})
    story: list[Any] = []
    title = context.company_or_project or "InsightForge AI Management Report"
    story.append(Spacer(1, 1.4 * inch))
    story.append(_paragraph(title, styles["CoverTitle"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(_paragraph(f"Analysis date: {datetime.now().strftime('%Y-%m-%d')}", styles["Normal"]))
    story.append(_paragraph(f"Data-quality score: {scores.get('overall', 'n/a')}/100", styles["Heading2"]))
    story.append(PageBreak())

    story.append(_paragraph("Executive Summary", styles["SectionTitle"]))
    for item in sections.get("Executive Summary", []):
        story.append(_paragraph(f"- {item}", styles["BodyText"]))

    story.append(_paragraph("Dataset Overview", styles["SectionTitle"]))
    story.append(
        _small_table(
            [
                ["Metric", "Value"],
                ["Rows", profile.get("row_count", 0)],
                ["Columns", profile.get("column_count", 0)],
                ["Exact duplicate rows", profile.get("exact_duplicate_rows", 0)],
                ["Memory usage bytes", profile.get("memory_usage_bytes", 0)],
            ],
            [2.3 * inch, 4.0 * inch],
        )
    )

    score_rows = [["Quality dimension", "Score"]]
    for key in ["overall", "completeness", "validity", "consistency", "uniqueness", "accuracy_indicators", "data_type_reliability"]:
        score_rows.append([key.replace("_", " ").title(), scores.get(key, "n/a")])
    story.append(_paragraph("Data-quality Assessment", styles["SectionTitle"]))
    story.append(_small_table(score_rows, [3.4 * inch, 2.9 * inch]))
    story.append(_paragraph(scores.get("explanation", ""), styles["BodySmall"]))

    story.append(_paragraph("Cleaning Actions", styles["SectionTitle"]))
    if audit_log:
        rows = [["Operation", "Column", "Action", "Records"]]
        for entry in audit_log[:20]:
            rows.append(
                [
                    entry.get("operation_name", ""),
                    entry.get("column_affected", ""),
                    entry.get("selected_action", ""),
                    entry.get("affected_records", 0),
                ]
            )
        story.append(_small_table(rows, [2.1 * inch, 1.5 * inch, 1.7 * inch, 1.0 * inch]))
    else:
        story.append(_paragraph("No cleaning actions were applied before this report was generated.", styles["BodyText"]))

    for section in ["Key Findings", "Trends", "Risks and Anomalies", "Opportunities", "Data Limitations", "Suggested Further Analysis"]:
        story.append(_paragraph(section, styles["SectionTitle"]))
        for item in sections.get(section, [])[:8]:
            story.append(_paragraph(f"- {item}", styles["BodyText"]))

    chart_flowables = _chart_image_flowables(charts)
    if chart_flowables:
        story.append(PageBreak())
        story.append(_paragraph("Charts", styles["SectionTitle"]))
        story.extend(chart_flowables)

    story.append(_paragraph("Prioritized Recommendations", styles["SectionTitle"]))
    recs = insights.get("recommendations", [])
    if recs:
        rows = [["Priority", "Difficulty", "Recommendation", "Evidence", "Monitoring KPI"]]
        for rec in recs[:12]:
            rows.append(
                [
                    rec.get("priority", ""),
                    rec.get("difficulty", ""),
                    rec.get("recommendation", ""),
                    rec.get("evidence", ""),
                    rec.get("monitoring_kpi", ""),
                ]
            )
        story.append(_small_table(rows, [0.7 * inch, 0.8 * inch, 1.7 * inch, 2.1 * inch, 1.1 * inch]))
    else:
        story.append(_paragraph("No recommendations passed the evidence threshold.", styles["BodyText"]))

    story.append(_paragraph("Methodology", styles["SectionTitle"]))
    story.append(
        _paragraph(
            "The analysis uses observable dataset structure, descriptive statistics, selected inferential tests when suitable, "
            "and conservative anomaly detection. AI output is grounded in computed aggregates. Statistical association does not prove causation.",
            styles["BodyText"],
        )
    )
    story.append(_paragraph("Appendix: Definitions and Formulas", styles["SectionTitle"]))
    for item in [
        "Completeness = non-missing cells divided by total cells.",
        "Uniqueness penalizes exact duplicate rows.",
        "IQR outliers fall below Q1 - 1.5 x IQR or above Q3 + 1.5 x IQR.",
        "Pearson correlation measures linear association from -1 to 1.",
    ]:
        story.append(_paragraph(f"- {item}", styles["BodySmall"]))

    doc.build(story)
    return buffer.getvalue()

