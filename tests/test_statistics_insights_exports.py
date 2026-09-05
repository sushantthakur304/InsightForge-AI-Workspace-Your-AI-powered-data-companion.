from __future__ import annotations

import pandas as pd

from core.cleaning import apply_cleaning_pipeline, recommend_cleaning_actions
from core.exporting import (
    build_excel_analysis_workbook,
    cleaning_configuration_json,
    dataframe_to_csv_bytes,
    dataframe_to_parquet_bytes,
)
from core.insights import generate_insights
from core.profiler import assess_data_quality, profile_dataframe
from core.reporting import build_html_report, generate_pdf_report
from core.statistics import analyze_dataframe
from core.validation import evaluate_validation_rules
from core.visualization import build_dashboard_figures
from models.schemas import BusinessContext, ValidationRule


def _clean_sample():
    df = pd.read_csv("sample_data/messy_sales_data.csv")
    actions = recommend_cleaning_actions(df)
    chosen = [
        action
        for action in actions
        if action["action_type"] in {"trim_whitespace", "convert_numeric_text", "parse_dates", "exact_duplicates"}
    ]
    return apply_cleaning_pipeline(df, chosen)


def test_statistical_analysis_and_ai_fallback_are_grounded():
    cleaned, audit = _clean_sample()
    context = BusinessContext(
        company_or_project="Northwind Demo",
        target_variable="Sales Amount",
        date_column="Order Date",
        important_dimensions=["Region", "Customer Segment"],
    )
    profile = profile_dataframe(cleaned)
    quality = assess_data_quality(cleaned, context)
    analysis = analyze_dataframe(cleaned, context)
    charts = build_dashboard_figures(analysis["prepared_df"], profile, quality, analysis, context)
    insights = generate_insights(profile, quality, analysis, context)

    assert not analysis["numeric_summary"].empty
    assert "Sales Amount_sum" in analysis["kpis"]
    assert charts
    assert insights["provider"] == "rule_based"
    assert insights["recommendations"]
    assert audit


def test_validation_rules_return_violations():
    df = pd.DataFrame({"quantity": [1, -1, 2], "region": ["North", "", "South"]})
    issues = evaluate_validation_rules(
        df,
        [
            ValidationRule(id="q_min", column="quantity", rule_type="min_value", value=0),
            ValidationRule(id="region_required", column="region", rule_type="required"),
        ],
    )

    assert len(issues) == 2
    assert sum(issue["affected_count"] for issue in issues) == 2


def test_exports_generate_downloadable_files():
    cleaned, audit = _clean_sample()
    context = BusinessContext(target_variable="Sales Amount", date_column="Order Date", important_dimensions=["Region"])
    profile = profile_dataframe(cleaned)
    quality = assess_data_quality(cleaned, context)
    analysis = analyze_dataframe(cleaned, context)
    insights = generate_insights(profile, quality, analysis, context)

    csv_bytes = dataframe_to_csv_bytes(cleaned)
    parquet_bytes = dataframe_to_parquet_bytes(cleaned)
    excel_bytes = build_excel_analysis_workbook(cleaned, quality, analysis, audit, insights)
    html_report = build_html_report(profile, quality, analysis, insights, audit, context)
    pdf_bytes = generate_pdf_report(profile, quality, analysis, insights, audit, [], context)
    config_bytes = cleaning_configuration_json([])

    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    assert parquet_bytes[:4] == b"PAR1"
    assert excel_bytes[:2] == b"PK"
    assert "InsightForge AI Management Report" in html_report
    assert pdf_bytes.startswith(b"%PDF")
    assert config_bytes == b"[]"
