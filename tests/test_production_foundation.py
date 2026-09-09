from __future__ import annotations

import pandas as pd

from core.production import production_settings
from core.reference_data import evaluate_configured_reference_checks
from core.validation_templates import available_templates, build_template_rules


def test_local_mode_remains_the_safe_default(monkeypatch):
    monkeypatch.delenv("INSIGHTFORGE_STORAGE_BACKEND", raising=False)

    settings = production_settings()

    assert settings.backend == "local"
    assert settings.enabled is False


def test_marketing_template_adapts_to_available_columns():
    rules = build_template_rules("marketing_campaigns", ["campaign_id", "impressions", "clicks", "spend"])

    rendered = {(rule.column, rule.rule_type, rule.value) for rule in rules}

    assert ("campaign_id", "required", None) in rendered
    assert ("impressions", "cross_column_greater_equal", "clicks") in rendered
    assert any(rule.column == "spend" and rule.rule_type == "min_value" for rule in rules)


def test_industry_templates_always_include_the_baseline():
    template_keys = {template.key for template in available_templates("Retail")}

    assert {"baseline", "retail_operations"}.issubset(template_keys)


def test_reference_checks_make_no_network_request_when_unconfigured(monkeypatch):
    monkeypatch.delenv("INSIGHTFORGE_REFERENCE_CHECKS_JSON", raising=False)

    assert evaluate_configured_reference_checks(pd.DataFrame({"country_code": ["IN"]})) == []
