"""Reusable, data-agnostic building blocks for the professional analytics view."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.exporting import dataframe_to_csv_bytes
from core.profiler import classify_columns
from core.security import mask_sensitive_preview
from models.schemas import BusinessContext


PALETTE = ["#2563eb", "#0f766e", "#4f46e5", "#f59e0b", "#dc2626", "#0891b2"]
METRIC_HINTS = re.compile(
    r"revenue|sales|turnover|gmv|income|profit|margin|amount|spend|cost|price|value|salary|balance|quantity|qty|units|orders?",
    re.I,
)
ADDITIVE_METRIC_HINTS = re.compile(
    r"revenue|sales|turnover|gmv|income|profit|amount|spend|cost|value|salary|balance|quantity|qty|units|orders?",
    re.I,
)
IDENTIFIER_HINTS = re.compile(r"(^id$|[_ -]id$|id[_ -]|uuid|guid|code|sku|invoice|order[_ -]?(id|number|no))", re.I)
DIMENSION_HINTS = re.compile(r"region|segment|category|product|department|status|channel|market|country|city|type|group", re.I)
CUSTOMER_HINTS = re.compile(r"customer|client|account|buyer|member|user", re.I)
PERCENT_HINTS = re.compile(r"rate|ratio|pct|percent|percentage|margin|conversion", re.I)


@dataclass(frozen=True)
class DashboardSchema:
    numerical: list[str]
    categorical: list[str]
    date_columns: list[str]
    primary_metric: str | None
    primary_dimension: str | None
    customer_column: str | None
    currency: str | None


@dataclass(frozen=True)
class DashboardKpi:
    label: str
    value: str
    detail: str
    sparkline: list[float] | None = None


@dataclass(frozen=True)
class DashboardInsight:
    title: str
    detail: str
    tone: str = "info"


@dataclass(frozen=True)
class DashboardChart:
    key: str
    title: str
    figure: go.Figure
    explanation: str
    sampled: bool = False


def humanize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[_-]+", " ", str(value))).strip().title()


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower())


def _metric_score(column: str) -> int:
    label = _normalized(column)
    if IDENTIFIER_HINTS.search(label):
        return -100
    score = 0
    if METRIC_HINTS.search(label):
        score += 100
    if ADDITIVE_METRIC_HINTS.search(label):
        score += 30
    if PERCENT_HINTS.search(label):
        score += 10
    return score


def _dimension_score(column: str, values: pd.Series) -> tuple[int, int]:
    unique_count = int(values.nunique(dropna=True))
    score = 100 if DIMENSION_HINTS.search(_normalized(column)) else 0
    # Very high-cardinality labels make unreadable charts and filters.
    if unique_count > 60:
        score -= 100
    return score, unique_count


def _pick_customer_column(df: pd.DataFrame) -> str | None:
    candidates = [str(column) for column in df.columns if CUSTOMER_HINTS.search(_normalized(str(column)))]
    return candidates[0] if candidates else None


def build_dashboard_schema(
    df: pd.DataFrame,
    analysis: dict[str, Any] | None = None,
    context: BusinessContext | None = None,
) -> DashboardSchema:
    """Identify useful dimensions without assuming a specific business schema."""

    context = context or BusinessContext()
    groups = (analysis or {}).get("column_groups", {})
    available = {str(column) for column in df.columns}
    numerical = [str(column) for column in groups.get("numerical", []) if str(column) in available]
    categorical = [str(column) for column in groups.get("categorical", []) if str(column) in available]
    date_columns = [str(column) for column in groups.get("date", []) if str(column) in available]

    if not (numerical or categorical or date_columns):
        inferred = classify_columns(df)
        numerical = [str(column) for column in inferred["numerical"]]
        categorical = [str(column) for column in inferred["categorical"]]
        date_columns = [str(column) for column in inferred["date"]]

    numerical = [column for column in numerical if not IDENTIFIER_HINTS.search(_normalized(column))]
    if context.target_variable in numerical:
        primary_metric = context.target_variable
    else:
        primary_metric = max(numerical, key=_metric_score, default=None)

    ordered_dimensions = sorted(
        categorical,
        key=lambda column: _dimension_score(column, df[column]),
        reverse=True,
    )
    if context.important_dimensions:
        primary_dimension = next(
            (column for column in context.important_dimensions if column in ordered_dimensions),
            ordered_dimensions[0] if ordered_dimensions else None,
        )
    else:
        primary_dimension = ordered_dimensions[0] if ordered_dimensions else None

    return DashboardSchema(
        numerical=numerical,
        categorical=ordered_dimensions,
        date_columns=date_columns,
        primary_metric=primary_metric,
        primary_dimension=primary_dimension,
        customer_column=_pick_customer_column(df),
        currency=context.currency,
    )


def _currency_symbol(currency: str | None) -> str | None:
    if not currency:
        return None
    mapping = {"inr": "₹", "rupee": "₹", "usd": "$", "dollar": "$", "eur": "€", "gbp": "£"}
    return mapping.get(currency.strip().lower())


def format_compact_number(value: Any, currency: str | None = None, percentage: bool = False) -> str:
    """Format a number without inventing a currency or unit."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    if percentage:
        return f"{number * 100:,.2f}%"

    symbol = _currency_symbol(currency)
    absolute = abs(number)
    if symbol == "₹" and absolute >= 100_000:
        text = f"{number / 100_000:,.2f}".rstrip("0").rstrip(".") + "L"
    elif absolute >= 1_000_000_000:
        text = f"{number / 1_000_000_000:,.2f}".rstrip("0").rstrip(".") + "B"
    elif absolute >= 1_000_000:
        text = f"{number / 1_000_000:,.2f}".rstrip("0").rstrip(".") + "M"
    elif absolute >= 1_000:
        text = f"{number / 1_000:,.2f}".rstrip("0").rstrip(".") + "K"
    elif number.is_integer():
        text = f"{int(number):,}"
    else:
        text = f"{number:,.2f}".rstrip("0").rstrip(".")
    return f"{symbol or ''}{text}"


def _metric_is_percentage(metric: str | None) -> bool:
    return bool(metric and PERCENT_HINTS.search(_normalized(metric)))


def _metric_is_additive(metric: str | None) -> bool:
    return bool(metric and ADDITIVE_METRIC_HINTS.search(_normalized(metric)))


def _parse_dashboard_dates(values: pd.Series) -> pd.Series:
    """Parse common spreadsheet date formats without guessing a business meaning."""

    return pd.to_datetime(values, errors="coerce", format="mixed")


def _time_series(df: pd.DataFrame, date_column: str, metric: str) -> pd.DataFrame:
    data = df[[date_column, metric]].copy()
    data[date_column] = _parse_dashboard_dates(data[date_column])
    data[metric] = pd.to_numeric(data[metric], errors="coerce")
    data = data.dropna()
    if len(data) < 2:
        return pd.DataFrame(columns=[date_column, metric])
    span_days = max((data[date_column].max() - data[date_column].min()).days, 1)
    rule = "D" if span_days <= 45 else "W-MON" if span_days <= 180 else "ME"
    aggregation = "sum" if _metric_is_additive(metric) else "mean"
    result = data.set_index(date_column)[metric].sort_index().resample(rule).agg(aggregation).reset_index()
    return result[result[metric].notna()]


def build_kpis(df: pd.DataFrame, schema: DashboardSchema) -> list[DashboardKpi]:
    cards = [DashboardKpi("Total records", format_compact_number(len(df)), "Rows in the current view")]
    metric = schema.primary_metric
    if metric and metric in df:
        values = pd.to_numeric(df[metric], errors="coerce").dropna()
        if not values.empty:
            percentage = _metric_is_percentage(metric)
            if _metric_is_additive(metric):
                cards.append(
                    DashboardKpi(
                        f"Total {humanize(metric)}",
                        format_compact_number(values.sum(), schema.currency, percentage),
                        f"Across {len(values):,} valid values",
                    )
                )
            else:
                cards.append(
                    DashboardKpi(
                        f"Average {humanize(metric)}",
                        format_compact_number(values.mean(), schema.currency, percentage),
                        f"Median {format_compact_number(values.median(), schema.currency, percentage)}",
                    )
                )
            cards.append(
                DashboardKpi(
                    f"Average {humanize(metric)}" if _metric_is_additive(metric) else f"Maximum {humanize(metric)}",
                    format_compact_number(values.mean() if _metric_is_additive(metric) else values.max(), schema.currency, percentage),
                    "Average of valid values" if _metric_is_additive(metric) else "Highest observed value",
                )
            )

    if schema.customer_column and schema.customer_column in df:
        cards.append(
            DashboardKpi(
                f"Unique {humanize(schema.customer_column)}",
                format_compact_number(df[schema.customer_column].nunique(dropna=True)),
                "Distinct non-empty values",
            )
        )
    elif schema.primary_dimension and schema.primary_dimension in df:
        cards.append(
            DashboardKpi(
                f"Unique {humanize(schema.primary_dimension)}",
                format_compact_number(df[schema.primary_dimension].nunique(dropna=True)),
                "Distinct non-empty values",
            )
        )

    if metric and schema.date_columns:
        series = _time_series(df, schema.date_columns[0], metric)
        if len(series) >= 2 and float(series.iloc[0][metric]) != 0:
            change = (float(series.iloc[-1][metric]) / float(series.iloc[0][metric])) - 1
            cards.append(
                DashboardKpi(
                    "Period change",
                    format_compact_number(change, percentage=True),
                    f"First to last observed {humanize(metric).lower()} period",
                    [float(value) for value in series[metric].tail(12)],
                )
            )
    return cards[:5]


def _sample_for_chart(df: pd.DataFrame, maximum: int = 5_000) -> tuple[pd.DataFrame, bool]:
    if len(df) <= maximum:
        return df, False
    return df.sample(maximum, random_state=42), True


def _chart_style(figure: go.Figure, title: str) -> go.Figure:
    figure.update_layout(
        title=dict(text=title, font=dict(size=17, color="#111827")),
        template="plotly_white",
        colorway=PALETTE,
        margin=dict(l=28, r=24, t=56, b=40),
        legend_title_text="",
        hovermode="closest",
        font=dict(family="Inter, Segoe UI, Arial", size=12, color="#111827"),
    )
    return figure


def build_charts(df: pd.DataFrame, schema: DashboardSchema) -> list[DashboardChart]:
    """Return only charts with enough real evidence to be readable."""

    charts: list[DashboardChart] = []
    metric = schema.primary_metric
    dimension = schema.primary_dimension

    if metric and schema.date_columns:
        date_column = schema.date_columns[0]
        trend = _time_series(df, date_column, metric)
        if len(trend) >= 2:
            aggregation = "Total" if _metric_is_additive(metric) else "Average"
            figure = px.line(
                trend,
                x=date_column,
                y=metric,
                markers=True,
                labels={date_column: humanize(date_column), metric: humanize(metric)},
                color_discrete_sequence=[PALETTE[0]],
            )
            charts.append(
                DashboardChart(
                    "trend",
                    f"{aggregation} {humanize(metric)} over time",
                    _chart_style(figure, f"{aggregation} {humanize(metric)} over time"),
                    f"Values are aggregated by observed period using {aggregation.lower()} {humanize(metric).lower()}.",
                )
            )

    if dimension and dimension in df:
        series = df[dimension].fillna("Missing").astype(str)
        if metric and metric in df:
            values = pd.to_numeric(df[metric], errors="coerce")
            grouped = pd.DataFrame({dimension: series, metric: values}).dropna(subset=[metric])
            aggregation = "sum" if _metric_is_additive(metric) else "mean"
            grouped = grouped.groupby(dimension, as_index=False)[metric].agg(aggregation).sort_values(metric, ascending=False).head(10)
            y_column = metric
            title = f"Top {humanize(dimension)} by {humanize(metric)}"
        else:
            grouped = series.value_counts().head(10).rename_axis(dimension).reset_index(name="records")
            y_column = "records"
            title = f"Top {humanize(dimension)} by record count"
        if not grouped.empty:
            figure = px.bar(
                grouped.sort_values(y_column),
                x=y_column,
                y=dimension,
                orientation="h",
                labels={dimension: humanize(dimension), y_column: humanize(y_column)},
                color_discrete_sequence=[PALETTE[1]],
            )
            charts.append(DashboardChart("category", title, _chart_style(figure, title), "Top 10 values are shown to keep comparisons legible."))

    if metric and metric in df:
        values = pd.to_numeric(df[metric], errors="coerce").dropna()
        if len(values) >= 2 and values.nunique() > 1:
            sample, sampled = _sample_for_chart(pd.DataFrame({metric: values}))
            title = f"Distribution of {humanize(metric)}"
            figure = px.histogram(
                sample,
                x=metric,
                nbins=min(40, max(12, int(math.sqrt(len(sample))))),
                marginal="box",
                labels={metric: humanize(metric)},
                color_discrete_sequence=[PALETTE[2]],
            )
            charts.append(DashboardChart("distribution", title, _chart_style(figure, title), "The box plot highlights the median and spread; it does not label values as errors.", sampled))

    numeric_pair = schema.numerical[:2]
    if len(numeric_pair) >= 2:
        x_column, y_column = numeric_pair
        pair = df[[x_column, y_column]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(pair) >= 10 and pair[x_column].nunique() > 1 and pair[y_column].nunique() > 1:
            correlation = float(pair[x_column].corr(pair[y_column]))
            sample, sampled = _sample_for_chart(pair)
            title = f"Relationship: {humanize(x_column)} and {humanize(y_column)}"
            figure = px.scatter(
                sample,
                x=x_column,
                y=y_column,
                opacity=0.65,
                labels={x_column: humanize(x_column), y_column: humanize(y_column)},
                color_discrete_sequence=[PALETTE[3]],
            )
            charts.append(
                DashboardChart(
                    "relationship",
                    title,
                    _chart_style(figure, title),
                    f"Pearson correlation is {correlation:.2f}. This describes association, not causation.",
                    sampled,
                )
            )
    return charts[:4]


def build_insights(full_df: pd.DataFrame, filtered_df: pd.DataFrame, schema: DashboardSchema) -> list[DashboardInsight]:
    insights: list[DashboardInsight] = []
    if len(filtered_df) != len(full_df):
        insights.append(
            DashboardInsight(
                "Filtered view",
                f"{len(filtered_df):,} of {len(full_df):,} records ({len(filtered_df) / max(len(full_df), 1):.1%}) match the active filters.",
            )
        )

    metric = schema.primary_metric
    dimension = schema.primary_dimension
    if dimension and dimension in filtered_df and not filtered_df.empty:
        if metric and metric in filtered_df:
            values = pd.to_numeric(filtered_df[metric], errors="coerce")
            groups = pd.DataFrame({dimension: filtered_df[dimension].fillna("Missing").astype(str), metric: values}).dropna(subset=[metric])
            if not groups.empty:
                aggregation = "sum" if _metric_is_additive(metric) else "mean"
                top = groups.groupby(dimension)[metric].agg(aggregation).sort_values(ascending=False)
                if not top.empty:
                    word = "total" if aggregation == "sum" else "average"
                    insights.append(DashboardInsight("Leading segment", f"{top.index[0]} has the highest {word} {humanize(metric).lower()} ({format_compact_number(top.iloc[0], schema.currency, _metric_is_percentage(metric))})."))
        else:
            top = filtered_df[dimension].fillna("Missing").astype(str).value_counts()
            if not top.empty:
                insights.append(DashboardInsight("Largest segment", f"{top.index[0]} contains {int(top.iloc[0]):,} records ({top.iloc[0] / max(len(filtered_df), 1):.1%} of the view)."))

    if metric and schema.date_columns and not filtered_df.empty:
        trend = _time_series(filtered_df, schema.date_columns[0], metric)
        if len(trend) >= 2 and float(trend.iloc[0][metric]) != 0:
            change = float(trend.iloc[-1][metric]) / float(trend.iloc[0][metric]) - 1
            direction = "increased" if change >= 0 else "decreased"
            insights.append(DashboardInsight("Period trend", f"{humanize(metric)} {direction} {abs(change):.1%} from the first to the last observed period."))

    if not filtered_df.empty:
        missing = filtered_df.isna().mean().sort_values(ascending=False)
        missing = missing[missing > 0]
        if not missing.empty:
            insights.append(DashboardInsight("Data completeness", f"{humanize(str(missing.index[0]))} has the highest missing rate at {missing.iloc[0]:.1%}.", "warning"))

    if len(schema.numerical) >= 2:
        pairs = filtered_df[schema.numerical].apply(pd.to_numeric, errors="coerce").corr()
        if not pairs.empty:
            upper = pairs.where(np.triu(np.ones(pairs.shape), k=1).astype(bool)).stack().abs().sort_values(ascending=False)
            if not upper.empty and upper.iloc[0] >= 0.5:
                x_column, y_column = upper.index[0]
                raw = float(pairs.loc[x_column, y_column])
                direction = "positive" if raw >= 0 else "negative"
                insights.append(DashboardInsight("Strongest numeric relationship", f"{humanize(x_column)} and {humanize(y_column)} show a {direction} Pearson correlation of {raw:.2f}; this is not evidence of causation."))

    return insights[:5]


def build_quality_summary(df: pd.DataFrame, schema: DashboardSchema) -> dict[str, int | float]:
    total_cells = max(len(df) * len(df.columns), 1)
    missing = int(df.isna().sum().sum())
    return {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "missing": missing,
        "duplicates": int(df.duplicated().sum()),
        "completeness": round((1 - missing / total_cells) * 100, 1),
        "numerical": len(schema.numerical),
        "categorical": len(schema.categorical),
        "date": len(schema.date_columns),
    }


def _filter_widget_keys() -> Iterable[str]:
    return (key for key in st.session_state if str(key).startswith("analytics_filter_"))


def clear_dashboard_filters() -> None:
    for key in list(_filter_widget_keys()):
        del st.session_state[key]
    st.session_state["analytics_table_page"] = 1


def apply_dashboard_filters(
    df: pd.DataFrame,
    date_column: str | None = None,
    date_range: tuple[date, date] | None = None,
    category_selections: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """Return the dashboard slice selected by date and category controls."""

    filtered = df.copy()
    if date_column and date_range and date_column in filtered:
        dates = _parse_dashboard_dates(filtered[date_column])
        valid_dates = dates.dropna()
        full_range = (valid_dates.min().date(), valid_dates.max().date()) if not valid_dates.empty else None
        # The default range represents the entire dataset, including rows whose
        # date is missing or invalid. Once a user narrows the range, only rows
        # with a matching valid date belong in that selected view.
        if full_range and date_range != full_range:
            start, end = date_range
            filtered = filtered[dates.dt.date.between(start, end, inclusive="both")]

    for column, selected_values in (category_selections or {}).items():
        if column in filtered:
            filtered = filtered[filtered[column].fillna("Missing").astype(str).isin(selected_values)]
    return filtered


def render_filter_panel(df: pd.DataFrame, schema: DashboardSchema) -> pd.DataFrame:
    """Render lightweight filters and apply them to a prepared source dataframe."""

    if df.empty:
        return df.copy()
    filter_dimensions = schema.categorical[:3]
    has_filters = bool(schema.date_columns or filter_dimensions)
    if not has_filters:
        st.info("No date or low-cardinality category fields were detected for interactive filters.", icon=":material/filter_alt_off:")
        return df.copy()

    with st.container(border=True):
        title_col, clear_col = st.columns([5, 1])
        title_col.markdown("#### Filters")
        clear_col.button("Clear", icon=":material/filter_alt_off:", key="analytics_clear_filters", on_click=clear_dashboard_filters, width="stretch")
        controls = st.columns(max(1, min(4, len(filter_dimensions) + (1 if schema.date_columns else 0))))
        control_index = 0
        selected_date_column: str | None = None
        selected_dates: tuple[date, date] | None = None
        if schema.date_columns:
            with controls[control_index]:
                selected_date_column = st.selectbox("Date field", schema.date_columns, key="analytics_filter_date_column")
                parsed = _parse_dashboard_dates(df[selected_date_column])
                valid = parsed.dropna()
                if not valid.empty:
                    selected = st.date_input(
                        "Date range",
                        value=(valid.min().date(), valid.max().date()),
                        min_value=valid.min().date(),
                        max_value=valid.max().date(),
                        key=f"analytics_filter_date_range_{selected_date_column}",
                    )
                    if isinstance(selected, tuple) and len(selected) == 2:
                        selected_dates = selected
                    elif isinstance(selected, list) and len(selected) == 2:
                        selected_dates = (selected[0], selected[1])
            control_index += 1

        selected_categories: dict[str, list[str]] = {}
        for column in filter_dimensions:
            with controls[control_index]:
                values = df[column].fillna("Missing").astype(str).value_counts().head(30).index.tolist()
                selected_categories[column] = st.multiselect(
                    humanize(column),
                    values,
                    default=values,
                    key=f"analytics_filter_values_{column}",
                )
            control_index += 1

    return apply_dashboard_filters(df, selected_date_column, selected_dates, selected_categories)


def render_kpi_cards(kpis: list[DashboardKpi]) -> None:
    if not kpis:
        return
    for index in range(0, len(kpis), 4):
        row = st.columns(min(4, len(kpis) - index))
        for column, kpi in zip(row, kpis[index : index + 4]):
            with column:
                kwargs: dict[str, Any] = {"label": kpi.label, "value": kpi.value, "help": kpi.detail, "border": True}
                if kpi.sparkline:
                    kwargs.update({"chart_data": kpi.sparkline, "chart_type": "line"})
                st.metric(**kwargs)
                st.caption(kpi.detail)


def render_chart_grid(charts: list[DashboardChart]) -> None:
    if not charts:
        st.info("No meaningful chart could be generated from the current view. Add a numerical, date, or categorical field to unlock more analysis.", icon=":material/insights:")
        return
    for index in range(0, len(charts), 2):
        left, right = st.columns(2)
        for column, chart in zip((left, right), charts[index : index + 2]):
            with column:
                with st.container(border=True):
                    st.plotly_chart(chart.figure, key=f"analytics_chart_{chart.key}", width="stretch", config={"displaylogo": False})
                    st.caption(chart.explanation + (" A deterministic 5,000-row sample is used for responsive rendering." if chart.sampled else ""))


def render_insights(insights: list[DashboardInsight]) -> None:
    with st.container(border=True):
        st.markdown("#### Key insights")
        if not insights:
            st.info("There is not enough variation in the current view to make evidence-based observations.", icon=":material/lightbulb:")
            return
        for insight in insights:
            icon = ":material/warning:" if insight.tone == "warning" else ":material/insights:"
            st.markdown(f"{icon} **{insight.title}.** {insight.detail}")


def render_quality_section(quality: dict[str, int | float]) -> None:
    with st.container(border=True):
        st.markdown("#### Data quality")
        st.progress(float(quality["completeness"]) / 100, text=f"{quality['completeness']:.1f}% complete across the processed dataset")
        first, second, third, fourth = st.columns(4)
        first.metric("Rows", f"{int(quality['rows']):,}")
        second.metric("Columns", f"{int(quality['columns']):,}")
        third.metric("Missing cells", f"{int(quality['missing']):,}")
        fourth.metric("Duplicate rows", f"{int(quality['duplicates']):,}")
        st.caption(
            f"Detected fields: {int(quality['numerical'])} numerical · {int(quality['categorical'])} categorical · {int(quality['date'])} date/time."
        )


def render_detailed_table(df: pd.DataFrame, sensitive_columns: list[str] | None = None) -> None:
    with st.container(border=True):
        st.markdown("#### Detailed data")
        if df.empty:
            st.info("No records match the current filters. Clear or broaden a filter to continue.", icon=":material/search_off:")
            return

        safe_preview = df
        if sensitive_columns and os.getenv("INSIGHTFORGE_MASK_SENSITIVE_PREVIEWS", "true").lower() != "false":
            safe_preview = mask_sensitive_preview(df, sensitive_columns)
            st.caption("Potentially sensitive columns are masked in this preview.")

        table_controls = st.columns([2, 2, 1, 1])
        query = table_controls[0].text_input("Search rows", placeholder="Search visible columns", key="analytics_table_search")
        visible_columns = table_controls[1].multiselect(
            "Visible columns",
            options=list(safe_preview.columns),
            default=list(safe_preview.columns),
            key="analytics_table_columns",
        )
        sort_options = ["Original order", *list(safe_preview.columns)]
        sort_column = table_controls[2].selectbox("Sort by", sort_options, key="analytics_table_sort")
        descending = table_controls[3].toggle("Descending", value=False, key="analytics_table_descending")
        if not visible_columns:
            st.warning("Select at least one column to display.", icon=":material/view_column:")
            return

        table = safe_preview.loc[:, visible_columns].copy()
        if query.strip():
            matches = table.astype("string").apply(lambda column: column.str.contains(query.strip(), case=False, na=False, regex=False)).any(axis=1)
            table = table[matches]
        if sort_column != "Original order":
            table = table.sort_values(sort_column, ascending=not descending, kind="stable", na_position="last")

        page_size = st.selectbox("Rows per page", [25, 50, 100], index=1, key="analytics_table_page_size")
        pages = max(1, math.ceil(len(table) / page_size))
        current_page = st.number_input("Page", min_value=1, max_value=pages, value=min(int(st.session_state.get("analytics_table_page", 1)), pages), step=1, key="analytics_table_page")
        start = (int(current_page) - 1) * page_size
        st.caption(f"Showing {min(start + 1, len(table)):,}–{min(start + page_size, len(table)):,} of {len(table):,} matching rows.")
        st.dataframe(table.iloc[start : start + page_size], hide_index=True, height=420, key="analytics_data_table")


def render_professional_analytics_dashboard(
    df: pd.DataFrame,
    *,
    file_name: str | None,
    analysis: dict[str, Any] | None,
    profile: dict[str, Any] | None,
    context: BusinessContext | None,
    last_updated: datetime | None,
) -> None:
    """Render the complete dashboard from the application's processed dataset."""

    if df is None or df.empty:
        st.info("Upload a non-empty dataset to generate an analytics dashboard.", icon=":material/upload_file:")
        return

    prepared = (analysis or {}).get("prepared_df")
    source = prepared.copy() if isinstance(prepared, pd.DataFrame) and not prepared.empty else df.copy()
    schema = build_dashboard_schema(source, analysis, context)
    updated_label = (last_updated or datetime.now()).strftime("%d %b %Y, %H:%M")

    st.subheader("Business Analytics Dashboard", icon=":material/analytics:")
    st.caption("Interactive overview of key business performance indicators, trends, and data quality.")
    header_left, header_right = st.columns([4, 1])
    header_left.caption(f"Dataset: **{file_name or 'Current dataset'}** · Last updated: {updated_label}")
    header_right.download_button(
        "Full CSV",
        dataframe_to_csv_bytes(source),
        file_name="insightforge_dashboard_data.csv",
        mime="text/csv",
        icon=":material/download:",
        key="analytics_export_unfiltered",
        width="stretch",
    )

    filtered = render_filter_panel(source, schema)
    if filtered.empty:
        st.warning("No records match the selected filters. Use Clear filters to return to the complete dataset.", icon=":material/filter_alt_off:")
        return

    export_left, export_right = st.columns([4, 1])
    export_left.caption(f"{len(filtered):,} records are included in this dashboard view. Chart hover, zoom, and legend controls support focused analysis.")
    export_right.download_button(
        "Export view",
        dataframe_to_csv_bytes(filtered),
        file_name="insightforge_filtered_dashboard_data.csv",
        mime="text/csv",
        icon=":material/download:",
        key="analytics_export_filtered",
        width="stretch",
    )

    render_kpi_cards(build_kpis(filtered, schema))
    render_chart_grid(build_charts(filtered, schema))
    render_insights(build_insights(source, filtered, schema))
    render_quality_section(build_quality_summary(source, schema))
    sensitive_columns = list((profile or {}).get("sensitive_columns", {}).keys())
    render_detailed_table(filtered, sensitive_columns)
