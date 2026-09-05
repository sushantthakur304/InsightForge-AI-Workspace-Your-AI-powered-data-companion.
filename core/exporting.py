from __future__ import annotations

import json
import zipfile
from io import BytesIO
from typing import Any

import pandas as pd

from core.cleaning import cleaning_log_to_dataframe
from core.security import protect_dataframe_for_excel


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def dataframe_to_parquet_bytes(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    df.to_parquet(buffer, index=False)
    return buffer.getvalue()


def _quality_dataframe(quality: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for name, value in quality.get("scores", {}).items():
        if name != "explanation":
            rows.append({"section": "score", "metric": name, "value": value})
    for issue in quality.get("issues", []):
        rows.append(
            {
                "section": "issue",
                "metric": issue.get("title"),
                "value": issue.get("affected_count"),
                "category": issue.get("category"),
                "severity": issue.get("severity"),
                "column": issue.get("column"),
                "description": issue.get("description"),
            }
        )
    return pd.DataFrame(rows)


def _statistical_summary_dataframe(analysis: dict[str, Any]) -> pd.DataFrame:
    summary = analysis.get("numeric_summary")
    if isinstance(summary, pd.DataFrame) and not summary.empty:
        return summary
    return pd.DataFrame([analysis.get("kpis", {})])


def _insights_dataframe(insights: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for section, items in insights.get("sections", {}).items():
        for item in items:
            rows.append({"section": section, "insight": item})
    return pd.DataFrame(rows)


def _recommendations_dataframe(insights: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(insights.get("recommendations", []))


def _safe_sheet_name(name: str) -> str:
    invalid_chars = set("[]:*?/\\")
    safe = "".join(ch if ch not in invalid_chars else "_" for ch in str(name))[:31]
    return safe or "Sheet"


def _autofit(writer: pd.ExcelWriter, sheet_name: str, df: pd.DataFrame) -> None:
    worksheet = writer.sheets[sheet_name]
    workbook = writer.book
    header_format = workbook.add_format(
        {"bold": True, "bg_color": "#1e40af", "font_color": "white", "border": 1, "valign": "top"}
    )
    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, header_format)
        max_width = max([len(str(value))] + [len(str(x)) for x in df[value].head(200).fillna("").tolist()])
        worksheet.set_column(col_num, col_num, min(max(max_width + 2, 10), 42))
    if not df.empty:
        worksheet.autofilter(0, 0, len(df), max(len(df.columns) - 1, 0))
        worksheet.freeze_panes(1, 0)


def build_excel_analysis_workbook(
    cleaned_df: pd.DataFrame,
    quality: dict[str, Any],
    analysis: dict[str, Any],
    audit_log: list[dict[str, Any]],
    insights: dict[str, Any],
) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter", datetime_format="yyyy-mm-dd", date_format="yyyy-mm-dd") as writer:
        sheets = {
            "Cleaned Data": protect_dataframe_for_excel(cleaned_df),
            "Data Quality": _quality_dataframe(quality),
            "Statistical Summary": _statistical_summary_dataframe(analysis),
            "Cleaning Log": cleaning_log_to_dataframe(audit_log),
            "Key Insights": _insights_dataframe(insights),
            "Recommendations": _recommendations_dataframe(insights),
        }
        for sheet_name, frame in sheets.items():
            safe_name = _safe_sheet_name(sheet_name)
            frame.to_excel(writer, sheet_name=safe_name, index=False)
            _autofit(writer, safe_name, frame)

        workbook = writer.book
        score_sheet = writer.sheets["Data Quality"]
        score_format = workbook.add_format({"bg_color": "#dbeafe", "font_color": "#1e3a8a"})
        score_sheet.conditional_format("C2:C20", {"type": "cell", "criteria": "<", "value": 80, "format": score_format})
    return buffer.getvalue()


def quality_report_json(quality: dict[str, Any]) -> bytes:
    return json.dumps(quality, indent=2, default=str).encode("utf-8")


def cleaning_configuration_json(actions: list[dict[str, Any]]) -> bytes:
    return json.dumps(actions, indent=2, default=str).encode("utf-8")


def audit_log_json(audit_log: list[dict[str, Any]]) -> bytes:
    return json.dumps(audit_log, indent=2, default=str).encode("utf-8")


def chart_images_zip(charts: list[dict[str, Any]]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, chart in enumerate(charts, start=1):
            fig = chart.get("figure")
            title = chart.get("title", f"chart_{index}")
            safe_title = "".join(ch if ch.isalnum() else "_" for ch in title).strip("_").lower()[:80]
            if fig is None:
                continue
            image = fig.to_image(format="png", scale=2)
            archive.writestr(f"{index:02d}_{safe_title}.png", image)
    return buffer.getvalue()
