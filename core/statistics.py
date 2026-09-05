from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LinearRegression

from core.profiler import classify_columns, detect_column_kind, parse_numeric_series
from models.schemas import BusinessContext


@dataclass
class PreparedAnalysisFrame:
    df: pd.DataFrame
    numerical: list[str]
    categorical: list[str]
    date: list[str]
    text: list[str]
    boolean: list[str]


def prepare_analysis_frame(df: pd.DataFrame) -> PreparedAnalysisFrame:
    prepared = df.copy()
    groups = classify_columns(prepared)
    for column in groups["numeric_text"]:
        prepared[column] = parse_numeric_series(prepared[column])
    for column in groups["date"]:
        if not pd.api.types.is_datetime64_any_dtype(prepared[column]):
            prepared[column] = pd.to_datetime(prepared[column], errors="coerce", format="mixed")

    groups = classify_columns(prepared)
    return PreparedAnalysisFrame(
        df=prepared,
        numerical=groups["numerical"],
        categorical=groups["categorical"],
        date=groups["date"],
        text=groups["text"],
        boolean=groups["boolean"],
    )


def numeric_summary(df: pd.DataFrame, numerical: list[str]) -> pd.DataFrame:
    if not numerical:
        return pd.DataFrame()
    summary = df[numerical].describe(percentiles=[0.25, 0.5, 0.75, 0.9, 0.95]).T
    summary["variance"] = df[numerical].var(numeric_only=True)
    summary["skewness"] = df[numerical].skew(numeric_only=True)
    summary["kurtosis"] = df[numerical].kurtosis(numeric_only=True)
    summary["missing"] = df[numerical].isna().sum()
    return summary.reset_index(names="column")


def categorical_summary(df: pd.DataFrame, categorical: list[str], limit: int = 10) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for column in categorical:
        counts = df[column].value_counts(dropna=False).head(limit)
        total = max(len(df), 1)
        result[column] = [
            {"value": str(index), "count": int(value), "pct": round(float(value) / total * 100, 2)}
            for index, value in counts.items()
        ]
    return result


def date_summary(df: pd.DataFrame, date_columns: list[str]) -> pd.DataFrame:
    rows = []
    for column in date_columns:
        dates = pd.to_datetime(df[column], errors="coerce")
        rows.append(
            {
                "column": column,
                "min": dates.min(),
                "max": dates.max(),
                "valid_dates": int(dates.notna().sum()),
                "missing_or_invalid": int(dates.isna().sum()),
            }
        )
    return pd.DataFrame(rows)


def _select_target(df: pd.DataFrame, numerical: list[str], context: BusinessContext) -> str | None:
    if context.target_variable in numerical:
        return context.target_variable
    if numerical:
        return numerical[0]
    return None


def _select_dimension(categorical: list[str], context: BusinessContext) -> str | None:
    for dimension in context.important_dimensions:
        if dimension in categorical:
            return dimension
    return categorical[0] if categorical else None


def _time_series(df: pd.DataFrame, date_cols: list[str], numerical: list[str], context: BusinessContext) -> list[dict[str, Any]]:
    date_col = context.date_column if context.date_column in date_cols else (date_cols[0] if date_cols else None)
    target = _select_target(df, numerical, context)
    if not date_col or not target:
        return []
    temp = df[[date_col, target]].dropna().copy()
    if temp.empty:
        return []
    temp[date_col] = pd.to_datetime(temp[date_col], errors="coerce")
    temp = temp.dropna()
    if temp.empty:
        return []
    monthly = temp.set_index(date_col).sort_index()[target].resample("ME").sum().reset_index()
    monthly["growth_rate"] = monthly[target].pct_change()
    monthly["moving_average_3"] = monthly[target].rolling(3, min_periods=1).mean()
    return monthly.to_dict("records")


def _group_comparisons(df: pd.DataFrame, numerical: list[str], categorical: list[str], context: BusinessContext) -> pd.DataFrame:
    target = _select_target(df, numerical, context)
    dimension = _select_dimension(categorical, context)
    if not target or not dimension:
        return pd.DataFrame()
    grouped = (
        df.groupby(dimension, dropna=False)[target]
        .agg(["count", "mean", "median", "sum", "std"])
        .sort_values("sum", ascending=False)
        .reset_index()
    )
    grouped["contribution_pct"] = grouped["sum"] / grouped["sum"].sum() * 100 if grouped["sum"].sum() else 0
    return grouped


def _pareto(df: pd.DataFrame, numerical: list[str], categorical: list[str], context: BusinessContext) -> pd.DataFrame:
    target = _select_target(df, numerical, context)
    dimension = _select_dimension(categorical, context)
    if not target or not dimension:
        return pd.DataFrame()
    pareto = df.groupby(dimension, dropna=False)[target].sum().sort_values(ascending=False).reset_index()
    total = pareto[target].sum()
    if total:
        pareto["contribution_pct"] = pareto[target] / total * 100
        pareto["cumulative_pct"] = pareto["contribution_pct"].cumsum()
    else:
        pareto["contribution_pct"] = 0
        pareto["cumulative_pct"] = 0
    return pareto


def _anomalies(df: pd.DataFrame, numerical: list[str]) -> pd.DataFrame:
    if not numerical or len(df) < 8:
        return pd.DataFrame()
    numeric = df[numerical].apply(pd.to_numeric, errors="coerce")
    filled = numeric.fillna(numeric.median(numeric_only=True))
    if filled.dropna(axis=1, how="all").shape[1] == 0:
        return pd.DataFrame()
    used_columns = filled.dropna(axis=1, how="all").columns.tolist()
    filled = filled[used_columns]
    try:
        if len(used_columns) >= 2 and len(filled) >= 20:
            model = IsolationForest(contamination=min(0.1, max(0.02, 5 / len(filled))), random_state=42)
            labels = model.fit_predict(filled)
            scores = model.decision_function(filled)
            mask = labels == -1
            result = df.loc[mask].copy()
            result["anomaly_score"] = scores[mask]
            result["anomaly_method"] = "Isolation Forest"
            return result.head(200)
    except Exception:
        pass

    flags = pd.Series(False, index=df.index)
    for column in used_columns:
        series = pd.to_numeric(df[column], errors="coerce")
        q1, q3 = series.quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr > 0:
            flags = flags | (series < q1 - 1.5 * iqr) | (series > q3 + 1.5 * iqr)
    result = df.loc[flags].copy()
    if not result.empty:
        result["anomaly_method"] = "IQR"
    return result.head(200)


def _inferential_tests(df: pd.DataFrame, numerical: list[str], categorical: list[str], context: BusinessContext) -> list[dict[str, Any]]:
    tests: list[dict[str, Any]] = []
    target = _select_target(df, numerical, context)
    dimension = _select_dimension(categorical, context)

    if target and dimension:
        temp = df[[target, dimension]].dropna()
        groups = [group[target].astype(float).values for _, group in temp.groupby(dimension) if len(group) >= 5]
        labels = [str(label) for label, group in temp.groupby(dimension) if len(group) >= 5]
        if len(groups) == 2:
            stat, p_value = stats.ttest_ind(groups[0], groups[1], equal_var=False)
            pooled = np.sqrt((np.var(groups[0], ddof=1) + np.var(groups[1], ddof=1)) / 2)
            effect = (np.mean(groups[0]) - np.mean(groups[1])) / pooled if pooled else np.nan
            tests.append(
                {
                    "test": "Welch independent t-test",
                    "columns": [target, dimension],
                    "sample_size": int(sum(len(group) for group in groups)),
                    "statistic": float(stat),
                    "p_value": float(p_value),
                    "effect_size": float(effect) if not np.isnan(effect) else None,
                    "assumptions_checked": "Two groups with at least five observations each; Welch test avoids equal-variance assumption.",
                    "plain_language": (
                        f"Compared average {target} between {labels[0]} and {labels[1]}. "
                        "A low p-value indicates an association in this sample, not causation."
                    ),
                }
            )
        elif 3 <= len(groups) <= 8:
            stat, p_value = stats.f_oneway(*groups)
            tests.append(
                {
                    "test": "One-way ANOVA",
                    "columns": [target, dimension],
                    "sample_size": int(sum(len(group) for group in groups)),
                    "statistic": float(stat),
                    "p_value": float(p_value),
                    "effect_size": None,
                    "assumptions_checked": "Three to eight groups with at least five observations each; normality is not guaranteed.",
                    "plain_language": (
                        f"Tested whether average {target} differs by {dimension}. "
                        "Association does not prove causation."
                    ),
                }
            )

    if len(categorical) >= 2:
        a, b = categorical[:2]
        table = pd.crosstab(df[a], df[b])
        if table.shape[0] > 1 and table.shape[1] > 1 and table.values.sum() >= 20:
            stat, p_value, dof, expected = stats.chi2_contingency(table)
            n = table.values.sum()
            phi2 = stat / n
            r, k = table.shape
            cramers_v = np.sqrt(phi2 / max(min(k - 1, r - 1), 1))
            tests.append(
                {
                    "test": "Chi-square test of independence",
                    "columns": [a, b],
                    "sample_size": int(n),
                    "statistic": float(stat),
                    "p_value": float(p_value),
                    "effect_size": float(cramers_v),
                    "assumptions_checked": "Contingency table has at least two rows and columns; expected counts should be reviewed.",
                    "plain_language": f"Tested whether {a} and {b} are associated. Association does not prove causation.",
                }
            )

    if len(numerical) >= 2:
        corr = df[numerical].corr(numeric_only=True).abs()
        pairs = corr.where(~np.eye(corr.shape[0], dtype=bool)).stack().sort_values(ascending=False)
        if not pairs.empty:
            x, y = pairs.index[0]
            temp = df[[x, y]].dropna()
            if len(temp) >= 10:
                model = LinearRegression().fit(temp[[x]], temp[y])
                r_value = temp[x].corr(temp[y])
                tests.append(
                    {
                        "test": "Simple linear regression",
                        "columns": [x, y],
                        "sample_size": int(len(temp)),
                        "statistic": float(model.coef_[0]),
                        "p_value": None,
                        "effect_size": float(r_value),
                        "assumptions_checked": "Two numerical columns with at least ten paired observations; residual assumptions not fully verified.",
                        "plain_language": (
                            f"Estimated the linear relationship between {x} and {y}. "
                            "This describes association, not causation."
                        ),
                    }
                )
    return tests


def analyze_dataframe(df: pd.DataFrame, context: BusinessContext | None = None) -> dict[str, Any]:
    context = context or BusinessContext()
    prepared = prepare_analysis_frame(df)
    frame = prepared.df

    pearson = frame[prepared.numerical].corr(method="pearson") if len(prepared.numerical) >= 2 else pd.DataFrame()
    spearman = frame[prepared.numerical].corr(method="spearman") if len(prepared.numerical) >= 2 else pd.DataFrame()
    covariance = frame[prepared.numerical].cov() if len(prepared.numerical) >= 2 else pd.DataFrame()
    group_comparison = _group_comparisons(frame, prepared.numerical, prepared.categorical, context)
    pareto = _pareto(frame, prepared.numerical, prepared.categorical, context)
    anomalies = _anomalies(frame, prepared.numerical)
    time_series = _time_series(frame, prepared.date, prepared.numerical, context)
    tests = _inferential_tests(frame, prepared.numerical, prepared.categorical, context)

    target = _select_target(frame, prepared.numerical, context)
    kpis = {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "missing_cells": int(frame.isna().sum().sum()),
        "duplicate_rows": int(frame.duplicated().sum()),
    }
    if target:
        kpis.update(
            {
                f"{target}_sum": float(frame[target].sum(skipna=True)),
                f"{target}_mean": float(frame[target].mean(skipna=True)),
                f"{target}_median": float(frame[target].median(skipna=True)),
            }
        )

    missing_patterns = (
        frame.isna()
        .astype(int)
        .groupby(list(frame.columns), dropna=False)
        .size()
        .reset_index(name="row_count")
        .sort_values("row_count", ascending=False)
        .head(20)
        if len(frame.columns) <= 12 and len(frame) <= 5000
        else pd.DataFrame()
    )

    return {
        "prepared_df": frame,
        "column_groups": {
            "numerical": prepared.numerical,
            "categorical": prepared.categorical,
            "date": prepared.date,
            "text": prepared.text,
            "boolean": prepared.boolean,
        },
        "numeric_summary": numeric_summary(frame, prepared.numerical),
        "categorical_summary": categorical_summary(frame, prepared.categorical),
        "date_summary": date_summary(frame, prepared.date),
        "pearson_correlation": pearson,
        "spearman_correlation": spearman,
        "covariance": covariance,
        "group_comparison": group_comparison,
        "pareto": pareto,
        "time_series": time_series,
        "anomalies": anomalies,
        "inferential_tests": tests,
        "missing_patterns": missing_patterns,
        "kpis": kpis,
        "target": target,
    }
