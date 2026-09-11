from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from core.profiler import classify_columns, parse_numeric_series, potential_identifier_columns
from core.statistics import prepare_analysis_frame
from models.schemas import BusinessContext


AGGREGATIONS = ["sum", "mean", "median", "count", "distinct_count"]
COUNT_SENTINEL = "__count_records__"

IDENTIFIER_HINTS = re.compile(
    r"(^id$|[_\s-]id$|id[_\s-]|uuid|guid|key|code|number|no$|sku|barcode|postal|zip|phone|account)",
    re.I,
)
ADDITIVE_MEASURE_HINTS = re.compile(
    r"amount|sales|revenue|profit|margin|price|cost|spend|budget|quantity|qty|units|total|value|balance",
    re.I,
)
PRIMARY_MEASURE_HINTS = re.compile(
    r"total|amount|sales|revenue|profit|spend|budget|cost|value|balance",
    re.I,
)
VOLUME_MEASURE_HINTS = re.compile(r"quantity|qty|units", re.I)
RATE_MEASURE_HINTS = re.compile(
    r"price\s*per|per\s*unit|unit\s*price|rate|ratio|percent|pct|margin|discount",
    re.I,
)
MONEY_HINTS = re.compile(r"amount|sales|revenue|profit|price|cost|spend|budget|margin|value|balance", re.I)
CURRENCY_HINTS = re.compile(r"currency|curr|iso_currency|ccy", re.I)


@dataclass(frozen=True)
class DashboardRoles:
    prepared_df: pd.DataFrame
    date_candidates: list[str]
    dimension_candidates: list[str]
    measure_candidates: list[str]
    technical_numeric_candidates: list[str]
    identifier_columns: list[str]
    default_date: str | None
    default_dimensions: list[str]
    default_measure: str | None
    default_aggregation: str
    currency_columns: list[str]
    currency_values: dict[str, list[str]]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "prepared_df": self.prepared_df,
            "date_candidates": self.date_candidates,
            "dimension_candidates": self.dimension_candidates,
            "measure_candidates": self.measure_candidates,
            "technical_numeric_candidates": self.technical_numeric_candidates,
            "identifier_columns": self.identifier_columns,
            "default_date": self.default_date,
            "default_dimensions": self.default_dimensions,
            "default_measure": self.default_measure,
            "default_aggregation": self.default_aggregation,
            "currency_columns": self.currency_columns,
            "currency_values": self.currency_values,
            "warnings": self.warnings,
        }


def _unique_ratio(series: pd.Series) -> float:
    non_null = series.dropna()
    return float(non_null.nunique(dropna=True) / max(len(non_null), 1)) if len(non_null) else 0.0


def _looks_integer_like(series: pd.Series) -> bool:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return False
    return bool(np.isclose(numeric % 1, 0).mean() >= 0.98)


def _is_identifier_like(df: pd.DataFrame, column: str, profile_identifiers: set[str]) -> bool:
    if column in profile_identifiers or IDENTIFIER_HINTS.search(str(column)):
        return True
    if len(df) < 20:
        return False
    series = df[column]
    return _looks_integer_like(series) and _unique_ratio(series) >= 0.92


def _safe_dimension_candidates(df: pd.DataFrame, categorical: list[str], identifiers: set[str]) -> list[str]:
    candidates: list[str] = []
    for column in categorical:
        if column in identifiers:
            continue
        non_null_unique = df[column].dropna().nunique(dropna=True)
        if 2 <= non_null_unique <= 80:
            candidates.append(column)
    return candidates


def _currency_values(df: pd.DataFrame) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for column in df.columns:
        if not CURRENCY_HINTS.search(str(column)):
            continue
        values = (
            df[column]
            .dropna()
            .astype(str)
            .str.strip()
            .replace("", np.nan)
            .dropna()
            .value_counts()
            .head(8)
            .index.tolist()
        )
        if values:
            result[column] = [str(value) for value in values]
    return result


def _measure_priority(column: str) -> tuple[int, str]:
    name = str(column)
    if PRIMARY_MEASURE_HINTS.search(name):
        return (0, name.lower())
    if VOLUME_MEASURE_HINTS.search(name):
        return (1, name.lower())
    if RATE_MEASURE_HINTS.search(name):
        return (2, name.lower())
    if ADDITIVE_MEASURE_HINTS.search(name):
        return (3, name.lower())
    return (4, name.lower())


def _default_aggregation_for_measure(measure: str | None) -> str:
    if not measure:
        return "count"
    if RATE_MEASURE_HINTS.search(measure):
        return "mean"
    if (
        PRIMARY_MEASURE_HINTS.search(measure)
        or VOLUME_MEASURE_HINTS.search(measure)
        or ADDITIVE_MEASURE_HINTS.search(measure)
    ):
        return "sum"
    return "mean"


def infer_dashboard_roles(
    df: pd.DataFrame,
    context: BusinessContext | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context or BusinessContext()
    prepared = prepare_analysis_frame(df)
    frame = prepared.df
    profile_identifiers = set((profile or {}).get("potential_identifier_columns") or potential_identifier_columns(frame))
    identifier_columns = {
        column for column in prepared.numerical + prepared.categorical + prepared.text if column in frame and _is_identifier_like(frame, column, profile_identifiers)
    }

    measure_candidates = [column for column in prepared.numerical if column not in identifier_columns]
    measure_candidates.sort(key=_measure_priority)
    technical_numeric_candidates = [column for column in prepared.numerical if column in identifier_columns]

    dimension_candidates = _safe_dimension_candidates(frame, prepared.categorical + prepared.boolean, identifier_columns)
    context_dimensions = [dim for dim in context.important_dimensions if dim in dimension_candidates]
    dimension_candidates = context_dimensions + [col for col in dimension_candidates if col not in context_dimensions]

    default_measure = None
    if context.target_variable in measure_candidates:
        default_measure = context.target_variable
    elif measure_candidates:
        default_measure = measure_candidates[0]

    default_date = context.date_column if context.date_column in prepared.date else (prepared.date[0] if prepared.date else None)
    default_dimensions = context_dimensions[:2] if context_dimensions else dimension_candidates[:2]
    currency_values = _currency_values(frame)

    warnings: list[str] = []
    if not measure_candidates:
        warnings.append("No safe numeric measure was inferred. The dashboard will default to record counts until a meaningful measure is selected.")
    if any(len(values) > 1 for values in currency_values.values()) and default_measure and MONEY_HINTS.search(default_measure):
        warnings.append("Multiple currency values were detected. Monetary measures should not be combined without an explicit conversion method.")
    if technical_numeric_candidates:
        warnings.append("Identifier-like numeric fields were excluded from KPI sums and averages by default.")

    roles = DashboardRoles(
        prepared_df=frame,
        date_candidates=list(prepared.date),
        dimension_candidates=dimension_candidates,
        measure_candidates=measure_candidates,
        technical_numeric_candidates=technical_numeric_candidates,
        identifier_columns=sorted(identifier_columns),
        default_date=default_date,
        default_dimensions=default_dimensions,
        default_measure=default_measure,
        default_aggregation=_default_aggregation_for_measure(default_measure),
        currency_columns=list(currency_values.keys()),
        currency_values=currency_values,
        warnings=warnings,
    )
    return roles.to_dict()


def _valid_aggregation(aggregation: str | None) -> str:
    return aggregation if aggregation in AGGREGATIONS else "count"


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df:
        return pd.Series(dtype="float64")
    if pd.api.types.is_numeric_dtype(df[column]):
        return pd.to_numeric(df[column], errors="coerce")
    return parse_numeric_series(df[column])


def aggregate_value(df: pd.DataFrame, measure: str | None, aggregation: str) -> tuple[float | int | None, int]:
    aggregation = _valid_aggregation(aggregation)
    if aggregation == "count" or not measure or measure == COUNT_SENTINEL:
        return int(len(df)), int(len(df))
    if measure not in df.columns:
        return None, 0

    series = _numeric_series(df, measure)
    valid = series.dropna()
    if aggregation == "distinct_count":
        return int(valid.nunique(dropna=True)), int(valid.count())
    if valid.empty:
        return None, 0
    if aggregation == "sum":
        return float(valid.sum()), int(valid.count())
    if aggregation == "mean":
        return float(valid.mean()), int(valid.count())
    if aggregation == "median":
        return float(valid.median()), int(valid.count())
    return int(len(df)), int(len(df))


def aggregation_label(measure: str | None, aggregation: str) -> str:
    if aggregation == "count" or not measure or measure == COUNT_SENTINEL:
        return "Record count"
    if aggregation == "distinct_count":
        return f"Distinct {measure}"
    return f"{aggregation.title()} of {measure}"


def aggregation_formula(measure: str | None, aggregation: str, valid_records: int, total_records: int) -> str:
    if aggregation == "count" or not measure or measure == COUNT_SENTINEL:
        return f"Count of filtered records. Included records: {total_records:,}."
    excluded = max(total_records - valid_records, 0)
    if aggregation == "distinct_count":
        return f"Distinct non-missing values in {measure}. Included records: {valid_records:,}; missing or invalid excluded: {excluded:,}."
    return f"{aggregation.title()} of non-missing numeric values in {measure}. Included records: {valid_records:,}; missing or invalid excluded: {excluded:,}."


def apply_dashboard_filters(
    df: pd.DataFrame,
    *,
    date_column: str | None = None,
    date_range: tuple[Any, Any] | list[Any] | None = None,
    categorical_filters: dict[str, list[str]] | None = None,
    search_text: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    filtered = df.copy()
    active_filters: list[str] = []
    warnings: list[str] = []

    if date_column and date_column in filtered.columns and date_range and len(date_range) == 2:
        dates = pd.to_datetime(filtered[date_column], errors="coerce")
        start, end = pd.to_datetime(date_range[0], errors="coerce"), pd.to_datetime(date_range[1], errors="coerce")
        if pd.notna(start) and pd.notna(end):
            if start > end:
                start, end = end, start
            valid_dates = dates.notna()
            filtered = filtered[valid_dates & (dates >= start) & (dates <= end + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1))]
            active_filters.append(f"{date_column}: {start.date()} to {end.date()}")
            invalid_count = int((~valid_dates).sum())
            if invalid_count:
                warnings.append(f"{invalid_count:,} records have invalid or missing {date_column} values and are excluded by the date filter.")

    for column, selected_values in (categorical_filters or {}).items():
        if column not in filtered.columns or not selected_values:
            continue
        selected = {str(value) for value in selected_values}
        filtered = filtered[filtered[column].astype(str).isin(selected)]
        active_filters.append(f"{column}: {len(selected)} selected")

    search = (search_text or "").strip()
    if search:
        if filtered.empty:
            mask = pd.Series(dtype=bool)
        else:
            searchable_columns = filtered.select_dtypes(include=["object", "string", "category"]).columns.tolist()
            if not searchable_columns:
                searchable_columns = filtered.columns.tolist()
            mask = filtered[searchable_columns].astype("string").apply(
                lambda series: series.str.contains(search, case=False, regex=False, na=False)
            ).any(axis=1)
        filtered = filtered.loc[mask]
        active_filters.append(f"Search: {search}")

    meta = {
        "active_filters": active_filters,
        "warnings": warnings,
        "records_before": int(len(df)),
        "records_after": int(len(filtered)),
        "filtered_pct": round(float(len(filtered) / max(len(df), 1) * 100), 2),
    }
    return filtered, meta


def _period_frequency(dates: pd.Series) -> str:
    if dates.empty:
        return "D"
    span_days = max((dates.max() - dates.min()).days, 0)
    if span_days > 730:
        return "Q"
    if span_days > 75:
        return "M"
    return "D"


def _grouped_metric(
    df: pd.DataFrame,
    by: str,
    measure: str | None,
    aggregation: str,
) -> pd.DataFrame:
    aggregation = _valid_aggregation(aggregation)
    if df.empty or by not in df.columns:
        return pd.DataFrame(columns=[by, "value"])
    working = df[[by] + ([measure] if measure and measure in df.columns else [])].copy()
    if aggregation == "count" or not measure or measure == COUNT_SENTINEL or measure not in working.columns:
        grouped = working.groupby(by, dropna=False).size().reset_index(name="value")
    else:
        working[measure] = _numeric_series(working, measure)
        if aggregation == "distinct_count":
            grouped = working.groupby(by, dropna=False)[measure].nunique(dropna=True).reset_index(name="value")
        else:
            grouped = getattr(working.groupby(by, dropna=False)[measure], aggregation)().reset_index(name="value")
    grouped[by] = grouped[by].astype(str).replace({"nan": "Missing", "NaT": "Missing"})
    return grouped


def trend_data(df: pd.DataFrame, date_column: str | None, measure: str | None, aggregation: str) -> pd.DataFrame:
    if not date_column or date_column not in df.columns or df.empty:
        return pd.DataFrame(columns=["period", "value"])
    working = df.copy()
    working[date_column] = pd.to_datetime(working[date_column], errors="coerce")
    working = working.dropna(subset=[date_column])
    if len(working) < 2:
        return pd.DataFrame(columns=["period", "value"])
    freq = _period_frequency(working[date_column])
    working["period"] = working[date_column].dt.to_period(freq).dt.to_timestamp()
    grouped = _grouped_metric(working, "period", measure, aggregation)
    grouped["period"] = pd.to_datetime(grouped["period"], errors="coerce")
    return grouped.dropna(subset=["period"]).sort_values("period")


def category_data(df: pd.DataFrame, dimension: str | None, measure: str | None, aggregation: str, limit: int = 12) -> pd.DataFrame:
    if not dimension or dimension not in df.columns or df.empty:
        return pd.DataFrame(columns=["category", "value"])
    grouped = _grouped_metric(df, dimension, measure, aggregation)
    if grouped.empty:
        return pd.DataFrame(columns=["category", "value"])
    grouped = grouped.rename(columns={dimension: "category"})
    grouped["value"] = pd.to_numeric(grouped["value"], errors="coerce").fillna(0)
    return grouped.sort_values("value", ascending=False).head(limit)


def distribution_data(df: pd.DataFrame, measure: str | None, max_rows: int = 5000) -> tuple[pd.DataFrame, bool]:
    if not measure or measure == COUNT_SENTINEL or measure not in df.columns:
        return pd.DataFrame(), False
    values = _numeric_series(df, measure).dropna().to_frame(name=measure)
    if values.empty:
        return pd.DataFrame(), False
    sampled = len(values) > max_rows
    if sampled:
        values = values.sample(max_rows, random_state=42)
    return values, sampled


def scatter_data(df: pd.DataFrame, x_col: str | None, y_col: str | None, max_rows: int = 2500) -> tuple[pd.DataFrame, bool]:
    if not x_col or not y_col or x_col == y_col or x_col not in df.columns or y_col not in df.columns:
        return pd.DataFrame(), False
    values = pd.DataFrame({x_col: _numeric_series(df, x_col), y_col: _numeric_series(df, y_col)}).dropna()
    if len(values) < 10:
        return pd.DataFrame(), False
    sampled = len(values) > max_rows
    if sampled:
        values = values.sample(max_rows, random_state=42)
    return values, sampled


def missing_data(df: pd.DataFrame, limit: int = 12) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["column", "missing_count", "missing_pct"])
    missing = df.isna().sum().sort_values(ascending=False)
    missing = missing[missing > 0]
    if missing.empty:
        return pd.DataFrame(columns=["column", "missing_count", "missing_pct"])
    result = missing.head(limit).rename_axis("column").reset_index(name="missing_count")
    result["missing_pct"] = result["missing_count"] / max(len(df), 1) * 100
    return result


def period_delta(df: pd.DataFrame, date_column: str | None, measure: str | None, aggregation: str) -> dict[str, Any] | None:
    trend = trend_data(df, date_column, measure, aggregation)
    if len(trend) < 2:
        return None
    current = float(trend["value"].iloc[-1])
    previous = float(trend["value"].iloc[-2])
    if previous == 0:
        return {
            "current": current,
            "previous": previous,
            "delta_pct": None,
            "note": "Previous comparable period was zero, so percent change is not shown.",
        }
    return {
        "current": current,
        "previous": previous,
        "delta_pct": (current - previous) / abs(previous) * 100,
        "note": "Comparison uses the two latest complete available periods in the filtered data.",
    }


def build_dashboard_kpis(
    full_df: pd.DataFrame,
    filtered_df: pd.DataFrame,
    *,
    measure: str | None,
    aggregation: str,
    date_column: str | None = None,
    primary_dimension: str | None = None,
) -> list[dict[str, Any]]:
    total_records = len(full_df)
    filtered_records = len(filtered_df)
    kpis: list[dict[str, Any]] = [
        {
            "label": "Records in view",
            "value": filtered_records,
            "delta": f"{filtered_records / max(total_records, 1) * 100:.1f}% of dataset",
            "definition": f"Filtered records divided by all loaded records. Base records: {total_records:,}.",
        }
    ]

    metric_value, valid_records = aggregate_value(filtered_df, measure, aggregation)
    if metric_value is not None:
        delta = period_delta(filtered_df, date_column, measure, aggregation)
        kpis.append(
            {
                "label": aggregation_label(measure, aggregation),
                "value": metric_value,
                "delta": f"{delta['delta_pct']:+.1f}% vs previous period" if delta and delta.get("delta_pct") is not None else None,
                "definition": aggregation_formula(measure, aggregation, valid_records, filtered_records),
            }
        )

    missing_cells = int(filtered_df.isna().sum().sum()) if not filtered_df.empty else 0
    total_cells = max(filtered_df.shape[0] * filtered_df.shape[1], 1)
    complete_pct = (1 - missing_cells / total_cells) * 100
    kpis.append(
        {
            "label": "Complete cells",
            "value": complete_pct,
            "format": "percent_100",
            "delta": f"{missing_cells:,} missing cells",
            "definition": "Non-missing cells divided by all cells in the filtered data.",
        }
    )

    if primary_dimension and primary_dimension in filtered_df.columns and not filtered_df.empty:
        grouped = category_data(filtered_df, primary_dimension, measure, aggregation, limit=1)
        if not grouped.empty:
            kpis.append(
                {
                    "label": f"Top {primary_dimension}",
                    "value": str(grouped["category"].iloc[0]),
                    "delta": f"{float(grouped['value'].iloc[0]):,.2f} by selected metric",
                    "definition": f"Highest {aggregation_label(measure, aggregation).lower()} segment among filtered records.",
                }
            )

    if date_column and date_column in filtered_df.columns:
        valid_dates = pd.to_datetime(filtered_df[date_column], errors="coerce").notna().sum()
        kpis.append(
            {
                "label": "Valid date coverage",
                "value": valid_dates / max(filtered_records, 1) * 100,
                "format": "percent_100",
                "delta": f"{valid_dates:,} dated records",
                "definition": f"Records with parseable {date_column} values divided by filtered records.",
            }
        )
    else:
        duplicate_rows = int(filtered_df.duplicated().sum()) if not filtered_df.empty else 0
        kpis.append(
            {
                "label": "Duplicate rows",
                "value": duplicate_rows,
                "delta": "Exact duplicate records",
                "definition": "Rows in the filtered data that duplicate an earlier row exactly.",
            }
        )

    return kpis[:5]


def build_dashboard_insights(
    filtered_df: pd.DataFrame,
    *,
    measure: str | None,
    aggregation: str,
    date_column: str | None,
    primary_dimension: str | None,
) -> dict[str, list[str]]:
    observations: list[str] = []
    actions: list[str] = []
    caveats: list[str] = []

    if filtered_df.empty:
        return {
            "observations": ["No records match the active filters."],
            "actions": ["Reset filters or broaden category/date selections before interpreting the dashboard."],
            "caveats": ["No statistical conclusion can be drawn from an empty filtered view."],
        }

    metric_value, valid_records = aggregate_value(filtered_df, measure, aggregation)
    if metric_value is not None:
        observations.append(
            f"{aggregation_label(measure, aggregation)} is {metric_value:,.2f} across {len(filtered_df):,} filtered records."
            if isinstance(metric_value, float)
            else f"{aggregation_label(measure, aggregation)} is {metric_value:,} across {len(filtered_df):,} filtered records."
        )
        if measure and measure != COUNT_SENTINEL and valid_records < len(filtered_df):
            caveats.append(f"{len(filtered_df) - valid_records:,} records were excluded from the metric because {measure} was missing or invalid.")

    trend = trend_data(filtered_df, date_column, measure, aggregation)
    if not trend.empty:
        high = trend.loc[trend["value"].idxmax()]
        low = trend.loc[trend["value"].idxmin()]
        observations.append(
            f"The highest period is {pd.to_datetime(high['period']).date()} with {float(high['value']):,.2f}; "
            f"the lowest is {pd.to_datetime(low['period']).date()} with {float(low['value']):,.2f}."
        )
        actions.append("Review the strongest period movements with business context before making operational decisions.")

    grouped = category_data(filtered_df, primary_dimension, measure, aggregation, limit=3)
    if not grouped.empty:
        top = grouped.iloc[0]
        observations.append(f"{top['category']} is the leading {primary_dimension} segment by the selected metric.")
        if len(grouped) > 1:
            actions.append(f"Compare the top {primary_dimension} segment against the next segments to understand whether the gap is structural or temporary.")

    if not observations:
        observations.append("The current dataset supports a neutral overview, but more business field mapping is needed for stronger KPI interpretation.")
    if not actions:
        actions.append("Map a meaningful measure, date field, and segment field to unlock richer trend and comparison analysis.")

    caveats.append("These are descriptive observations from computed statistics. They show association and movement, not causation.")
    return {"observations": observations[:4], "actions": actions[:3], "caveats": caveats[:3]}
