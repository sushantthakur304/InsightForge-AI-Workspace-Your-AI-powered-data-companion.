"""Opt-in checks against deployment-configured reference data sources.

Reference sources are configured by an operator, not supplied by an end user.
That keeps the feature useful for accuracy checks without turning the app into
an arbitrary server-side request proxy.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests

from models.schemas import DataIssue


def _configured_checks() -> list[dict[str, Any]]:
    raw = os.getenv("INSIGHTFORGE_REFERENCE_CHECKS_JSON", "").strip()
    if not raw:
        return []
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("INSIGHTFORGE_REFERENCE_CHECKS_JSON must contain a JSON list.")
    return [item for item in parsed if isinstance(item, dict)]


def _extract_items(payload: Any, path: str | None) -> list[Any]:
    current = payload
    for part in (path or "").split("."):
        if not part:
            continue
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"The response does not contain '{path}'.")
        current = current[part]
    return current if isinstance(current, list) else []


def _reference_values(check: dict[str, Any]) -> set[str]:
    url = str(check.get("url") or "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Reference data URLs must use HTTPS.")
    response = requests.get(url, timeout=10, allow_redirects=False)
    response.raise_for_status()
    items = _extract_items(response.json(), check.get("items_path"))
    value_field = str(check.get("value_field") or "id")
    values = {
        str(item.get(value_field)).strip().casefold()
        for item in items
        if isinstance(item, dict) and item.get(value_field) is not None
    }
    if not values:
        raise ValueError("The reference source returned no usable values.")
    return values


def evaluate_configured_reference_checks(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Return traceable issues for values absent from trusted reference data.

    A failed source produces a configuration/availability issue rather than an
    accuracy claim.  No network request is made unless an operator configured
    at least one source in ``INSIGHTFORGE_REFERENCE_CHECKS_JSON``.
    """

    issues: list[dict[str, Any]] = []
    try:
        checks = _configured_checks()
    except (ValueError, json.JSONDecodeError) as exc:
        return [
            DataIssue(
                id="reference-configuration-error",
                category="accuracy",
                severity="medium",
                title="External reference checks are not configured correctly",
                description=f"No real-world accuracy conclusion was made: {exc}",
                suggested_action="Correct INSIGHTFORGE_REFERENCE_CHECKS_JSON and run the profile again.",
            ).model_dump()
        ]
    for check in checks:
        label = str(check.get("label") or "External reference check")
        column = str(check.get("column") or "")
        source_url = str(check.get("url") or "")
        if column not in df.columns:
            issues.append(
                DataIssue(
                    id=f"reference-missing-column:{label}:{column}",
                    category="accuracy",
                    severity="high",
                    title=f"{label} cannot run",
                    description=f"The configured column '{column}' is not present in this dataset.",
                    column=column or None,
                    suggested_action="Update the reference-check configuration or map the dataset column.",
                ).model_dump()
            )
            continue
        try:
            approved = _reference_values(check)
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            issues.append(
                DataIssue(
                    id=f"reference-unavailable:{label}:{column}",
                    category="accuracy",
                    severity="medium",
                    title=f"{label} is unavailable",
                    description=f"No real-world accuracy conclusion was made because the source could not be verified: {exc}",
                    column=column,
                    suggested_action="Review the approved source URL and retry the check.",
                    evidence={"source_url": source_url},
                ).model_dump()
            )
            continue

        values = df[column].astype("string").str.strip().str.casefold()
        mask = df[column].notna() & ~values.isin(approved)
        affected = int(mask.sum())
        if affected:
            issues.append(
                DataIssue(
                    id=f"reference-mismatch:{label}:{column}",
                    category="accuracy",
                    severity="high" if affected / max(len(df), 1) >= 0.1 else "medium",
                    title=f"{label} found values absent from the reference source",
                    description="These values were not found in the configured external reference snapshot. This is a review signal, not proof that a record is incorrect.",
                    column=column,
                    affected_count=affected,
                    affected_rows=[int(index) for index in mask[mask].index[:100]],
                    suggested_action="Review source freshness, matching rules, and the affected records.",
                    evidence={
                        "source_url": source_url,
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "reference_value_count": len(approved),
                    },
                ).model_dump()
            )
    return issues
