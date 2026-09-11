from __future__ import annotations

from datetime import date

import pandas as pd

from components.analytics_dashboard import (
    apply_dashboard_filters as apply_component_dashboard_filters,
    build_charts,
    build_dashboard_schema,
    build_insights,
    build_kpis,
    build_quality_summary,
    format_compact_number,
)
from core.analytics_dashboard import (
    apply_dashboard_filters,
    build_dashboard_insights,
    build_dashboard_kpis,
    category_data,
    infer_dashboard_roles,
    trend_data,
)
from core.statistics import analyze_dataframe
from models.schemas import BusinessContext


def _business_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Order date": pd.date_range("2026-01-01", periods=12, freq="MS"),
            "Region": ["North", "South", "West"] * 4,
            "Customer ID": [f"C-{index:03d}" for index in range(12)],
            "Revenue": [120, 180, 240, 150, 210, 270, 165, 225, 285, 180, 240, 330],
            "Units": [2, 3, 4, 2, 4, 5, 3, 4, 6, 3, 5, 7],
        }
    )


def _dashboard_sample() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": [1001, 1002, 1003, 1004, 1005],
            "order_date": ["2024-01-01", "2024-01-10", "2024-02-01", "2024-02-20", None],
            "region": ["North", "North", "South", "West", "South"],
            "customer": ["Acme", "Blue Co", "Acme", "Delta", "Echo"],
            "revenue": [120.0, 80.0, 200.0, 50.0, 130.0],
            "currency": ["USD", "USD", "USD", "USD", "USD"],
        }
    )


def test_component_dashboard_uses_detected_business_columns_for_kpis_charts_and_insights():
    frame = _business_frame()
    context = BusinessContext(currency="USD")
    analysis = analyze_dataframe(frame, context)
    schema = build_dashboard_schema(analysis["prepared_df"], analysis, context)

    assert schema.primary_metric == "Revenue"
    assert schema.primary_dimension == "Region"
    assert schema.customer_column == "Customer ID"

    kpis = build_kpis(analysis["prepared_df"], schema)
    labels = {kpi.label for kpi in kpis}
    assert "Total records" in labels
    assert "Total Revenue" in labels
    assert "Unique Customer Id" in labels
    assert any(kpi.value.startswith("$") for kpi in kpis if kpi.label == "Total Revenue")

    charts = build_charts(analysis["prepared_df"], schema)
    assert {chart.key for chart in charts} >= {"trend", "category", "distribution", "relationship"}

    insights = build_insights(analysis["prepared_df"], analysis["prepared_df"], schema)
    assert any(insight.title == "Leading segment" for insight in insights)
    assert any(insight.title == "Period trend" for insight in insights)


def test_component_dashboard_skips_time_series_when_no_date_column_exists():
    frame = _business_frame().drop(columns="Order date")
    analysis = analyze_dataframe(frame)
    schema = build_dashboard_schema(analysis["prepared_df"], analysis)

    assert schema.date_columns == []
    assert "trend" not in {chart.key for chart in build_charts(analysis["prepared_df"], schema)}


def test_component_dashboard_quality_and_number_formatting_handle_sparse_and_empty_data():
    sparse = pd.DataFrame({"Department": ["Operations", None], "Score": [1.0, None]})
    analysis = analyze_dataframe(sparse)
    schema = build_dashboard_schema(analysis["prepared_df"], analysis)
    quality = build_quality_summary(analysis["prepared_df"], schema)

    assert quality["rows"] == 2
    assert quality["missing"] == 2
    assert quality["completeness"] == 50.0
    assert format_compact_number(1_250_000) == "1.25M"
    assert format_compact_number(0.1834, percentage=True) == "18.34%"
    assert format_compact_number(1_250_000, currency="INR") == "\u20b912.5L"


def test_component_dashboard_filters_support_mixed_date_formats_and_categories():
    frame = pd.DataFrame(
        {
            "Order Date": ["2026-01-05", "01/19/2026", "2026/03/01", "not-a-date"],
            "Region": ["West", "West", "North", "West"],
        }
    )

    filtered = apply_component_dashboard_filters(
        frame,
        "Order Date",
        (date(2026, 1, 1), date(2026, 1, 31)),
        {"Region": ["West"]},
    )

    assert len(filtered) == 2
    assert filtered["Order Date"].tolist() == ["2026-01-05", "01/19/2026"]


def test_analysis_makes_duplicate_spreadsheet_headers_safe_for_the_dashboard():
    duplicated = pd.DataFrame(
        [["North", 120.0, 90.0], ["South", 180.0, 140.0], ["West", 220.0, 175.0]],
        columns=["Region", "Sales", "Sales"],
    )

    analysis = analyze_dataframe(duplicated)

    assert analysis["prepared_df"].columns.tolist() == ["Region", "Sales", "Sales (2)"]


def test_analysis_skips_regression_when_numeric_columns_have_no_valid_pairs():
    sparse_numeric = pd.DataFrame(
        {
            "Metric A": [1.0, None] * 6,
            "Metric B": [None, 2.0] * 6,
        }
    )

    analysis = analyze_dataframe(sparse_numeric)

    assert analysis["inferential_tests"] == []


def test_dashboard_role_inference_excludes_numeric_ids_from_default_measures():
    df = _dashboard_sample()
    roles = infer_dashboard_roles(
        df,
        BusinessContext(target_variable="revenue", date_column="order_date", important_dimensions=["region"]),
    )

    assert "order_id" in roles["identifier_columns"]
    assert "order_id" not in roles["measure_candidates"]
    assert roles["default_measure"] == "revenue"
    assert roles["default_date"] == "order_date"
    assert roles["default_dimensions"][0] == "region"


def test_dashboard_prefers_totals_over_unit_price_metrics():
    df = pd.DataFrame(
        {
            "transaction_id": [10_001, 10_002, 10_003],
            "transaction_date": ["2024-04-08", "2024-04-09", "2024-04-10"],
            "category": ["Beauty", "Clothing", "Beauty"],
            "Price Per Unit": [12.5, 30.0, 18.0],
            "Quantity": [2, 1, 3],
            "Total Spent": [25.0, 30.0, 54.0],
        }
    )

    roles = infer_dashboard_roles(df)

    assert roles["default_measure"] == "Total Spent"
    assert roles["default_aggregation"] == "sum"


def test_dashboard_filters_apply_consistently_to_dates_categories_and_search():
    roles = infer_dashboard_roles(_dashboard_sample())
    frame = roles["prepared_df"]

    filtered, meta = apply_dashboard_filters(
        frame,
        date_column="order_date",
        date_range=(pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-01-31").date()),
        categorical_filters={"region": ["North"]},
        search_text="Acme",
    )

    assert len(filtered) == 1
    assert filtered.iloc[0]["revenue"] == 120.0
    assert meta["records_before"] == 5
    assert meta["records_after"] == 1
    assert len(meta["active_filters"]) == 3


def test_dashboard_kpis_and_chart_data_are_computed_from_filtered_records():
    roles = infer_dashboard_roles(_dashboard_sample())
    frame = roles["prepared_df"]
    filtered, _ = apply_dashboard_filters(frame, categorical_filters={"region": ["North"]})

    kpis = build_dashboard_kpis(
        frame,
        filtered,
        measure="revenue",
        aggregation="sum",
        date_column="order_date",
        primary_dimension="region",
    )
    trend = trend_data(filtered, "order_date", "revenue", "sum")
    categories = category_data(filtered, "region", "revenue", "sum")
    insights = build_dashboard_insights(
        filtered,
        measure="revenue",
        aggregation="sum",
        date_column="order_date",
        primary_dimension="region",
    )

    assert kpis[0]["value"] == 2
    assert kpis[1]["value"] == 200.0
    assert not trend.empty
    assert categories.iloc[0]["value"] == 200.0
    assert insights["observations"]
    assert "causation" in insights["caveats"][-1]


def test_dashboard_handles_empty_filtered_data_without_fake_metrics():
    roles = infer_dashboard_roles(_dashboard_sample())
    frame = roles["prepared_df"]
    filtered, _ = apply_dashboard_filters(frame, categorical_filters={"region": ["Unknown"]})
    insights = build_dashboard_insights(
        filtered,
        measure="revenue",
        aggregation="sum",
        date_column="order_date",
        primary_dimension="region",
    )

    assert filtered.empty
    assert insights["observations"] == ["No records match the active filters."]
    assert insights["actions"]


def test_dashboard_warns_when_monetary_measure_has_multiple_currencies():
    df = _dashboard_sample()
    df.loc[2, "currency"] = "EUR"

    roles = infer_dashboard_roles(df, BusinessContext(target_variable="revenue"))

    assert any("Multiple currency values" in warning for warning in roles["warnings"])
