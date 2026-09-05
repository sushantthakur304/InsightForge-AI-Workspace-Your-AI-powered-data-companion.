from __future__ import annotations

import pandas as pd
import pyarrow as pa

from core.cleaning import apply_cleaning_pipeline, cleaning_log_to_dataframe, recommend_cleaning_actions
from core.profiler import assess_data_quality, parse_numeric_series, profile_dataframe
from models.schemas import BusinessContext


def test_profile_detects_missing_duplicates_and_sensitive_columns():
    df = pd.read_csv("sample_data/messy_sales_data.csv")

    profile = profile_dataframe(df)
    quality = assess_data_quality(df, BusinessContext(target_variable="Sales Amount", date_column="Order Date"))

    assert profile["missing_counts"]["Quantity"] == 1
    assert profile["exact_duplicate_rows"] == 1
    assert "Customer Email" in profile["sensitive_columns"]
    assert quality["scores"]["overall"] < 100
    assert any(issue["id"].startswith("duplicates:exact") for issue in quality["issues"])


def test_numeric_text_parser_handles_currency_and_percentages():
    series = pd.Series(["$1,250.00", "15%", "(40)", "bad"])
    parsed = parse_numeric_series(series)

    assert parsed.iloc[0] == 1250
    assert parsed.iloc[1] == 0.15
    assert parsed.iloc[2] == -40
    assert pd.isna(parsed.iloc[3])


def test_cleaning_pipeline_applies_approved_actions_and_audit_log():
    df = pd.read_csv("sample_data/messy_sales_data.csv")
    quality = assess_data_quality(df)
    actions = recommend_cleaning_actions(df, quality)
    chosen = [
        action
        for action in actions
        if action["action_type"] in {"trim_whitespace", "convert_numeric_text", "parse_dates", "exact_duplicates"}
    ]

    cleaned, audit = apply_cleaning_pipeline(df, chosen)

    assert cleaned.duplicated().sum() == 0
    assert pd.api.types.is_numeric_dtype(cleaned["Sales Amount"])
    assert pd.api.types.is_datetime64_any_dtype(cleaned["Order Date"])
    assert audit
    assert all(entry["user_approval_status"] == "approved" for entry in audit)


def test_cleaning_log_dataframe_is_arrow_safe_with_nested_examples():
    audit = [
        {
            "timestamp": "2026-09-05T10:00:00+00:00",
            "operation_name": "Parse dates",
            "column_affected": "order_date",
            "original_issue": "Dates were stored as text.",
            "selected_action": "parse_dates",
            "affected_records": 2,
            "before_after_examples": [
                {"row_index": 0, "before": "2024-04-08", "after": pd.Timestamp("2024-04-08")},
                {"row_index": 1, "before": "not-a-date", "after": None},
            ],
            "warning_or_assumption": None,
            "user_approval_status": "approved",
        }
    ]

    frame = cleaning_log_to_dataframe(audit)

    assert isinstance(frame.loc[0, "before_after_examples"], str)
    assert "2024-04-08" in frame.loc[0, "before_after_examples"]
    pa.Table.from_pandas(frame, preserve_index=False)


def test_outlier_action_flags_records():
    df = pd.DataFrame({"sales": [10, 11, 10, 12, 11, 13, 10, 500]})
    actions = recommend_cleaning_actions(df)
    outlier = [action for action in actions if action["action_type"] == "outliers"]

    cleaned, audit = apply_cleaning_pipeline(df, outlier)

    assert "sales_outlier_flag" in cleaned.columns
    assert cleaned["sales_outlier_flag"].sum() == 1
    assert audit[0]["affected_records"] == 1


def test_group_based_imputation_uses_business_dimensions():
    df = pd.DataFrame(
        {
            "region": ["North", "North", "South", "South"],
            "sales": [10.0, None, 30.0, None],
        }
    )
    context = BusinessContext(important_dimensions=["region"])
    actions = recommend_cleaning_actions(df, context=context)
    fill_actions = [action for action in actions if action["action_type"] == "fill_missing"]

    cleaned, audit = apply_cleaning_pipeline(df, fill_actions)

    assert cleaned["sales"].tolist() == [10.0, 10.0, 30.0, 30.0]
    assert fill_actions[0]["selected_action"] == "fill_group_median"
    assert audit[0]["affected_records"] == 2


def test_key_duplicate_action_uses_selected_columns():
    df = pd.DataFrame(
        {
            "order_id": [1, 1, 2],
            "line": [1, 1, 1],
            "amount": [10, 12, 20],
        }
    )
    action = {
        "id": "key_duplicates_order_id_line",
        "operation": "Handle key-column duplicates",
        "action_type": "key_duplicates",
        "selected_action": "keep_first",
        "affected_count": 1,
        "params": {"key_columns": ["order_id", "line"]},
        "reason": "Test duplicate key handling.",
        "risk": "Repeated keys can be valid revisions.",
    }

    cleaned, audit = apply_cleaning_pipeline(df, [action])

    assert cleaned.shape[0] == 2
    assert cleaned.loc[0, "amount"] == 10
    assert audit[0]["selected_action"] == "keep_first"
