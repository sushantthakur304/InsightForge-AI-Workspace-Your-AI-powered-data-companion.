from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from core.profiler import detect_column_kind, parse_numeric_series
from core.security import make_unique_column_names
from models.schemas import AuditEntry, BusinessContext, CleaningRecommendation


ACTION_ORDER = {
    "replace_empty_with_null": 10,
    "trim_whitespace": 20,
    "standardize_capitalization": 30,
    "convert_numeric_text": 40,
    "parse_dates": 50,
    "fill_missing": 60,
    "exact_duplicates": 70,
    "key_duplicates": 71,
    "outliers": 80,
    "clean_column_names": 90,
}

AUDIT_LOG_COLUMNS = [
    "timestamp",
    "operation_name",
    "column_affected",
    "original_issue",
    "selected_action",
    "affected_records",
    "before_after_examples",
    "warning_or_assumption",
    "user_approval_status",
]


def _action_id(action_type: str, column: str | None = None) -> str:
    raw = f"{action_type}:{column or 'all'}"
    return "".join(ch if ch.isalnum() else "_" for ch in raw).strip("_").lower()


def _example_records(before: pd.DataFrame, after: pd.DataFrame, column: str | None, rows: list[int], limit: int = 5) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for row in rows[:limit]:
        before_value = None
        after_value = None
        if row in before.index:
            before_value = before.loc[row].to_dict() if column is None else before.loc[row].get(column)
        if row in after.index:
            after_value = after.loc[row].to_dict() if column is None else after.loc[row].get(column)
        examples.append({"row_index": int(row), "before": _json_safe(before_value), "after": _json_safe(after_value)})
    return examples


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if pd.isna(value) if not isinstance(value, (list, tuple, dict, np.ndarray)) else False:
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


def _audit_display_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(_json_safe(value), default=str)
    return _json_safe(value)


def recommend_cleaning_actions(
    df: pd.DataFrame,
    quality: dict[str, Any] | None = None,
    context: BusinessContext | None = None,
) -> list[dict[str, Any]]:
    """Generate conservative, user-approvable cleaning recommendations."""

    recommendations: list[CleaningRecommendation] = []
    context = context or BusinessContext()

    dirty_columns = [column for column in df.columns if str(column) != str(column).strip() or " " in str(column)]
    if dirty_columns:
        recommendations.append(
            CleaningRecommendation(
                id=_action_id("clean_column_names"),
                operation="Clean column names",
                action_type="clean_column_names",
                selected_action="clean_names",
                options=["clean_names", "leave_unchanged"],
                reason="Consistent machine-readable column names make analysis and exports easier to audit.",
                risk="Downstream tools may expect the original labels, so the mapping is recorded in the audit log.",
                affected_count=len(dirty_columns),
                params={"columns": dirty_columns},
                enabled_by_default=False,
            )
        )

    for column in df.select_dtypes(include=["object", "string"]).columns:
        text = df[column].astype("string")
        empty_mask = text.str.strip().eq("")
        if empty_mask.any():
            recommendations.append(
                CleaningRecommendation(
                    id=_action_id("replace_empty_with_null", column),
                    operation="Replace empty strings with nulls",
                    action_type="replace_empty_with_null",
                    column=column,
                    selected_action="replace_empty_with_null",
                    options=["replace_empty_with_null", "leave_unchanged"],
                    reason="Blank strings behave differently from true missing values in profiling and statistics.",
                    risk="Blank labels that intentionally mean 'none' will become missing values.",
                    affected_count=int(empty_mask.sum()),
                )
            )

        whitespace_mask = text.str.match(r"^\s+|\s+$", na=False)
        if whitespace_mask.any():
            recommendations.append(
                CleaningRecommendation(
                    id=_action_id("trim_whitespace", column),
                    operation="Trim whitespace",
                    action_type="trim_whitespace",
                    column=column,
                    selected_action="trim",
                    options=["trim", "leave_unchanged"],
                    reason="Leading and trailing spaces can create duplicate categories.",
                    risk="Meaningful leading/trailing spaces in free text would be removed.",
                    affected_count=int(whitespace_mask.sum()),
                )
            )

        stripped = text.dropna().str.strip()
        variants: dict[str, set[str]] = {}
        for value in stripped:
            variants.setdefault(str(value).lower(), set()).add(str(value))
        inconsistent = {key: values for key, values in variants.items() if len(values) > 1}
        if inconsistent and stripped.nunique() <= 100:
            affected = text.str.strip().str.lower().isin(inconsistent.keys()).sum()
            recommendations.append(
                CleaningRecommendation(
                    id=_action_id("standardize_capitalization", column),
                    operation="Standardize capitalization",
                    action_type="standardize_capitalization",
                    column=column,
                    selected_action="title_case",
                    options=["title_case", "upper_case", "lower_case", "leave_unchanged"],
                    reason="Category labels that differ only by capitalization should usually be grouped.",
                    risk="Acronyms or brand names may need custom mapping after title casing.",
                    affected_count=int(affected),
                    params={"examples": {key: sorted(values) for key, values in list(inconsistent.items())[:5]}},
                )
            )

    for column in df.columns:
        kind = detect_column_kind(df[column], str(column))
        if kind == "numeric_text":
            parsed = parse_numeric_series(df[column])
            affected = int(parsed.notna().sum())
            recommendations.append(
                CleaningRecommendation(
                    id=_action_id("convert_numeric_text", column),
                    operation="Convert numeric text",
                    action_type="convert_numeric_text",
                    column=column,
                    selected_action="convert_numeric_text",
                    options=["convert_numeric_text", "leave_unchanged"],
                    reason="Values are stored as text but mostly parse as numbers, including currency or percentage strings.",
                    risk="Invalid tokens become missing values and must be reviewed.",
                    affected_count=affected,
                )
            )
        elif kind == "date_text":
            parsed = pd.to_datetime(df[column], errors="coerce", format="mixed")
            recommendations.append(
                CleaningRecommendation(
                    id=_action_id("parse_dates", column),
                    operation="Parse dates",
                    action_type="parse_dates",
                    column=column,
                    selected_action="parse_dates",
                    options=["parse_dates", "leave_unchanged"],
                    reason="The column appears to contain dates stored as text.",
                    risk="Ambiguous dates may parse incorrectly when day and month order is unclear.",
                    affected_count=int(parsed.notna().sum()),
                )
            )

    for column in df.columns:
        missing_count = int(df[column].isna().sum())
        if missing_count == 0:
            continue
        kind = detect_column_kind(df[column], str(column))
        group_columns = [
            dimension
            for dimension in context.important_dimensions
            if dimension in df.columns and dimension != column
        ]
        params: dict[str, Any] = {}
        if kind in {"numeric", "numeric_text"}:
            if group_columns:
                selected = "fill_group_median"
                params["group_column"] = group_columns[0]
                reason = (
                    f"Median imputation within {group_columns[0]} preserves segment differences "
                    "better than a single global fill."
                )
            else:
                selected = "fill_median"
                reason = "Median imputation is robust against skew and outliers for numerical fields."
        elif kind in {"categorical", "boolean"}:
            if group_columns:
                selected = "fill_group_mode"
                params["group_column"] = group_columns[0]
                reason = f"Mode imputation within {group_columns[0]} uses the most common segment-specific value."
            else:
                selected = "fill_mode"
                reason = "Mode imputation preserves the most common category without inventing a new label."
        elif kind in {"date", "date_text"}:
            selected = "leave_unchanged"
            reason = "Missing dates often need business-specific treatment."
        else:
            selected = "leave_unchanged"
            reason = "Free-text missing values are safest to leave unchanged unless business rules are known."
        recommendations.append(
            CleaningRecommendation(
                id=_action_id("fill_missing", column),
                operation="Handle missing values",
                action_type="fill_missing",
                column=column,
                selected_action=selected,
                options=[
                    "leave_unchanged",
                    "remove_rows",
                    "remove_column",
                    "fill_mean",
                    "fill_median",
                    "fill_mode",
                    "fill_group_median",
                    "fill_group_mode",
                    "forward_fill",
                    "backward_fill",
                    "interpolate",
                    "fill_custom_value",
                ],
                reason=reason,
                risk="Imputation can bias distributions. The audit log records the selected method.",
                affected_count=missing_count,
                params=params,
                enabled_by_default=selected != "leave_unchanged",
            )
        )

    duplicate_count = int(df.duplicated().sum())
    if duplicate_count:
        recommendations.append(
            CleaningRecommendation(
                id=_action_id("exact_duplicates"),
                operation="Handle exact duplicates",
                action_type="exact_duplicates",
                selected_action="keep_first",
                options=["keep_first", "keep_last", "remove_all_duplicates", "review_only", "leave_unchanged"],
                reason="Exact duplicate rows usually inflate counts and totals.",
                risk="Repeated records can be valid transactions; confirm before deletion.",
                affected_count=duplicate_count,
            )
        )

    for column in df.select_dtypes(include=[np.number]).columns:
        series = pd.to_numeric(df[column], errors="coerce")
        clean = series.dropna()
        if len(clean) < 8:
            continue
        q1, q3 = clean.quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr <= 0:
            continue
        mask = (series < q1 - 1.5 * iqr) | (series > q3 + 1.5 * iqr)
        if mask.any():
            recommendations.append(
                CleaningRecommendation(
                    id=_action_id("outliers", column),
                    operation="Handle outliers",
                    action_type="outliers",
                    column=column,
                    selected_action="flag_outliers",
                    options=["keep_outliers", "flag_outliers", "filter_from_analysis", "cap_iqr", "remove_outliers"],
                    reason="Outliers can strongly influence averages and correlations.",
                    risk="Outliers may be valid high-value business events, so they are flagged by default.",
                    affected_count=int(mask.sum()),
                    params={"lower": float(q1 - 1.5 * iqr), "upper": float(q3 + 1.5 * iqr)},
                )
            )

    return [item.model_dump() for item in recommendations]


def _apply_single_action(frame: pd.DataFrame, action: dict[str, Any]) -> tuple[pd.DataFrame, AuditEntry]:
    before = frame.copy()
    after = frame.copy()
    action_type = action["action_type"]
    selected = action.get("selected_action", "leave_unchanged")
    column = action.get("column")
    affected_rows: list[int] = []
    affected_count = int(action.get("affected_count", 0))
    warning = action.get("risk")

    if selected in {"leave_unchanged", "review_only", "keep_outliers"}:
        return after, AuditEntry(
            operation_name=action.get("operation", action_type),
            column_affected=column,
            original_issue=action.get("reason", ""),
            selected_action=selected,
            affected_records=0,
            before_after_examples=[],
            warning_or_assumption="User chose to leave records unchanged.",
            user_approval_status="approved",
        )

    if column is not None and column not in after.columns and action_type != "clean_column_names":
        return after, AuditEntry(
            operation_name=action.get("operation", action_type),
            column_affected=column,
            original_issue=action.get("reason", ""),
            selected_action=selected,
            affected_records=0,
            before_after_examples=[],
            warning_or_assumption=f"Column '{column}' was not present when this action ran.",
            user_approval_status="approved",
        )

    if action_type == "replace_empty_with_null" and column:
        mask = after[column].astype("string").str.strip().eq("")
        affected_rows = [int(i) for i in after[mask].index.tolist()]
        after.loc[mask, column] = np.nan
        affected_count = int(mask.sum())

    elif action_type == "trim_whitespace" and column:
        mask = after[column].astype("string").str.match(r"^\s+|\s+$", na=False)
        affected_rows = [int(i) for i in after[mask].index.tolist()]
        after[column] = after[column].map(lambda value: value.strip() if isinstance(value, str) else value)
        affected_count = int(mask.sum())

    elif action_type == "standardize_capitalization" and column:
        mask = after[column].notna()
        affected_rows = [int(i) for i in after[mask].index.tolist()]
        if selected == "title_case":
            after[column] = after[column].map(lambda value: value.strip().title() if isinstance(value, str) else value)
        elif selected == "upper_case":
            after[column] = after[column].map(lambda value: value.strip().upper() if isinstance(value, str) else value)
        elif selected == "lower_case":
            after[column] = after[column].map(lambda value: value.strip().lower() if isinstance(value, str) else value)
        affected_count = int(mask.sum())

    elif action_type == "convert_numeric_text" and column:
        mask = after[column].notna()
        affected_rows = [int(i) for i in after[mask].index.tolist()]
        after[column] = parse_numeric_series(after[column])
        affected_count = int(mask.sum())

    elif action_type == "parse_dates" and column:
        mask = after[column].notna()
        affected_rows = [int(i) for i in after[mask].index.tolist()]
        after[column] = pd.to_datetime(after[column], errors="coerce", format="mixed")
        affected_count = int(mask.sum())

    elif action_type == "fill_missing" and column:
        mask = after[column].isna()
        affected_rows = [int(i) for i in after[mask].index.tolist()]
        affected_count = int(mask.sum())
        if selected == "remove_rows":
            after = after.loc[~mask].copy()
        elif selected == "remove_column":
            after = after.drop(columns=[column])
        elif selected == "fill_mean":
            after[column] = after[column].fillna(pd.to_numeric(after[column], errors="coerce").mean())
        elif selected == "fill_median":
            after[column] = after[column].fillna(pd.to_numeric(after[column], errors="coerce").median())
        elif selected == "fill_mode":
            mode = after[column].mode(dropna=True)
            after[column] = after[column].fillna(mode.iloc[0] if not mode.empty else "Unknown")
        elif selected == "forward_fill":
            after[column] = after[column].ffill()
        elif selected == "backward_fill":
            after[column] = after[column].bfill()
        elif selected == "interpolate":
            after[column] = pd.to_numeric(after[column], errors="coerce").interpolate()
        elif selected == "fill_custom_value":
            after[column] = after[column].fillna(action.get("params", {}).get("custom_value", "Unknown"))
        elif selected in {"fill_group_median", "fill_group_mode"}:
            group_column = action.get("params", {}).get("group_column")
            if group_column and group_column in after.columns:
                if selected == "fill_group_median":
                    numeric = pd.to_numeric(after[column], errors="coerce")
                    group_values = numeric.groupby(after[group_column]).transform("median")
                    after[column] = numeric.fillna(group_values).fillna(numeric.median())
                else:
                    def group_mode(values: pd.Series) -> Any:
                        mode = values.mode(dropna=True)
                        return mode.iloc[0] if not mode.empty else np.nan

                    group_values = after.groupby(group_column)[column].transform(group_mode)
                    global_mode = after[column].mode(dropna=True)
                    fallback = global_mode.iloc[0] if not global_mode.empty else "Unknown"
                    after[column] = after[column].fillna(group_values).fillna(fallback)
            else:
                warning = f"Group column '{group_column}' was unavailable; no group-based fill was applied."

    elif action_type in {"exact_duplicates", "key_duplicates"}:
        key_columns = action.get("params", {}).get("key_columns") if action_type == "key_duplicates" else None
        if key_columns:
            duplicate_basis = after[key_columns].astype("string").apply(lambda series: series.str.strip().str.lower())
            duplicate_mask = duplicate_basis.duplicated(keep=False)
            earlier_duplicate_count = int(duplicate_basis.duplicated().sum())
        else:
            duplicate_mask = after.duplicated(keep=False)
            earlier_duplicate_count = int(before.duplicated().sum())
        affected_rows = [int(i) for i in after[duplicate_mask].index.tolist()]
        if selected == "keep_first":
            after = after.drop_duplicates(subset=key_columns, keep="first")
            affected_count = earlier_duplicate_count
        elif selected == "keep_last":
            after = after.drop_duplicates(subset=key_columns, keep="last")
            affected_count = earlier_duplicate_count
        elif selected == "remove_all_duplicates":
            after = after.drop_duplicates(subset=key_columns, keep=False)
            affected_count = int(duplicate_mask.sum())

    elif action_type == "outliers" and column:
        numeric = pd.to_numeric(after[column], errors="coerce")
        lower = action.get("params", {}).get("lower")
        upper = action.get("params", {}).get("upper")
        if lower is None or upper is None:
            clean = numeric.dropna()
            q1, q3 = clean.quantile([0.25, 0.75])
            iqr = q3 - q1
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        mask = numeric.notna() & ((numeric < float(lower)) | (numeric > float(upper)))
        affected_rows = [int(i) for i in after[mask].index.tolist()]
        affected_count = int(mask.sum())
        if selected == "flag_outliers":
            after[f"{column}_outlier_flag"] = mask
        elif selected == "filter_from_analysis":
            after[f"{column}_excluded_from_analysis"] = mask
        elif selected == "cap_iqr":
            after[column] = numeric.clip(lower=float(lower), upper=float(upper))
        elif selected == "remove_outliers":
            after = after.loc[~mask].copy()

    elif action_type == "clean_column_names":
        original_columns = list(after.columns)
        after.columns = make_unique_column_names(original_columns)
        affected_rows = []
        affected_count = sum(a != b for a, b in zip(original_columns, after.columns))

    examples = _example_records(before, after, column, affected_rows)
    if action_type == "clean_column_names":
        examples = [{"before": list(before.columns), "after": list(after.columns)}]

    return after, AuditEntry(
        operation_name=action.get("operation", action_type),
        column_affected=column,
        original_issue=action.get("reason", ""),
        selected_action=selected,
        affected_records=affected_count,
        before_after_examples=examples,
        warning_or_assumption=warning,
        user_approval_status="approved",
    )


def apply_cleaning_pipeline(
    original_df: pd.DataFrame,
    actions: list[dict[str, Any]],
    approved_action_ids: set[str] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    approved_action_ids = approved_action_ids or {action["id"] for action in actions}
    runnable = [
        action for action in actions
        if action.get("id") in approved_action_ids and action.get("selected_action") not in {"leave_unchanged", "review_only"}
    ]
    runnable.sort(key=lambda item: ACTION_ORDER.get(item.get("action_type", ""), 100))

    frame = original_df.copy()
    audit_entries: list[dict[str, Any]] = []
    for action in runnable:
        frame, audit = _apply_single_action(frame, action)
        audit_entries.append(audit.model_dump())
    return frame.reset_index(drop=True), audit_entries


def cleaning_actions_to_json(actions: list[dict[str, Any]]) -> str:
    return json.dumps(actions, indent=2, default=str)


def cleaning_log_to_dataframe(audit_log: list[dict[str, Any]]) -> pd.DataFrame:
    if not audit_log:
        return pd.DataFrame(
            {
                column: pd.Series(dtype="int64" if column == "affected_records" else "string")
                for column in AUDIT_LOG_COLUMNS
            }
        )

    frame = pd.DataFrame(audit_log).reindex(columns=AUDIT_LOG_COLUMNS)
    frame["affected_records"] = pd.to_numeric(frame["affected_records"], errors="coerce").fillna(0).astype("int64")

    for column in frame.columns.difference(["affected_records"]):
        frame[column] = frame[column].map(_audit_display_value).astype("string")

    return frame
