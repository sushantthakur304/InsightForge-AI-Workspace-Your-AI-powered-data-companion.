from __future__ import annotations

import json
import os
from typing import Any, Protocol

import pandas as pd

from models.schemas import BusinessContext


INSIGHT_SECTIONS = [
    "Executive Summary",
    "Key Findings",
    "Trends",
    "Risks and Anomalies",
    "Opportunities",
    "Recommended Actions",
    "Data Limitations",
    "Suggested Further Analysis",
]


class InsightProvider(Protocol):
    def generate(
        self,
        profile: dict[str, Any],
        quality: dict[str, Any],
        analysis: dict[str, Any],
        context: BusinessContext,
    ) -> dict[str, Any]:
        ...


def _round(value: Any, digits: int = 2) -> Any:
    try:
        return round(float(value), digits)
    except Exception:
        return value


def _strongest_correlation(correlation: pd.DataFrame) -> dict[str, Any] | None:
    if not isinstance(correlation, pd.DataFrame) or correlation.empty:
        return None
    values = correlation.where(~pd.DataFrame(
        [[i == j for j in correlation.columns] for i in correlation.index],
        index=correlation.index,
        columns=correlation.columns,
    ))
    stacked = values.abs().stack().sort_values(ascending=False)
    if stacked.empty:
        return None
    left, right = stacked.index[0]
    return {"left": left, "right": right, "value": _round(correlation.loc[left, right], 3)}


def _analysis_payload(profile: dict[str, Any], quality: dict[str, Any], analysis: dict[str, Any], context: BusinessContext) -> dict[str, Any]:
    numeric_summary = analysis.get("numeric_summary")
    group_comparison = analysis.get("group_comparison")
    anomalies = analysis.get("anomalies")
    return {
        "business_context": context.model_dump(),
        "profile": {
            "rows": profile.get("row_count"),
            "columns": profile.get("column_count"),
            "column_types": profile.get("column_types"),
            "missing_percentages": profile.get("missing_percentages"),
            "exact_duplicate_rows": profile.get("exact_duplicate_rows"),
        },
        "quality": quality.get("scores"),
        "quality_issues": quality.get("issues", [])[:25],
        "kpis": analysis.get("kpis", {}),
        "numeric_summary": numeric_summary.head(20).to_dict("records") if isinstance(numeric_summary, pd.DataFrame) else [],
        "group_comparison": group_comparison.head(15).to_dict("records") if isinstance(group_comparison, pd.DataFrame) and not group_comparison.empty else [],
        "time_series": analysis.get("time_series", [])[-12:],
        "anomalies": {
            "count": int(len(anomalies)) if isinstance(anomalies, pd.DataFrame) else 0,
            "columns": list(anomalies.columns[:10]) if isinstance(anomalies, pd.DataFrame) else [],
        },
        "inferential_tests": analysis.get("inferential_tests", []),
    }


class RuleBasedInsightProvider:
    def generate(
        self,
        profile: dict[str, Any],
        quality: dict[str, Any],
        analysis: dict[str, Any],
        context: BusinessContext,
    ) -> dict[str, Any]:
        scores = quality.get("scores", {})
        issues = quality.get("issues", [])
        kpis = analysis.get("kpis", {})
        target = analysis.get("target")
        company = context.company_or_project or "this dataset"

        sections: dict[str, list[str]] = {section: [] for section in INSIGHT_SECTIONS}
        recommendations: list[dict[str, Any]] = []

        sections["Executive Summary"].append(
            f"{company} contains {profile.get('row_count', 0):,} rows and {profile.get('column_count', 0):,} columns. "
            f"The data-quality score is {_round(scores.get('overall'))}/100."
        )
        sections["Executive Summary"].append(
            "The assessment is based on completeness, validity, consistency, uniqueness, accuracy indicators, and data-type reliability. "
            "Real-world accuracy has not been verified against external reference data."
        )

        missing_percentages = profile.get("missing_percentages", {})
        if missing_percentages:
            top_missing_col, top_missing_pct = max(missing_percentages.items(), key=lambda item: item[1])
            sections["Key Findings"].append(
                f"{top_missing_col} has the highest missing-value rate at {_round(top_missing_pct)}%."
            )
            if top_missing_pct >= 10:
                recommendations.append(
                    {
                        "recommendation": f"Resolve missingness in {top_missing_col}.",
                        "evidence": f"{top_missing_col} is missing in {_round(top_missing_pct)}% of rows.",
                        "proposed_action": "Review source-system capture rules and approve an imputation or exclusion policy before analysis.",
                        "expected_business_benefit": "More reliable KPI calculations and segment comparisons.",
                        "priority": "high" if top_missing_pct >= 25 else "medium",
                        "difficulty": "medium",
                        "monitoring_kpi": f"{top_missing_col} missing-value rate",
                        "confidence": "high",
                    }
                )

        duplicates = profile.get("exact_duplicate_rows", 0)
        if duplicates:
            sections["Key Findings"].append(f"{duplicates:,} exact duplicate rows were detected.")
            recommendations.append(
                {
                    "recommendation": "Approve duplicate handling for exact matches.",
                    "evidence": f"{duplicates:,} rows duplicate an earlier record exactly.",
                    "proposed_action": "Keep the first or last record after confirming repeated rows are not valid business events.",
                    "expected_business_benefit": "Prevents inflated counts, totals, and conversion metrics.",
                    "priority": "medium",
                    "difficulty": "low",
                    "monitoring_kpi": "Exact duplicate row count",
                    "confidence": "high",
                }
            )

        if target:
            target_sum = kpis.get(f"{target}_sum")
            target_mean = kpis.get(f"{target}_mean")
            if target_sum is not None:
                sections["Key Findings"].append(
                    f"{target} totals {_round(target_sum)} with an average of {_round(target_mean)} per row."
                )

        time_series = analysis.get("time_series", [])
        if len(time_series) >= 2 and target:
            previous = time_series[-2].get(target)
            latest = time_series[-1].get(target)
            if previous not in (None, 0) and latest is not None:
                change = (latest - previous) / previous * 100
                sections["Trends"].append(
                    f"The latest period changed by {_round(change)}% versus the prior period for {target}."
                )
                if abs(change) >= 15:
                    recommendations.append(
                        {
                            "recommendation": f"Investigate the latest-period movement in {target}.",
                            "evidence": f"{target} changed {_round(change)}% versus the previous period.",
                            "proposed_action": "Break the change down by the selected dimensions and confirm whether it reflects operations, seasonality, or data quality.",
                            "expected_business_benefit": "Faster diagnosis of revenue, demand, or performance shifts.",
                            "priority": "high" if abs(change) >= 30 else "medium",
                            "difficulty": "medium",
                            "monitoring_kpi": f"Monthly {target} growth rate",
                            "confidence": "medium",
                        }
                    )
        else:
            sections["Trends"].append("No reliable time trend was calculated because a usable date and metric combination was not available.")

        group_comparison = analysis.get("group_comparison")
        if isinstance(group_comparison, pd.DataFrame) and not group_comparison.empty and target:
            dimension = group_comparison.columns[0]
            top = group_comparison.iloc[0]
            contribution = top.get("contribution_pct", None)
            sections["Opportunities"].append(
                f"{top[dimension]} is the top {dimension} segment by {target}, contributing {_round(contribution)}% of the observed total."
            )
            recommendations.append(
                {
                    "recommendation": f"Prioritize analysis of the top {dimension} segment.",
                    "evidence": f"{top[dimension]} contributes {_round(contribution)}% of {target}.",
                    "proposed_action": "Compare this segment's drivers, margins, and data quality against lower-performing segments.",
                    "expected_business_benefit": "Focuses follow-up effort where the measured impact is largest.",
                    "priority": "medium",
                    "difficulty": "medium",
                    "monitoring_kpi": f"{target} contribution by {dimension}",
                    "confidence": "high",
                }
            )

        anomalies = analysis.get("anomalies")
        anomaly_count = int(len(anomalies)) if isinstance(anomalies, pd.DataFrame) else 0
        if anomaly_count:
            sections["Risks and Anomalies"].append(
                f"{anomaly_count:,} records were flagged as potential anomalies using the configured analytical method."
            )
            recommendations.append(
                {
                    "recommendation": "Review anomaly records before excluding them.",
                    "evidence": f"{anomaly_count:,} rows were flagged by IQR or Isolation Forest.",
                    "proposed_action": "Confirm whether flagged records are data-entry errors, one-time business events, or meaningful edge cases.",
                    "expected_business_benefit": "Protects analysis from distortions without discarding legitimate exceptional events.",
                    "priority": "medium",
                    "difficulty": "low",
                    "monitoring_kpi": "Confirmed anomaly rate",
                    "confidence": "medium",
                }
            )
        else:
            sections["Risks and Anomalies"].append("No anomaly records were flagged by the current analytical checks.")

        correlation = _strongest_correlation(analysis.get("pearson_correlation"))
        if correlation:
            sections["Key Findings"].append(
                f"The strongest observed Pearson correlation is between {correlation['left']} and {correlation['right']} (r={correlation['value']}). "
                "This is evidence of association, not causation."
            )

        if issues:
            severe = [issue for issue in issues if issue.get("severity") in {"high", "medium"}]
            sections["Data Limitations"].append(
                f"{len(severe)} medium/high-priority data-quality issues may affect conclusions."
            )
        else:
            sections["Data Limitations"].append("No major data-quality issues were detected by the automated checks.")

        tests = analysis.get("inferential_tests", [])
        if tests:
            for test in tests[:3]:
                sections["Suggested Further Analysis"].append(
                    f"{test['test']} on {', '.join(test['columns'])}: p-value={_round(test.get('p_value'))}; {test['plain_language']}"
                )
        else:
            sections["Suggested Further Analysis"].append(
                "Add a clear KPI, date field, and business dimensions to unlock stronger trend, cohort, and statistical testing."
            )

        sections["Recommended Actions"] = [
            f"{item['priority'].title()} priority: {item['recommendation']} Evidence: {item['evidence']}"
            for item in recommendations
        ] or ["No immediate business recommendation passed the evidence threshold."]

        return {
            "provider": "rule_based",
            "sections": sections,
            "recommendations": recommendations,
            "assumptions": [
                "Insights use aggregate statistics and quality metrics only.",
                "Correlation and statistical association do not prove causation.",
                "External real-world accuracy has not been verified.",
            ],
        }


class OpenAIInsightProvider:
    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    def generate(
        self,
        profile: dict[str, Any],
        quality: dict[str, Any],
        analysis: dict[str, Any],
        context: BusinessContext,
    ) -> dict[str, Any]:
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - optional dependency path
            fallback = RuleBasedInsightProvider().generate(profile, quality, analysis, context)
            fallback["provider"] = f"rule_based_fallback_openai_import_failed:{exc}"
            return fallback

        if not os.getenv("OPENAI_API_KEY"):
            return RuleBasedInsightProvider().generate(profile, quality, analysis, context)

        client = OpenAI()
        payload = _analysis_payload(profile, quality, analysis, context)
        prompt = (
            "Generate evidence-based business insights as strict JSON with keys sections, recommendations, and assumptions. "
            "Use only the supplied aggregate payload. Do not invent numbers, predictions, or causal claims. "
            "Each recommendation must include recommendation, evidence, proposed_action, expected_business_benefit, "
            "priority, difficulty, monitoring_kpi, and confidence."
        )
        try:
            response = client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, default=str)},
                ],
                temperature=0.2,
            )
            text = response.output_text
            parsed = json.loads(text)
            parsed["provider"] = "openai"
            return parsed
        except Exception as exc:  # pragma: no cover - depends on external service
            fallback = RuleBasedInsightProvider().generate(profile, quality, analysis, context)
            fallback["provider"] = f"rule_based_fallback_openai_error:{exc}"
            return fallback


def generate_insights(
    profile: dict[str, Any],
    quality: dict[str, Any],
    analysis: dict[str, Any],
    context: BusinessContext | None = None,
) -> dict[str, Any]:
    context = context or BusinessContext()
    provider_name = os.getenv("INSIGHTFORGE_AI_PROVIDER", "rule_based").lower()
    provider: InsightProvider
    if provider_name == "openai" and os.getenv("OPENAI_API_KEY"):
        provider = OpenAIInsightProvider()
    else:
        provider = RuleBasedInsightProvider()
    result = provider.generate(profile, quality, analysis, context)
    for section in INSIGHT_SECTIONS:
        result.setdefault("sections", {}).setdefault(section, [])
    result.setdefault("recommendations", [])
    result.setdefault("assumptions", [])
    return result

