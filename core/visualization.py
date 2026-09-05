from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from models.schemas import BusinessContext


PALETTE = ["#2563eb", "#0f766e", "#4f46e5", "#f59e0b", "#dc2626", "#0891b2", "#7c3aed", "#16a34a"]


@dataclass
class ChartSpec:
    title: str
    figure: go.Figure
    chart_type: str
    source_columns: list[str]
    interpretation: str
    sampled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "figure": self.figure,
            "chart_type": self.chart_type,
            "source_columns": self.source_columns,
            "interpretation": self.interpretation,
            "sampled": self.sampled,
        }


def _style(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=title,
        colorway=PALETTE,
        template="plotly_white",
        margin=dict(l=30, r=24, t=56, b=42),
        legend_title_text="",
        font=dict(family="Inter, Segoe UI, Arial", size=13, color="#111827"),
        hovermode="closest",
    )
    return fig


def _sample_for_viz(df: pd.DataFrame, max_rows: int = 5000) -> tuple[pd.DataFrame, bool]:
    if len(df) <= max_rows:
        return df, False
    return df.sample(max_rows, random_state=42), True


def _top_categories(series: pd.Series, limit: int = 12) -> pd.Series:
    counts = series.fillna("Missing").astype(str).value_counts()
    if len(counts) <= limit:
        return counts
    top = counts.head(limit - 1)
    top["Other"] = counts.iloc[limit - 1 :].sum()
    return top


def build_dashboard_figures(
    df: pd.DataFrame,
    profile: dict[str, Any],
    quality: dict[str, Any],
    analysis: dict[str, Any],
    context: BusinessContext | None = None,
) -> list[dict[str, Any]]:
    context = context or BusinessContext()
    charts: list[ChartSpec] = []
    groups = analysis.get("column_groups", {})
    numerical = groups.get("numerical", [])
    categorical = groups.get("categorical", [])
    date_cols = groups.get("date", [])
    target = analysis.get("target")

    missing = pd.Series(profile.get("missing_counts", {})).sort_values(ascending=False)
    missing = missing[missing > 0]
    if not missing.empty:
        missing_frame = missing.rename_axis("column").reset_index(name="missing_count")
        fig = px.bar(
            missing_frame.head(20),
            x="column",
            y="missing_count",
            labels={"column": "Column", "missing_count": "Missing values"},
            color_discrete_sequence=[PALETTE[1]],
        )
        charts.append(
            ChartSpec(
                "Missing Values by Column",
                _style(fig, "Missing Values by Column"),
                "bar",
                missing.index.tolist(),
                f"{missing.index[0]} has the most missing values ({int(missing.iloc[0])}).",
            )
        )

    if numerical:
        column = target if target in numerical else numerical[0]
        sample, sampled = _sample_for_viz(df)
        fig = px.histogram(
            sample,
            x=column,
            nbins=30,
            marginal="box",
            labels={column: column},
            color_discrete_sequence=[PALETTE[0]],
        )
        charts.append(
            ChartSpec(
                f"Distribution of {column}",
                _style(fig, f"Distribution of {column}"),
                "histogram",
                [column],
                f"The chart shows the spread, skew, and extreme values for {column}.",
                sampled=sampled,
            )
        )

    if len(numerical) >= 2:
        corr = analysis.get("pearson_correlation")
        if isinstance(corr, pd.DataFrame) and not corr.empty:
            fig = px.imshow(
                corr,
                text_auto=".2f",
                aspect="auto",
                color_continuous_scale="RdBu_r",
                zmin=-1,
                zmax=1,
                labels=dict(color="Pearson r"),
            )
            charts.append(
                ChartSpec(
                    "Correlation Matrix",
                    _style(fig, "Correlation Matrix"),
                    "heatmap",
                    numerical,
                    "Correlations summarize linear association and should not be interpreted as causation.",
                )
            )

        corr_pairs = corr.abs().where(~np.eye(corr.shape[0], dtype=bool)).stack().sort_values(ascending=False) if isinstance(corr, pd.DataFrame) and not corr.empty else pd.Series(dtype=float)
        if not corr_pairs.empty:
            x_col, y_col = corr_pairs.index[0]
            sample, sampled = _sample_for_viz(df[[x_col, y_col]].dropna())
            fig = px.scatter(
                sample,
                x=x_col,
                y=y_col,
                labels={x_col: x_col, y_col: y_col},
                color_discrete_sequence=[PALETTE[2]],
            )
            if len(sample) >= 10:
                xy = sample[[x_col, y_col]].apply(pd.to_numeric, errors="coerce").dropna()
                if len(xy) >= 10 and xy[x_col].nunique() > 1:
                    slope, intercept = np.polyfit(xy[x_col], xy[y_col], deg=1)
                    x_line = np.linspace(float(xy[x_col].min()), float(xy[x_col].max()), 50)
                    y_line = slope * x_line + intercept
                    fig.add_scatter(
                        x=x_line,
                        y=y_line,
                        mode="lines",
                        name="Linear fit",
                        line=dict(color=PALETTE[3], width=2),
                    )
            charts.append(
                ChartSpec(
                    f"Relationship: {x_col} vs {y_col}",
                    _style(fig, f"Relationship: {x_col} vs {y_col}"),
                    "scatter",
                    [x_col, y_col],
                    f"{x_col} and {y_col} have one of the strongest observed numeric relationships.",
                    sampled=sampled,
                )
            )

    if categorical:
        dimension = next((col for col in context.important_dimensions if col in categorical), categorical[0])
        counts = _top_categories(df[dimension])
        counts_frame = counts.rename_axis(dimension).reset_index(name="count")
        fig = px.bar(
            counts_frame,
            x=dimension,
            y="count",
            labels={dimension: dimension, "count": "Rows"},
            color=dimension,
            color_discrete_sequence=PALETTE,
        )
        fig.update_layout(showlegend=False)
        charts.append(
            ChartSpec(
                f"Top Categories in {dimension}",
                _style(fig, f"Top Categories in {dimension}"),
                "bar",
                [dimension],
                f"{counts.index[0]} is the largest category by row count.",
            )
        )

    pareto = analysis.get("pareto")
    if isinstance(pareto, pd.DataFrame) and not pareto.empty and target:
        dimension = pareto.columns[0]
        top = pareto.head(15)
        fig = go.Figure()
        fig.add_bar(x=top[dimension].astype(str), y=top[target], name=target, marker_color=PALETTE[0])
        fig.add_scatter(
            x=top[dimension].astype(str),
            y=top["cumulative_pct"],
            name="Cumulative %",
            yaxis="y2",
            mode="lines+markers",
            marker_color=PALETTE[3],
        )
        fig.update_layout(
            yaxis=dict(title=target),
            yaxis2=dict(title="Cumulative %", overlaying="y", side="right", range=[0, 105]),
        )
        charts.append(
            ChartSpec(
                f"Pareto Analysis of {target}",
                _style(fig, f"Pareto Analysis of {target}"),
                "pareto",
                [dimension, target],
                "The bars show contribution by segment; the line shows cumulative contribution.",
            )
        )

    if date_cols and numerical:
        date_col = context.date_column if context.date_column in date_cols else date_cols[0]
        metric = target if target in numerical else numerical[0]
        temp = df[[date_col, metric]].dropna().copy()
        if not temp.empty:
            temp[date_col] = pd.to_datetime(temp[date_col], errors="coerce")
            temp = temp.dropna()
        if len(temp) >= 2:
            monthly = temp.set_index(date_col).sort_index()[metric].resample("ME").sum().reset_index()
            fig = px.line(monthly, x=date_col, y=metric, markers=True, labels={date_col: "Period", metric: metric})
            charts.append(
                ChartSpec(
                    f"Trend in {metric}",
                    _style(fig, f"Trend in {metric}"),
                    "line",
                    [date_col, metric],
                    f"Monthly aggregation shows how {metric} changed over time.",
                )
            )

    anomalies = analysis.get("anomalies")
    if isinstance(anomalies, pd.DataFrame) and not anomalies.empty and numerical:
        first = numerical[0]
        second = numerical[1] if len(numerical) > 1 else numerical[0]
        if first in anomalies.columns and second in anomalies.columns:
            sample, sampled = _sample_for_viz(df[[first, second]].dropna())
            fig = px.scatter(sample, x=first, y=second, labels={first: first, second: second}, opacity=0.55)
            fig.add_scatter(
                x=anomalies[first],
                y=anomalies[second],
                mode="markers",
                name="Anomaly",
                marker=dict(color=PALETTE[4], size=11, symbol="x"),
            )
            charts.append(
                ChartSpec(
                    "Detected Anomalies",
                    _style(fig, "Detected Anomalies"),
                    "scatter",
                    [first, second],
                    f"{len(anomalies)} records were flagged for analytical review.",
                    sampled=sampled,
                )
            )

    return [chart.to_dict() for chart in charts]
