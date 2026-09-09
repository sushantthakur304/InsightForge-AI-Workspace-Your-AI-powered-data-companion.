"""Reusable, industry-aware validation policy templates.

Templates are intentionally conservative: a rule is offered only when the
uploaded dataset has a recognisable column for it.  They are starting points
for governance review, not a substitute for an organisation's approved policy.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from models.schemas import ValidationRule


@dataclass(frozen=True)
class TemplateRule:
    columns: tuple[str, ...]
    rule_type: str
    value: Any = None
    second_value: Any = None
    description: str | None = None


@dataclass(frozen=True)
class ValidationPolicyTemplate:
    key: str
    label: str
    description: str
    industries: tuple[str, ...]
    rules: tuple[TemplateRule, ...]


POLICY_TEMPLATES: tuple[ValidationPolicyTemplate, ...] = (
    ValidationPolicyTemplate(
        key="baseline",
        label="Baseline business data",
        description="Core identifiers, dates, contact formats, and non-negative quantities.",
        industries=("all",),
        rules=(
            TemplateRule(("id", "record_id", "customer_id", "order_id", "transaction_id"), "unique"),
            TemplateRule(("date", "created_at", "order_date", "transaction_date"), "required"),
            TemplateRule(("email", "email_address", "contact_email"), "regex", r"[^@\s]+@[^@\s]+\.[^@\s]+"),
            TemplateRule(("quantity", "units", "amount", "price", "value"), "min_value", 0),
        ),
    ),
    ValidationPolicyTemplate(
        key="retail_operations",
        label="Retail operations",
        description="Order, product, price, quantity, and fulfilment controls.",
        industries=("retail", "ecommerce", "e-commerce"),
        rules=(
            TemplateRule(("order_id", "order_number"), "unique"),
            TemplateRule(("order_date", "sale_date"), "required"),
            TemplateRule(("sku", "product_id", "product_code"), "required"),
            TemplateRule(("quantity", "units_sold"), "min_value", 0),
            TemplateRule(("unit_price", "price", "discount", "revenue"), "min_value", 0),
            TemplateRule(("currency", "currency_code"), "regex", r"[A-Z]{3}"),
        ),
    ),
    ValidationPolicyTemplate(
        key="finance_controls",
        label="Finance controls",
        description="Transaction traceability, amounts, account references, and ISO currency codes.",
        industries=("finance", "banking", "insurance", "accounting"),
        rules=(
            TemplateRule(("transaction_id", "journal_id", "entry_id"), "unique"),
            TemplateRule(("transaction_date", "posting_date", "date"), "required"),
            TemplateRule(("account_id", "account_code", "ledger_account"), "required"),
            TemplateRule(("amount", "debit", "credit", "balance"), "min_value", 0),
            TemplateRule(("currency", "currency_code"), "regex", r"[A-Z]{3}"),
        ),
    ),
    ValidationPolicyTemplate(
        key="healthcare_operations",
        label="Healthcare operations",
        description="Operational completeness and safe demographic ranges; not a clinical compliance certification.",
        industries=("healthcare", "health", "life sciences"),
        rules=(
            TemplateRule(("patient_id", "member_id", "encounter_id"), "required"),
            TemplateRule(("encounter_date", "admission_date", "service_date"), "required"),
            TemplateRule(("age",), "range", 0, 130),
            TemplateRule(("sex", "gender"), "category_list", ["female", "male", "nonbinary", "unknown", "other"]),
        ),
    ),
    ValidationPolicyTemplate(
        key="marketing_campaigns",
        label="Marketing campaigns",
        description="Campaign traceability, spend sanity, and click/impression consistency.",
        industries=("marketing", "advertising", "media"),
        rules=(
            TemplateRule(("campaign_id", "campaign_code"), "required"),
            TemplateRule(("campaign_id", "campaign_code"), "unique"),
            TemplateRule(("impressions",), "min_value", 0),
            TemplateRule(("clicks",), "min_value", 0),
            TemplateRule(("conversions",), "min_value", 0),
            TemplateRule(("spend",), "min_value", 0),
            TemplateRule(("impressions",), "cross_column_greater_equal", ("clicks",)),
            TemplateRule(("email", "email_address"), "regex", r"[^@\s]+@[^@\s]+\.[^@\s]+"),
        ),
    ),
    ValidationPolicyTemplate(
        key="supply_chain",
        label="Supply chain and inventory",
        description="SKU, inventory, lead-time, and reorder-point controls.",
        industries=("supply chain", "logistics", "manufacturing", "inventory"),
        rules=(
            TemplateRule(("sku", "item_id", "product_code"), "required"),
            TemplateRule(("sku", "item_id", "product_code"), "unique"),
            TemplateRule(("inventory_quantity", "on_hand", "quantity"), "min_value", 0),
            TemplateRule(("reorder_point", "safety_stock"), "min_value", 0),
            TemplateRule(("lead_time_days", "lead_time"), "range", 0, 365),
        ),
    ),
)


def available_templates(industry: str | None = None) -> list[ValidationPolicyTemplate]:
    """Return baseline plus templates relevant to an optional industry label."""

    normalized = (industry or "").strip().lower()
    selected = [template for template in POLICY_TEMPLATES if "all" in template.industries]
    if normalized:
        selected.extend(
            template
            for template in POLICY_TEMPLATES
            if "all" not in template.industries and any(label in normalized for label in template.industries)
        )
    return selected or [POLICY_TEMPLATES[0]]


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _matching_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    indexed = {_normalise(column): column for column in columns}
    for candidate in candidates:
        if candidate in indexed:
            return indexed[candidate]
    return None


def build_template_rules(template_key: str, columns: list[str]) -> list[ValidationRule]:
    """Build rules whose semantic column names exist in the uploaded dataset."""

    template = next((item for item in POLICY_TEMPLATES if item.key == template_key), None)
    if template is None:
        raise ValueError(f"Unknown validation template: {template_key}")

    rules: list[ValidationRule] = []
    for spec in template.rules:
        column = _matching_column(columns, spec.columns)
        if column is None:
            continue
        value = spec.value
        if spec.rule_type == "cross_column_greater_equal" and isinstance(spec.value, tuple):
            value = _matching_column(columns, spec.value)
            if value is None:
                continue
        rules.append(
            ValidationRule(
                id=f"{template.key}-{uuid.uuid4().hex[:8]}",
                column=column,
                rule_type=spec.rule_type,  # type: ignore[arg-type]
                value=value,
                second_value=spec.second_value,
                description=spec.description or f"{template.label} policy: {spec.rule_type.replace('_', ' ')}.",
            )
        )
    return rules
