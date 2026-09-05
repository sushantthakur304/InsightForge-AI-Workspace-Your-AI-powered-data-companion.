from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BusinessContext(BaseModel):
    """Optional user context used to tailor profiling, charts, and insights."""

    company_or_project: str | None = None
    industry: str | None = None
    dataset_description: str | None = None
    business_objective: str | None = None
    target_variable: str | None = None
    currency: str | None = None
    country_or_market: str | None = None
    date_column: str | None = None
    important_dimensions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class FileValidationResult(BaseModel):
    is_valid: bool
    file_name: str
    extension: str
    size_bytes: int
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DataIssue(BaseModel):
    id: str
    category: str
    severity: Literal["low", "medium", "high"]
    title: str
    description: str
    column: str | None = None
    affected_count: int = 0
    affected_rows: list[int] = Field(default_factory=list)
    suggested_action: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class QualityScores(BaseModel):
    overall: float
    completeness: float
    validity: float
    consistency: float
    uniqueness: float
    accuracy_indicators: float
    data_type_reliability: float
    explanation: str


class CleaningRecommendation(BaseModel):
    id: str
    operation: str
    action_type: str
    column: str | None = None
    selected_action: str
    options: list[str] = Field(default_factory=list)
    reason: str
    risk: str
    affected_count: int
    params: dict[str, Any] = Field(default_factory=dict)
    enabled_by_default: bool = True


class AuditEntry(BaseModel):
    operation_name: str
    column_affected: str | None = None
    original_issue: str
    selected_action: str
    affected_records: int
    before_after_examples: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    warning_or_assumption: str | None = None
    user_approval_status: Literal["approved", "rejected", "pending"] = "approved"


class ValidationRule(BaseModel):
    id: str
    column: str
    rule_type: Literal[
        "required",
        "unique",
        "min_value",
        "max_value",
        "range",
        "category_list",
        "date_range",
        "regex",
        "cross_column_greater_equal",
    ]
    value: Any = None
    second_value: Any = None
    description: str | None = None

