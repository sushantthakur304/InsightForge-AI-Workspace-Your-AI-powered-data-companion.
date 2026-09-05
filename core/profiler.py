from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from core.security import detect_sensitive_columns
from models.schemas import BusinessContext, DataIssue, QualityScores


POSITIVE_FIELD_HINTS = re.compile(
    r"amount|sales|revenue|price|cost|quantity|qty|units|count|age|salary|income|balance|total",
    re.I,
)
DATE_FIELD_HINTS = re.compile(r"date|time|month|year|period|created|updated", re.I)
IDENTIFIER_HINTS = re.compile(r"(^id$|[_ -]id$|id[_ -]|uuid|guid|key|code|number|no$|sku)", re.I)


def parse_numeric_series(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    is_percent = text.str.endswith("%", na=False)
    cleaned = (
        text.str.replace(r"[\$,£€₹,]", "", regex=True)
        .str.replace(r"\(([^)]+)\)", r"-\1", regex=True)
        .str.replace("%", "", regex=False)
        .str.replace(r"\s+", "", regex=True)
    )
    numeric = pd.to_numeric(cleaned, errors="coerce").astype("float64")
    percent_mask = is_percent & numeric.notna()
    numeric.loc[percent_mask] = numeric.loc[percent_mask] / 100.0
    return numeric


def detect_column_kind(series: pd.Series, column_name: str | None = None) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return "unknown"

    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"

    as_text = non_null.astype(str).str.strip()
    lowered = as_text.str.lower()
    boolean_tokens = {"true", "false", "yes", "no", "y", "n", "0", "1"}
    if lowered.isin(boolean_tokens).mean() >= 0.9 and lowered.nunique() <= 4:
        return "boolean"

    numeric = parse_numeric_series(non_null)
    numeric_ratio = numeric.notna().mean()
    if numeric_ratio >= 0.85:
        return "numeric_text"

    date_ratio = pd.to_datetime(non_null, errors="coerce", format="mixed").notna().mean()
    if date_ratio >= 0.8 or (column_name and DATE_FIELD_HINTS.search(column_name) and date_ratio >= 0.5):
        return "date_text"

    unique_ratio = non_null.nunique(dropna=True) / max(len(non_null), 1)
    if non_null.nunique(dropna=True) <= 30 or unique_ratio <= 0.25:
        return "categorical"
    return "text"


def classify_columns(df: pd.DataFrame) -> dict[str, list[str]]:
    groups = {
        "numerical": [],
        "categorical": [],
        "date": [],
        "text": [],
        "boolean": [],
        "numeric_text": [],
        "unknown": [],
    }
    for column in df.columns:
        kind = detect_column_kind(df[column], str(column))
        if kind == "numeric":
            groups["numerical"].append(column)
        elif kind == "numeric_text":
            groups["numeric_text"].append(column)
        elif kind in {"date", "date_text"}:
            groups["date"].append(column)
        elif kind == "boolean":
            groups["boolean"].append(column)
        elif kind == "categorical":
            groups["categorical"].append(column)
        elif kind == "text":
            groups["text"].append(column)
        else:
            groups["unknown"].append(column)
    return groups


def potential_identifier_columns(df: pd.DataFrame) -> list[str]:
    identifiers: list[str] = []
    row_count = max(len(df), 1)
    for column in df.columns:
        unique_ratio = df[column].nunique(dropna=True) / row_count
        if IDENTIFIER_HINTS.search(str(column)) or (unique_ratio >= 0.95 and not pd.api.types.is_float_dtype(df[column])):
            identifiers.append(column)
    return identifiers


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Build a profile for upload preview and downstream quality checks."""

    missing_counts = df.isna().sum()
    missing_percentages = (missing_counts / max(len(df), 1) * 100).round(2)
    unique_counts = df.nunique(dropna=True)
    column_types = classify_columns(df)
    sensitive_columns = detect_sensitive_columns(df)

    column_profiles = []
    for column in df.columns:
        series = df[column]
        column_profiles.append(
            {
                "column": column,
                "pandas_dtype": str(series.dtype),
                "detected_type": detect_column_kind(series, str(column)),
                "missing_count": int(missing_counts[column]),
                "missing_pct": float(missing_percentages[column]),
                "unique_values": int(unique_counts[column]),
                "memory_bytes": int(series.memory_usage(deep=True)),
                "sample_values": [str(value) for value in series.dropna().head(3).tolist()],
            }
        )

    return {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": list(df.columns),
        "column_profiles": column_profiles,
        "column_types": column_types,
        "missing_counts": missing_counts.astype(int).to_dict(),
        "missing_percentages": missing_percentages.astype(float).to_dict(),
        "exact_duplicate_rows": int(df.duplicated().sum()),
        "unique_values": unique_counts.astype(int).to_dict(),
        "potential_identifier_columns": potential_identifier_columns(df),
        "memory_usage_bytes": int(df.memory_usage(deep=True).sum()),
        "sensitive_columns": sensitive_columns,
    }


def _row_indices(mask: pd.Series | np.ndarray, limit: int = 100) -> list[int]:
    if isinstance(mask, np.ndarray):
        mask = pd.Series(mask)
    return [int(i) for i in mask[mask].index[:limit].tolist()]


def _issue(
    issue_id: str,
    category: str,
    severity: str,
    title: str,
    description: str,
    column: str | None = None,
    affected_count: int = 0,
    affected_rows: list[int] | None = None,
    suggested_action: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> DataIssue:
    return DataIssue(
        id=issue_id,
        category=category,
        severity=severity,  # type: ignore[arg-type]
        title=title,
        description=description,
        column=column,
        affected_count=int(affected_count),
        affected_rows=affected_rows or [],
        suggested_action=suggested_action,
        evidence=evidence or {},
    )


def detect_quality_issues(df: pd.DataFrame, context: BusinessContext | None = None) -> list[DataIssue]:
    issues: list[DataIssue] = []
    context = context or BusinessContext()
    row_count = len(df)

    missing = df.isna().sum()
    for column, count in missing.items():
        if count:
            pct = count / max(row_count, 1) * 100
            issues.append(
                _issue(
                    f"missing:{column}",
                    "completeness",
                    "high" if pct >= 25 else "medium" if pct >= 5 else "low",
                    f"Missing values in {column}",
                    f"{count} rows ({pct:.1f}%) are missing a value.",
                    column=column,
                    affected_count=int(count),
                    affected_rows=_row_indices(df[column].isna()),
                    suggested_action="Review imputation or removal options before cleaning.",
                    evidence={"missing_pct": round(pct, 2)},
                )
            )

    duplicate_mask = df.duplicated(keep=False)
    duplicate_count = int(df.duplicated().sum())
    if duplicate_count:
        issues.append(
            _issue(
                "duplicates:exact",
                "uniqueness",
                "medium" if duplicate_count < max(row_count * 0.05, 1) else "high",
                "Exact duplicate rows",
                f"{duplicate_count} rows duplicate an earlier record exactly.",
                affected_count=duplicate_count,
                affected_rows=_row_indices(duplicate_mask),
                suggested_action="Remove exact duplicates after confirming repeated rows are not valid transactions.",
            )
        )

    normalized = df.astype(str).apply(lambda col: col.str.strip().str.lower())
    possible_duplicate_mask = normalized.duplicated(keep=False) & ~duplicate_mask
    possible_count = int(normalized.duplicated().sum() - duplicate_count)
    if possible_count > 0:
        issues.append(
            _issue(
                "duplicates:possible_normalized",
                "uniqueness",
                "low",
                "Possible duplicate records",
                "Some records match after trimming whitespace and ignoring capitalization.",
                affected_count=possible_count,
                affected_rows=_row_indices(possible_duplicate_mask),
                suggested_action="Review possible matches manually before deletion.",
            )
        )

    for column in df.select_dtypes(include=["object", "string"]).columns:
        text = df[column].dropna().astype(str)
        if text.empty:
            continue

        empty_mask = df[column].astype("string").str.strip().eq("")
        if empty_mask.any():
            issues.append(
                _issue(
                    f"empty_strings:{column}",
                    "completeness",
                    "medium",
                    f"Empty strings in {column}",
                    "Blank text values should be converted to nulls before analysis.",
                    column=column,
                    affected_count=int(empty_mask.sum()),
                    affected_rows=_row_indices(empty_mask),
                    suggested_action="Replace empty strings with null values.",
                )
            )

        whitespace_mask = df[column].astype("string").str.match(r"^\s+|\s+$", na=False)
        if whitespace_mask.any():
            issues.append(
                _issue(
                    f"whitespace:{column}",
                    "consistency",
                    "low",
                    f"Leading or trailing spaces in {column}",
                    "Whitespace can split categories that should be identical.",
                    column=column,
                    affected_count=int(whitespace_mask.sum()),
                    affected_rows=_row_indices(whitespace_mask),
                    suggested_action="Trim leading and trailing whitespace.",
                )
            )

        suspicious_mask = df[column].astype("string").str.contains(r"[\x00-\x08\x0B-\x1F]", regex=True, na=False)
        if suspicious_mask.any():
            issues.append(
                _issue(
                    f"suspicious_chars:{column}",
                    "validity",
                    "medium",
                    f"Suspicious characters in {column}",
                    "Control characters may indicate copy-paste or encoding issues.",
                    column=column,
                    affected_count=int(suspicious_mask.sum()),
                    affected_rows=_row_indices(suspicious_mask),
                    suggested_action="Inspect and remove suspicious characters if they are not meaningful.",
                )
            )

        stripped = text.str.strip()
        lowered = stripped.str.lower()
        variants = {}
        for value in stripped:
            key = value.lower()
            variants.setdefault(key, set()).add(value)
        inconsistent_groups = {key: sorted(values) for key, values in variants.items() if len(values) > 1}
        if inconsistent_groups and lowered.nunique() <= 100:
            affected = df[column].astype("string").str.strip().str.lower().isin(inconsistent_groups.keys())
            issues.append(
                _issue(
                    f"capitalization:{column}",
                    "consistency",
                    "low",
                    f"Inconsistent capitalization in {column}",
                    "The same category appears with different capitalization.",
                    column=column,
                    affected_count=int(affected.sum()),
                    affected_rows=_row_indices(affected),
                    suggested_action="Standardize category capitalization.",
                    evidence={"examples": dict(list(inconsistent_groups.items())[:5])},
                )
            )

        numeric = parse_numeric_series(df[column])
        numeric_ratio = numeric.notna().sum() / max(df[column].notna().sum(), 1)
        if 0.3 <= numeric_ratio < 0.95:
            invalid_mask = df[column].notna() & numeric.isna()
            issues.append(
                _issue(
                    f"mixed_numeric:{column}",
                    "validity",
                    "medium",
                    f"Mixed numeric formats in {column}",
                    "Some values look numeric while others cannot be parsed as numbers.",
                    column=column,
                    affected_count=int(invalid_mask.sum()),
                    affected_rows=_row_indices(invalid_mask),
                    suggested_action="Review units, symbols, and invalid tokens before conversion.",
                    evidence={"numeric_parse_ratio": round(numeric_ratio, 3)},
                )
            )

        date_like = DATE_FIELD_HINTS.search(str(column)) is not None
        parsed_dates = pd.to_datetime(df[column], errors="coerce", format="mixed")
        date_ratio = parsed_dates.notna().sum() / max(df[column].notna().sum(), 1)
        if date_like and 0 < date_ratio < 0.95:
            issues.append(
                _issue(
                    f"invalid_dates:{column}",
                    "validity",
                    "medium",
                    f"Inconsistent or invalid dates in {column}",
                    "The column name suggests dates, but not all non-empty values parse as dates.",
                    column=column,
                    affected_count=int((df[column].notna() & parsed_dates.isna()).sum()),
                    affected_rows=_row_indices(df[column].notna() & parsed_dates.isna()),
                    suggested_action="Parse dates and review invalid records.",
                    evidence={"date_parse_ratio": round(date_ratio, 3)},
                )
            )

        unit_pattern = df[column].astype("string").str.extract(r"([a-zA-Z%$£€₹]+)\s*$", expand=False)
        unit_counts = unit_pattern.dropna().str.lower().value_counts()
        if len(unit_counts) > 1 and unit_counts.sum() >= 5:
            issues.append(
                _issue(
                    f"mixed_units:{column}",
                    "consistency",
                    "medium",
                    f"Mixed units or suffixes in {column}",
                    "Values appear to use multiple units, symbols, or suffixes.",
                    column=column,
                    affected_count=int(unit_counts.sum()),
                    affected_rows=_row_indices(unit_pattern.notna()),
                    suggested_action="Standardize units before comparing values.",
                    evidence={"unit_examples": unit_counts.head(5).to_dict()},
                )
            )

    for column in df.columns:
        if df[column].nunique(dropna=True) <= 1 and row_count > 1:
            issues.append(
                _issue(
                    f"constant:{column}",
                    "validity",
                    "low",
                    f"Constant column {column}",
                    "This column has one distinct non-null value and may not help analysis.",
                    column=column,
                    affected_count=row_count,
                    affected_rows=list(range(min(row_count, 100))),
                    suggested_action="Consider excluding this column from analysis.",
                )
            )

        unique_ratio = df[column].nunique(dropna=True) / max(row_count, 1)
        if unique_ratio >= 0.9 and row_count >= 20:
            issues.append(
                _issue(
                    f"high_cardinality:{column}",
                    "validity",
                    "low",
                    f"Extremely high cardinality in {column}",
                    "This column has nearly unique values and may be an identifier or free text.",
                    column=column,
                    affected_count=int(df[column].nunique(dropna=True)),
                    suggested_action="Avoid using this column as a segment unless it is intentionally an identifier.",
                    evidence={"unique_ratio": round(unique_ratio, 3)},
                )
            )

    numeric_candidates = list(df.select_dtypes(include=[np.number]).columns)
    for column in df.select_dtypes(include=["object", "string"]).columns:
        if detect_column_kind(df[column], str(column)) == "numeric_text":
            numeric_candidates.append(column)

    for column in numeric_candidates:
        numeric = df[column] if pd.api.types.is_numeric_dtype(df[column]) else parse_numeric_series(df[column])
        numeric = pd.to_numeric(numeric, errors="coerce")
        if POSITIVE_FIELD_HINTS.search(str(column)):
            negative_mask = numeric < 0
            if negative_mask.any():
                issues.append(
                    _issue(
                        f"negative_expected_positive:{column}",
                        "accuracy_indicators",
                        "medium",
                        f"Negative values in expected-positive field {column}",
                        "The column name suggests values should usually be non-negative.",
                        column=column,
                        affected_count=int(negative_mask.sum()),
                        affected_rows=_row_indices(negative_mask),
                        suggested_action="Verify whether refunds, corrections, or data-entry errors explain the negative values.",
                    )
                )

        clean_numeric = numeric.dropna()
        if len(clean_numeric) >= 8:
            q1, q3 = clean_numeric.quantile([0.25, 0.75])
            iqr = q3 - q1
            if iqr > 0:
                outlier_mask = (numeric < q1 - 1.5 * iqr) | (numeric > q3 + 1.5 * iqr)
                if outlier_mask.any():
                    issues.append(
                        _issue(
                            f"outliers_iqr:{column}",
                            "accuracy_indicators",
                            "medium" if outlier_mask.sum() / len(df) >= 0.02 else "low",
                            f"Numerical outliers in {column}",
                            "Values fall outside the standard interquartile range fence. Outliers are not automatically errors.",
                            column=column,
                            affected_count=int(outlier_mask.sum()),
                            affected_rows=_row_indices(outlier_mask),
                            suggested_action="Flag, cap, filter, or manually review outliers depending on business meaning.",
                            evidence={"q1": float(q1), "q3": float(q3), "iqr": float(iqr)},
                        )
                    )

    for column in classify_columns(df)["categorical"]:
        freq = df[column].value_counts(dropna=True)
        if len(freq) > 3:
            rare = freq[freq <= max(1, math.floor(row_count * 0.01))]
            if not rare.empty:
                issues.append(
                    _issue(
                        f"rare_categories:{column}",
                        "accuracy_indicators",
                        "low",
                        f"Rare categories in {column}",
                        "Low-frequency categories may be valid niche segments or inconsistent labels.",
                        column=column,
                        affected_count=int(rare.sum()),
                        suggested_action="Review rare categories before grouping them.",
                        evidence={"examples": rare.head(10).to_dict()},
                    )
                )

    for column in classify_columns(df)["date"]:
        dates = df[column] if pd.api.types.is_datetime64_any_dtype(df[column]) else pd.to_datetime(df[column], errors="coerce", format="mixed")
        lower = pd.Timestamp("1900-01-01")
        upper = pd.Timestamp(datetime.now() + timedelta(days=365))
        suspicious = dates.notna() & ((dates < lower) | (dates > upper))
        if suspicious.any():
            issues.append(
                _issue(
                    f"suspicious_dates:{column}",
                    "accuracy_indicators",
                    "medium",
                    f"Impossible or suspicious dates in {column}",
                    "Dates are before 1900 or more than one year in the future.",
                    column=column,
                    affected_count=int(suspicious.sum()),
                    affected_rows=_row_indices(suspicious),
                    suggested_action="Correct or exclude suspicious dates after review.",
                )
            )

    sensitive = detect_sensitive_columns(df)
    for column, reasons in sensitive.items():
        issues.append(
            _issue(
                f"sensitive:{column}",
                "privacy",
                "medium",
                f"Potentially sensitive column {column}",
                "The column name or values suggest personal or payment-related information.",
                column=column,
                affected_count=int(df[column].notna().sum()) if column in df.columns else 0,
                suggested_action="Mask previews and avoid sending raw values to external systems.",
                evidence={"reasons": reasons},
            )
        )

    ids = potential_identifier_columns(df)
    target = context.target_variable
    for column in ids:
        if target and str(column) == str(target):
            issues.append(
                _issue(
                    f"identifier_leakage:{column}",
                    "validity",
                    "high",
                    f"Potential identifier leakage in target {column}",
                    "The selected KPI or target behaves like an identifier rather than a measurable outcome.",
                    column=column,
                    affected_count=row_count,
                    suggested_action="Select a business KPI instead of an identifier column.",
                )
            )

    return issues


def calculate_quality_scores(df: pd.DataFrame, issues: list[DataIssue]) -> QualityScores:
    total_cells = max(df.shape[0] * df.shape[1], 1)
    missing_cells = int(df.isna().sum().sum())
    completeness = max(0.0, 100.0 * (1.0 - missing_cells / total_cells))

    duplicate_penalty = min(60.0, 100.0 * df.duplicated().sum() / max(len(df), 1))
    uniqueness = max(0.0, 100.0 - duplicate_penalty)

    buckets = {
        "validity": ["validity"],
        "consistency": ["consistency"],
        "accuracy_indicators": ["accuracy_indicators"],
        "data_type_reliability": ["validity"],
    }

    def issue_penalty(categories: list[str]) -> float:
        relevant = [issue for issue in issues if issue.category in categories]
        penalty = 0.0
        for issue in relevant:
            weight = {"low": 2.5, "medium": 6.0, "high": 12.0}[issue.severity]
            affected_ratio = issue.affected_count / max(len(df), 1) if issue.affected_count else 0.2
            penalty += weight * min(1.0, max(affected_ratio, 0.1))
        return min(80.0, penalty)

    validity = max(0.0, 100.0 - issue_penalty(buckets["validity"]))
    consistency = max(0.0, 100.0 - issue_penalty(buckets["consistency"]))
    accuracy = max(0.0, 100.0 - issue_penalty(buckets["accuracy_indicators"]))

    type_related = [
        issue for issue in issues if issue.id.startswith(("mixed_numeric:", "invalid_dates:", "mixed_units:"))
    ]
    data_type_reliability = max(0.0, 100.0 - min(70.0, 9.0 * len(type_related)))

    overall = (
        completeness * 0.25
        + validity * 0.2
        + consistency * 0.15
        + uniqueness * 0.15
        + accuracy * 0.15
        + data_type_reliability * 0.10
    )

    return QualityScores(
        overall=round(overall, 1),
        completeness=round(completeness, 1),
        validity=round(validity, 1),
        consistency=round(consistency, 1),
        uniqueness=round(uniqueness, 1),
        accuracy_indicators=round(accuracy, 1),
        data_type_reliability=round(data_type_reliability, 1),
        explanation=(
            "Scores are heuristic indicators based on observable dataset structure. "
            "Real-world accuracy is not verified unless reference data is supplied."
        ),
    )


def assess_data_quality(df: pd.DataFrame, context: BusinessContext | None = None) -> dict[str, Any]:
    issues = detect_quality_issues(df, context)
    scores = calculate_quality_scores(df, issues)
    return {
        "scores": scores.model_dump(),
        "issues": [issue.model_dump() for issue in issues],
        "summary": {
            "issue_count": len(issues),
            "high_severity": sum(issue.severity == "high" for issue in issues),
            "medium_severity": sum(issue.severity == "medium" for issue in issues),
            "low_severity": sum(issue.severity == "low" for issue in issues),
        },
    }
