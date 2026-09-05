from __future__ import annotations

import re
from typing import Any

import pandas as pd

from models.schemas import DataIssue, ValidationRule


def _affected_rows(mask: pd.Series, limit: int = 100) -> list[int]:
    return [int(i) for i in mask[mask].index[:limit].tolist()]


def evaluate_validation_rule(df: pd.DataFrame, rule: ValidationRule) -> DataIssue | None:
    if rule.column not in df.columns:
        return DataIssue(
            id=f"validation_missing_column:{rule.id}",
            category="validity",
            severity="high",
            title=f"Validation rule references missing column {rule.column}",
            description="The rule cannot be evaluated because the selected column is not present.",
            column=rule.column,
            affected_count=0,
            suggested_action="Update or remove the rule.",
        )

    series = df[rule.column]
    mask = pd.Series(False, index=df.index)
    title = ""
    description = rule.description or ""

    if rule.rule_type == "required":
        mask = series.isna() | series.astype("string").str.strip().eq("")
        title = f"Required field violation in {rule.column}"
        description = description or "Required values are missing or blank."
    elif rule.rule_type == "unique":
        mask = series.duplicated(keep=False) & series.notna()
        title = f"Unique field violation in {rule.column}"
        description = description or "Values expected to be unique appear multiple times."
    elif rule.rule_type == "min_value":
        numeric = pd.to_numeric(series, errors="coerce")
        mask = numeric < float(rule.value)
        title = f"Minimum value violation in {rule.column}"
        description = description or f"Values must be greater than or equal to {rule.value}."
    elif rule.rule_type == "max_value":
        numeric = pd.to_numeric(series, errors="coerce")
        mask = numeric > float(rule.value)
        title = f"Maximum value violation in {rule.column}"
        description = description or f"Values must be less than or equal to {rule.value}."
    elif rule.rule_type == "range":
        numeric = pd.to_numeric(series, errors="coerce")
        mask = (numeric < float(rule.value)) | (numeric > float(rule.second_value))
        title = f"Range violation in {rule.column}"
        description = description or f"Values must be between {rule.value} and {rule.second_value}."
    elif rule.rule_type == "category_list":
        allowed = {str(value).strip().lower() for value in (rule.value or [])}
        values = series.astype("string").str.strip().str.lower()
        mask = series.notna() & ~values.isin(allowed)
        title = f"Category-list violation in {rule.column}"
        description = description or "Values fall outside the allowed category list."
    elif rule.rule_type == "date_range":
        dates = pd.to_datetime(series, errors="coerce", format="mixed")
        start = pd.Timestamp(rule.value)
        end = pd.Timestamp(rule.second_value)
        mask = dates.notna() & ((dates < start) | (dates > end))
        title = f"Date-range violation in {rule.column}"
        description = description or f"Dates must be between {start.date()} and {end.date()}."
    elif rule.rule_type == "regex":
        pattern = re.compile(str(rule.value))
        values = series.astype("string")
        mask = series.notna() & ~values.map(lambda value: bool(pattern.fullmatch(str(value))))
        title = f"Pattern violation in {rule.column}"
        description = description or "Values do not match the required regular expression."
    elif rule.rule_type == "cross_column_greater_equal":
        other_column = str(rule.value)
        if other_column not in df.columns:
            return DataIssue(
                id=f"validation_missing_column:{rule.id}:{other_column}",
                category="validity",
                severity="high",
                title=f"Validation rule references missing column {other_column}",
                description="The rule cannot be evaluated because the comparison column is not present.",
                column=rule.column,
                affected_count=0,
                suggested_action="Update or remove the rule.",
            )
        left = pd.to_numeric(series, errors="coerce")
        right = pd.to_numeric(df[other_column], errors="coerce")
        mask = left.notna() & right.notna() & (left < right)
        title = f"Cross-column rule violation in {rule.column}"
        description = description or f"{rule.column} must be greater than or equal to {other_column}."

    affected = int(mask.sum())
    if affected == 0:
        return None

    return DataIssue(
        id=f"validation:{rule.id}",
        category="validity",
        severity="high" if affected / max(len(df), 1) >= 0.1 else "medium",
        title=title,
        description=description,
        column=rule.column,
        affected_count=affected,
        affected_rows=_affected_rows(mask),
        suggested_action="Review records that violate this user-defined rule.",
        evidence={"rule_type": rule.rule_type, "value": rule.value, "second_value": rule.second_value},
    )


def evaluate_validation_rules(df: pd.DataFrame, rules: list[ValidationRule]) -> list[dict[str, Any]]:
    issues = []
    for rule in rules:
        issue = evaluate_validation_rule(df, rule)
        if issue is not None:
            issues.append(issue.model_dump())
    return issues

