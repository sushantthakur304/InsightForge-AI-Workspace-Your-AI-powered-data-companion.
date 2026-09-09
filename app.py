from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime
from io import BytesIO
from numbers import Number
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from components.analytics_dashboard import render_professional_analytics_dashboard
from components.ui import STEP_LABELS, app_header, inject_global_styles, metric_card, render_sidebar_brand, step_indicator, upload_showcase
from core.cleaning import apply_cleaning_pipeline, cleaning_log_to_dataframe, recommend_cleaning_actions
from core.dataset_store import (
    StoredDatasetRecord,
    delete_stored_dataset,
    init_dataset_store,
    list_stored_datasets,
    load_stored_dataset,
    save_dataset_bytes,
)
from core.exporting import (
    audit_log_json,
    build_excel_analysis_workbook,
    chart_images_zip,
    cleaning_configuration_json,
    dataframe_to_csv_bytes,
    dataframe_to_parquet_bytes,
    quality_report_json,
)
from core.history import init_history_db, record_analysis_run
from core.ingestion import IngestionResult, load_dataset, list_excel_sheets
from core.insights import generate_insights
from core.profiler import assess_data_quality, profile_dataframe
from core.production import (
    ProductionConfigurationError,
    UserIdentity,
    active_gateway,
    configure_request_context,
    production_enabled,
    production_settings,
    set_active_workspace,
)
from core.reference_data import evaluate_configured_reference_checks
from core.reporting import build_html_report, generate_pdf_report
from core.security import mask_sensitive_preview, validate_upload
from core.statistics import analyze_dataframe
from core.validation import evaluate_validation_rules
from core.validation_templates import available_templates, build_template_rules
from models.schemas import BusinessContext, ValidationRule


load_dotenv()


@st.cache_data(show_spinner=False)
def cached_profile(df: pd.DataFrame) -> dict[str, Any]:
    return profile_dataframe(df)


@st.cache_data(show_spinner=False)
def cached_quality(df: pd.DataFrame, context_payload: dict[str, Any]) -> dict[str, Any]:
    return assess_data_quality(df, BusinessContext(**context_payload))


@st.cache_data(show_spinner=False)
def cached_analysis(df: pd.DataFrame, context_payload: dict[str, Any]) -> dict[str, Any]:
    return analyze_dataframe(df, BusinessContext(**context_payload))


def init_state() -> None:
    defaults = {
        "step": 0,
        "theme_mode": "Light",
        "context": BusinessContext().model_dump(),
        "ingestion": None,
        "active_dataset_key": None,
        "sheet_workspaces": {},
        "original_df": None,
        "cleaned_df": None,
        "profile": None,
        "quality": None,
        "recommendations": [],
        "applied_actions": [],
        "audit_log": [],
        "validation_rules": [],
        "analysis": None,
        "charts": [],
        "insights": None,
        "file_name": None,
        "run_recorded": False,
        "active_storage_record_id": None,
        "storage_notice": None,
        "pending_delete_dataset_id": None,
        "data_updated_at": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _user_claim(name: str) -> str | None:
    """Read a verified OIDC claim without relying on a provider-specific shape."""

    try:
        value = getattr(st.user, name, None)
        if value is None:
            value = st.user.get(name)  # type: ignore[attr-defined]
    except (AttributeError, KeyError):
        return None
    return str(value) if value else None


def configure_production_access() -> None:
    """Require a real OIDC identity before the Supabase backend can be used."""

    configure_request_context(None)
    if not production_enabled():
        return

    try:
        production_settings().validate()
    except ProductionConfigurationError as exc:
        st.error(str(exc), icon=":material/error:")
        st.stop()

    if not st.user.is_logged_in:
        st.title("Sign in to InsightForge")
        st.write("Production workspaces require a verified account before data can be stored.")
        if st.button("Sign in", type="primary", icon=":material/login:"):
            st.login()
        st.stop()

    user_id = _user_claim("sub")
    if not user_id:
        st.error("The identity provider did not return a stable user ID (sub claim).", icon=":material/error:")
        st.stop()
    configure_request_context(
        UserIdentity(
            user_id=user_id,
            email=_user_claim("email"),
            display_name=_user_claim("name") or _user_claim("preferred_username"),
        ),
        st.session_state.get("active_workspace_id"),
    )


def render_workspace_selector() -> None:
    """Let production users switch only between workspaces they can access."""

    if not production_enabled():
        return
    try:
        gateway = active_gateway()
        assert gateway is not None
        workspaces = gateway.list_workspaces()
        if not workspaces:
            gateway.ensure_personal_workspace()
            workspaces = gateway.list_workspaces()
        if not workspaces:
            raise ProductionConfigurationError("No workspace could be created for this account.")

        by_id = {str(item["id"]): item for item in workspaces}
        current = st.session_state.get("active_workspace_id")
        if current not in by_id:
            current = str(workspaces[0]["id"])
        selected = st.selectbox(
            "Workspace",
            options=list(by_id),
            index=list(by_id).index(current),
            format_func=lambda workspace_id: f"{by_id[workspace_id].get('name', 'Workspace')} · {by_id[workspace_id].get('role', 'viewer')}",
            key="workspace_selector",
        )
        gateway.select_workspace(selected)
        st.session_state.active_workspace_id = selected
        set_active_workspace(selected)
        st.badge("Private Supabase workspace", icon=":material/cloud_done:", color="green")
    except Exception as exc:
        st.error(f"Workspace access is unavailable: {exc}", icon=":material/error:")
        st.stop()


def storage_backend_label() -> str:
    return "Private cloud workspace" if production_enabled() else "Permanent local storage"


def _new_workspace(frame: pd.DataFrame) -> dict[str, Any]:
    original = frame.copy()
    return {
        "original_df": original,
        "cleaned_df": original.copy(),
        "profile": None,
        "quality": None,
        "recommendations": [],
        "applied_actions": [],
        "audit_log": [],
        "analysis": None,
        "charts": [],
        "insights": None,
        "run_recorded": False,
        "data_updated_at": datetime.now().isoformat(),
    }


def _save_active_workspace() -> None:
    active_key = st.session_state.get("active_dataset_key")
    workspaces = st.session_state.get("sheet_workspaces", {})
    if not active_key or active_key not in workspaces:
        return
    for key in [
        "original_df",
        "cleaned_df",
        "profile",
        "quality",
        "recommendations",
        "applied_actions",
        "audit_log",
        "analysis",
        "charts",
        "insights",
        "run_recorded",
        "data_updated_at",
    ]:
        workspaces[active_key][key] = st.session_state.get(key)


def _clear_dataset_widget_state() -> None:
    prefixes = ("enabled_", "action_", "custom_", "analytics_")
    exact_keys = {"active_dataset_selector", "duplicate_key_columns"}
    for key in list(st.session_state.keys()):
        if key in exact_keys or any(str(key).startswith(prefix) for prefix in prefixes):
            del st.session_state[key]


def load_ingestion_into_session(
    result: IngestionResult,
    storage_record_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    _clear_dataset_widget_state()
    st.session_state.ingestion = result
    st.session_state.sheet_workspaces = {
        sheet_name: _new_workspace(frame)
        for sheet_name, frame in result.dataframes.items()
    }
    st.session_state.active_storage_record_id = storage_record_id
    st.session_state.file_name = result.file_name
    if context:
        st.session_state.context = BusinessContext(**context).model_dump()
    activate_dataset(result.active_sheet)


def mark_dataset_updated() -> None:
    """Keep a stable, user-visible update time for the active processed dataset."""

    st.session_state.data_updated_at = datetime.now().isoformat()


def activate_dataset(dataset_key: str) -> None:
    ingestion = st.session_state.get("ingestion")
    if ingestion is None or dataset_key not in ingestion.dataframes:
        return
    _save_active_workspace()
    workspaces = st.session_state.setdefault("sheet_workspaces", {})
    workspaces.setdefault(dataset_key, _new_workspace(ingestion.dataframes[dataset_key]))
    workspace = workspaces[dataset_key]
    st.session_state.active_dataset_key = dataset_key
    ingestion.active_sheet = dataset_key
    for key, value in workspace.items():
        st.session_state[key] = value


def render_loaded_dataset_selector() -> None:
    ingestion = st.session_state.get("ingestion")
    if ingestion is None or len(ingestion.dataframes) <= 1:
        return
    options = list(ingestion.dataframes.keys())
    current = st.session_state.get("active_dataset_key") or ingestion.active_sheet
    if current not in options:
        current = options[0]
    selected = st.selectbox(
        "Active sheet or combined dataset",
        options,
        index=options.index(current),
        key="active_dataset_selector",
    )
    if selected != current:
        activate_dataset(selected)
        st.rerun()


def _stored_dataset_label(record: StoredDatasetRecord) -> str:
    return f"{record.file_name} - {format_file_size(record.size_bytes)} - {record.row_count:,} rows"


def _short_date(value: str | None) -> str:
    if not value:
        return "never"
    try:
        return datetime.fromisoformat(value).strftime("%b %d, %Y")
    except ValueError:
        return value[:10]


def render_storage_sidebar() -> list[StoredDatasetRecord]:
    st.markdown("### Dataset library")
    try:
        init_dataset_store()
        records = list_stored_datasets()
    except Exception as exc:
        st.caption(f"Dataset library unavailable: {exc}")
        return []

    notice = st.session_state.get("storage_notice")
    if notice:
        st.success(notice, icon=":material/check_circle:")
        st.session_state.storage_notice = None

    st.badge(storage_backend_label(), icon=":material/database:", color="green")
    if not records:
        st.caption(
            "Saved uploads are private to your selected workspace."
            if production_enabled()
            else "Saved uploads will appear here after you load a dataset."
        )
        return records

    record_ids = [record.id for record in records]
    selected_record_id = st.session_state.get("saved_dataset_selector")
    if selected_record_id not in record_ids and "saved_dataset_selector" in st.session_state:
        del st.session_state["saved_dataset_selector"]

    record_by_id = {record.id: record for record in records}
    selected_id = st.selectbox(
        "Saved dataset",
        record_ids,
        format_func=lambda record_id: _stored_dataset_label(record_by_id[record_id]),
        key="saved_dataset_selector",
    )
    selected_record = record_by_id[selected_id]
    st.caption(
        f"{selected_record.column_count:,} columns - saved {_short_date(selected_record.created_at)}"
    )

    load_col, remove_col = st.columns(2)
    if load_col.button("Load", icon=":material/folder_open:", key="load_saved_dataset", width="stretch"):
        try:
            result, record = load_stored_dataset(selected_id)
            load_ingestion_into_session(result, storage_record_id=record.id, context=record.context)
            st.session_state.storage_notice = f"Loaded {record.file_name}."
            set_step(1)
            st.rerun()
        except Exception as exc:
            st.error(f"Could not load saved dataset: {exc}", icon=":material/error:")

    if remove_col.button("Remove", icon=":material/delete:", key="request_delete_saved_dataset", width="stretch"):
        st.session_state.pending_delete_dataset_id = selected_id

    if st.session_state.get("pending_delete_dataset_id") == selected_id:
        st.warning(
            "This permanently removes the selected dataset from this workspace."
            if production_enabled()
            else "This removes the saved local copy from the dataset library.",
            icon=":material/warning:",
        )
        confirm_col, cancel_col = st.columns(2)
        if confirm_col.button("Confirm", icon=":material/check:", key="confirm_delete_saved_dataset", width="stretch"):
            try:
                removed = delete_stored_dataset(selected_id)
                if removed and st.session_state.get("active_storage_record_id") == selected_id:
                    st.session_state.active_storage_record_id = None
                st.session_state.pending_delete_dataset_id = None
                st.session_state.storage_notice = "Saved dataset removed."
                st.rerun()
            except Exception as exc:
                st.error(f"Could not remove saved dataset: {exc}", icon=":material/error:")
        if cancel_col.button("Cancel", icon=":material/close:", key="cancel_delete_saved_dataset", width="stretch"):
            st.session_state.pending_delete_dataset_id = None
            st.rerun()

    return records


def context_model() -> BusinessContext:
    return BusinessContext(**st.session_state.context)


def set_step(step: int) -> None:
    st.session_state.step = max(0, min(step, len(STEP_LABELS) - 1))


def navigation_controls(back_enabled: bool = True, next_enabled: bool = True, next_label: str = "Next") -> None:
    left, right = st.columns([1, 1])
    with left:
        if st.button("Back", disabled=not back_enabled, icon=":material/arrow_back:", width="stretch"):
            set_step(st.session_state.step - 1)
            st.rerun()
    with right:
        if st.button(next_label, disabled=not next_enabled, icon=":material/arrow_forward:", width="stretch"):
            set_step(st.session_state.step + 1)
            st.rerun()


def display_dataframe_preview(df: pd.DataFrame, profile: dict[str, Any] | None = None) -> None:
    mask_enabled = os.getenv("INSIGHTFORGE_MASK_SENSITIVE_PREVIEWS", "true").lower() != "false"
    sensitive_columns = list((profile or {}).get("sensitive_columns", {}).keys())
    preview = mask_sensitive_preview(df.head(30), sensitive_columns) if mask_enabled and sensitive_columns else df.head(30)
    st.dataframe(preview, width="stretch", height=320)
    if sensitive_columns and mask_enabled:
        st.caption(f"Masked preview columns: {', '.join(sensitive_columns)}")


def format_file_size(size_bytes: int) -> str:
    value = float(max(size_bytes, 0))
    if value < 1024:
        return f"{int(value):,} B"
    for unit in ["KB", "MB", "GB", "TB"]:
        value /= 1024
        if value < 1024:
            return f"{value:,.1f} {unit}"
    return f"{value:,.1f} PB"


def _format_sheet_list(sheets: list[str]) -> str:
    return ", ".join(sheets) if sheets else "None"


def format_display_value(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str)
    try:
        if pd.isna(value):
            return "None"
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Number):
        formatted = f"{float(value):,.2f}"
        return formatted.rstrip("0").rstrip(".")
    return str(value)


def _humanize_label(value: str) -> str:
    return value.replace("_", " ").strip().title()


def render_dataset_details(ingestion: IngestionResult) -> None:
    with st.expander("Dataset details", expanded=False, icon=":material/folder_open:"):
        storage_status = (
            "Saved in private cloud workspace"
            if production_enabled()
            else "Saved in local dataset library"
        ) if st.session_state.get("active_storage_record_id") else "Current browser session only"
        st.table(
            {
                ":material/description: File": ingestion.file_name,
                ":material/folder: Type": ingestion.file_type.upper().lstrip(".") or "Unknown",
                ":material/storage: Size": format_file_size(ingestion.size_bytes),
                ":material/database: Storage": storage_status,
                ":material/table_chart: Active sheet": ingestion.active_sheet,
                ":material/view_list: Available sheets": _format_sheet_list(ingestion.available_sheets),
                ":material/checklist: Selected sheets": _format_sheet_list(ingestion.selected_sheets),
                ":material/join_inner: Combined sheets": "Yes" if ingestion.combined else "No",
            },
            border="horizontal",
            width="stretch",
        )
        for warning in ingestion.schema_warnings + ingestion.load_warnings:
            st.warning(warning, icon=":material/warning:")


def render_column_groups(column_types: dict[str, list[str]]) -> None:
    rows = [
        {
            "Group": _humanize_label(group),
            "Columns": _format_sheet_list([str(column) for column in columns]),
            "Count": len(columns),
        }
        for group, columns in column_types.items()
        if columns
    ]
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.caption("No column groups were detected.")


def render_kpi_summary(kpis: dict[str, Any]) -> None:
    rows = [
        {"Metric": _humanize_label(str(key)), "Value": format_display_value(value)}
        for key, value in kpis.items()
    ]
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("Run analysis to calculate summary metrics.")


def render_upload_step() -> None:
    st.subheader("Upload Data", icon=":material/upload_file:")
    upload_showcase()
    uploaded = st.file_uploader(
        "Choose a business dataset",
        type=["csv", "xlsx", "xls", "json", "parquet"],
        accept_multiple_files=False,
    )
    save_upload = st.toggle(
        "Save uploaded dataset to private workspace" if production_enabled() else "Save uploaded dataset to local library",
        value=True,
        key="save_upload_permanently",
        help=(
            "Stores an encrypted-at-rest object in the selected Supabase workspace."
            if production_enabled()
            else "Stores a local copy under data/datasets so it can be loaded again after the app restarts."
        ),
    )

    selected_sheets: list[str] | None = None
    combine_sheets = False
    if uploaded is not None:
        validation = validate_upload(uploaded.name, uploaded.size, getattr(uploaded, "type", None))
        if validation.errors:
            for error in validation.errors:
                st.error(error)
            return
        for warning in validation.warnings:
            st.warning(warning)

        extension = os.path.splitext(uploaded.name)[1].lower()
        cols = st.columns(4)
        cols[0].metric("File", uploaded.name)
        cols[1].metric("Type", extension)
        cols[2].metric("Size", f"{uploaded.size / 1024:.1f} KB")

        if extension in {".xlsx", ".xls"}:
            try:
                sheet_names = list_excel_sheets(uploaded.getvalue())
                cols[3].metric("Sheets", len(sheet_names))
                selected_sheets = st.multiselect(
                    "Sheets to analyze",
                    options=sheet_names,
                    default=sheet_names[:1],
                )
                combine_sheets = st.checkbox("Combine selected compatible sheets", value=False)
            except Exception as exc:
                st.error(f"Unable to inspect workbook sheets: {exc}")
                return
        else:
            cols[3].metric("Sheets", "1")

    st.subheader("Business Context")
    with st.form("business_context"):
        c1, c2 = st.columns(2)
        with c1:
            company = st.text_input("Company or project name", value=st.session_state.context.get("company_or_project") or "")
            industry = st.text_input("Industry", value=st.session_state.context.get("industry") or "")
            objective = st.text_input("Main business objective", value=st.session_state.context.get("business_objective") or "")
            currency = st.text_input("Currency", value=st.session_state.context.get("currency") or "USD")
        with c2:
            description = st.text_area("Dataset description", value=st.session_state.context.get("dataset_description") or "", height=84)
            country = st.text_input("Country or market", value=st.session_state.context.get("country_or_market") or "")
            target = st.text_input("Target variable or KPI", value=st.session_state.context.get("target_variable") or "")
            date_column = st.text_input("Date column", value=st.session_state.context.get("date_column") or "")
        dimensions = st.text_input(
            "Important dimensions",
            value=", ".join(st.session_state.context.get("important_dimensions", [])),
            help="Comma-separated fields such as product, region, customer, or department.",
        )
        saved = st.form_submit_button("Save context", icon=":material/save:", width="stretch")
        if saved:
            st.session_state.context = BusinessContext(
                company_or_project=company or None,
                industry=industry or None,
                dataset_description=description or None,
                business_objective=objective or None,
                target_variable=target or None,
                currency=currency or None,
                country_or_market=country or None,
                date_column=date_column or None,
                important_dimensions=[item.strip() for item in dimensions.split(",") if item.strip()],
            ).model_dump()
            st.success("Business context saved.")

    if uploaded is not None:
        if st.button("Load dataset", type="primary", icon=":material/database:", key="load_uploaded_dataset", width="stretch"):
            try:
                uploaded_bytes = uploaded.getvalue()
                result = load_dataset(
                    uploaded_bytes,
                    filename=uploaded.name,
                    selected_sheets=selected_sheets,
                    combine_sheets=combine_sheets,
                    mime_type=getattr(uploaded, "type", None),
                )
                storage_record_id = None
                if save_upload:
                    record = save_dataset_bytes(uploaded_bytes, result, context=st.session_state.context)
                    storage_record_id = record.id
                    st.session_state.storage_notice = f"Saved {record.file_name} to the dataset library."
                load_ingestion_into_session(result, storage_record_id=storage_record_id)
                for warning in result.schema_warnings + result.load_warnings:
                    st.warning(warning)
                set_step(1)
                st.rerun()
            except Exception as exc:
                st.error(f"Could not load the dataset: {exc}")


def render_profile_step() -> None:
    st.subheader("Profile Data", icon=":material/table_chart:")
    df = st.session_state.cleaned_df
    if df is None:
        st.info("Upload a dataset first.")
        navigation_controls(back_enabled=True, next_enabled=False)
        return

    with st.spinner("Profiling dataset and scoring data quality..."):
        profile = cached_profile(df)
        quality = cached_quality(df, st.session_state.context)
        rule_issues = evaluate_validation_rules(df, [ValidationRule(**rule) for rule in st.session_state.validation_rules])
        reference_issues = evaluate_configured_reference_checks(df)
        additional_issues = rule_issues + reference_issues
        if additional_issues:
            quality = {**quality, "issues": quality["issues"] + additional_issues}
        st.session_state.profile = profile
        st.session_state.quality = quality

    top = st.columns(5)
    top[0].metric("Rows", f"{profile['row_count']:,}")
    top[1].metric("Columns", f"{profile['column_count']:,}")
    top[2].metric("Missing cells", f"{sum(profile['missing_counts'].values()):,}")
    top[3].metric("Duplicates", f"{profile['exact_duplicate_rows']:,}")
    top[4].metric("Quality score", f"{quality['scores']['overall']}/100")

    ingestion = st.session_state.ingestion
    if ingestion is not None:
        render_dataset_details(ingestion)

    st.markdown("#### Column inventory")
    st.dataframe(pd.DataFrame(profile["column_profiles"]), width="stretch", height=280)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### First rows")
        display_dataframe_preview(df.head(10), profile)
    with c2:
        st.markdown("#### Last rows")
        display_dataframe_preview(df.tail(10), profile)

    st.markdown("#### Detected column groups")
    render_column_groups(profile["column_types"])

    st.markdown("#### Quality issues")
    issues = quality.get("issues", [])
    if not issues:
        st.success("No automated quality issues were found.")
    else:
        issue_titles = [f"{issue['severity'].upper()} - {issue['title']} ({issue['affected_count']})" for issue in issues]
        selected_title = st.selectbox("Inspect issue", issue_titles)
        selected_issue = issues[issue_titles.index(selected_title)]
        st.write(selected_issue["description"])
        st.caption(f"Suggested action: {selected_issue.get('suggested_action') or 'Review manually.'}")
        affected = selected_issue.get("affected_rows", [])
        if affected:
            st.dataframe(df.loc[df.index.intersection(affected)].head(100), width="stretch")

    navigation_controls(back_enabled=True, next_enabled=True)


def render_validation_rule_builder(df: pd.DataFrame) -> None:
    with st.expander("Custom validation rules", expanded=False):
        if st.session_state.validation_rules:
            st.dataframe(pd.DataFrame(st.session_state.validation_rules), width="stretch")

        templates = available_templates(context_model().industry)
        template_by_key = {template.key: template for template in templates}
        selected_template = st.selectbox(
            "Validation policy template",
            options=list(template_by_key),
            format_func=lambda key: template_by_key[key].label,
            key="validation_policy_template",
        )
        st.caption(template_by_key[selected_template].description)
        if st.button("Add template rules", icon=":material/library_add:", key="add_validation_template", width="stretch"):
            suggested_rules = build_template_rules(selected_template, [str(column) for column in df.columns])
            existing = {
                (rule.get("column"), rule.get("rule_type"), json.dumps(rule.get("value"), sort_keys=True, default=str), json.dumps(rule.get("second_value"), sort_keys=True, default=str))
                for rule in st.session_state.validation_rules
            }
            additions = [
                rule.model_dump()
                for rule in suggested_rules
                if (rule.column, rule.rule_type, json.dumps(rule.value, sort_keys=True, default=str), json.dumps(rule.second_value, sort_keys=True, default=str)) not in existing
            ]
            if additions:
                st.session_state.validation_rules.extend(additions)
                st.success(f"Added {len(additions)} policy rule{'s' if len(additions) != 1 else ''}.")
                st.rerun()
            st.info("No new template rules match this dataset's columns.")

        st.divider()
        st.caption("Or add a custom rule")
        rule_type = st.selectbox(
            "Rule type",
            [
                "required",
                "unique",
                "min_value",
                "max_value",
                "range",
                "category_list",
                "date_range",
                "regex",
                "cross_column_greater_equal",
            ],
        )
        column = st.selectbox("Column", list(df.columns))
        value: Any = None
        second_value: Any = None
        if rule_type in {"min_value", "max_value"}:
            value = st.number_input("Value", value=0.0)
        elif rule_type == "range":
            c1, c2 = st.columns(2)
            value = c1.number_input("Minimum", value=0.0)
            second_value = c2.number_input("Maximum", value=100.0)
        elif rule_type == "category_list":
            value = st.text_input("Allowed values", help="Comma-separated values")
        elif rule_type == "date_range":
            c1, c2 = st.columns(2)
            value = c1.date_input("Start date", value=date(2000, 1, 1))
            second_value = c2.date_input("End date", value=date.today())
        elif rule_type == "regex":
            value = st.text_input("Regular expression", value=r".+")
        elif rule_type == "cross_column_greater_equal":
            value = st.selectbox("Comparison column", list(df.columns))
        description = st.text_input("Rule description")
        if st.button("Add validation rule", icon=":material/rule:", width="stretch"):
            parsed_value = value
            if rule_type == "category_list":
                parsed_value = [item.strip() for item in str(value).split(",") if item.strip()]
            rule = ValidationRule(
                id=str(uuid.uuid4())[:8],
                column=column,
                rule_type=rule_type,
                value=str(parsed_value) if isinstance(parsed_value, date) else parsed_value,
                second_value=str(second_value) if isinstance(second_value, date) else second_value,
                description=description or None,
            )
            st.session_state.validation_rules.append(rule.model_dump())
            st.success("Validation rule added.")
            st.rerun()

        if st.session_state.validation_rules and st.button("Clear validation rules", icon=":material/delete:", width="stretch"):
            st.session_state.validation_rules = []
            st.rerun()


def render_duplicate_key_builder(df: pd.DataFrame) -> None:
    with st.expander("Duplicate detection using key columns", expanded=False):
        candidate_keys = []
        if st.session_state.profile:
            candidate_keys = [
                column
                for column in st.session_state.profile.get("potential_identifier_columns", [])
                if column in df.columns
            ][:3]
        key_columns = st.multiselect(
            "Key columns",
            list(df.columns),
            default=candidate_keys,
            help="Choose business keys that should identify a unique record, such as order ID plus order date.",
            key="duplicate_key_columns",
        )
        if st.button(
            "Add key duplicate recommendation",
            disabled=not key_columns,
            icon=":material/rule:",
            width="stretch",
        ):
            normalized = df[key_columns].astype("string").apply(lambda column: column.str.strip().str.lower())
            duplicate_count = int(normalized.duplicated().sum())
            if duplicate_count == 0:
                st.info("No duplicate records were found for the selected key columns.")
                return
            action_id = "key_duplicates_" + "_".join(str(column).lower().replace(" ", "_") for column in key_columns)
            recommendation = {
                "id": action_id,
                "operation": "Handle key-column duplicates",
                "action_type": "key_duplicates",
                "column": None,
                "selected_action": "review_only",
                "options": ["review_only", "keep_first", "keep_last", "remove_all_duplicates", "leave_unchanged"],
                "reason": f"{duplicate_count:,} rows duplicate an earlier record using {', '.join(key_columns)}.",
                "risk": "Key-column duplicates can be valid revisions or split transactions, so review them before removal.",
                "affected_count": duplicate_count,
                "params": {"key_columns": key_columns},
                "enabled_by_default": False,
            }
            existing_ids = {item.get("id") for item in st.session_state.recommendations}
            if action_id not in existing_ids:
                st.session_state.recommendations.append(recommendation)
                _save_active_workspace()
                st.success("Key duplicate recommendation added.")
                st.rerun()
            else:
                st.info("That key duplicate recommendation already exists.")


def render_cleaning_step() -> None:
    st.subheader("Review Cleaning Recommendations", icon=":material/cleaning_services:")
    original_df = st.session_state.original_df
    if original_df is None:
        st.info("Upload a dataset first.")
        navigation_controls(back_enabled=True, next_enabled=False)
        return

    working_df = st.session_state.cleaned_df if st.session_state.cleaned_df is not None else original_df
    profile = st.session_state.profile or cached_profile(working_df)
    quality = st.session_state.quality or cached_quality(working_df, st.session_state.context)
    st.session_state.profile = profile
    st.session_state.quality = quality

    if not st.session_state.recommendations:
        st.session_state.recommendations = recommend_cleaning_actions(working_df, quality, context_model())

    render_validation_rule_builder(working_df)
    render_duplicate_key_builder(working_df)

    recommendations = st.session_state.recommendations
    if not recommendations:
        st.success("No cleaning recommendations were generated. You can continue to analysis.")
    else:
        st.caption("Each recommendation is inactive until you approve it below. You can adjust the selected action before applying.")
        chosen_actions: list[dict[str, Any]] = []
        for rec in recommendations:
            with st.expander(f"{rec['operation']}: {rec.get('column') or 'all columns'}", expanded=rec.get("enabled_by_default", True)):
                enabled_key = f"enabled_{rec['id']}"
                action_key = f"action_{rec['id']}"
                st.session_state.setdefault(enabled_key, rec.get("enabled_by_default", True))
                st.session_state.setdefault(action_key, rec.get("selected_action", "leave_unchanged"))
                approved = st.checkbox("Approve this action", key=enabled_key)
                selected = st.selectbox(
                    "Selected action",
                    options=rec.get("options", []),
                    index=rec.get("options", []).index(st.session_state[action_key]) if st.session_state[action_key] in rec.get("options", []) else 0,
                    key=action_key,
                )
                rec["selected_action"] = selected
                if selected == "fill_custom_value":
                    custom = st.text_input("Custom fill value", key=f"custom_{rec['id']}")
                    rec.setdefault("params", {})["custom_value"] = custom
                st.write(rec["reason"])
                st.caption(f"Risk: {rec['risk']}")
                st.caption(f"Affected records: {rec['affected_count']:,}")
                if approved:
                    chosen_actions.append(rec)

        c1, c2, c3 = st.columns(3)
        if c1.button("Apply approved actions", type="primary", icon=":material/check_circle:", width="stretch"):
            cleaned, audit = apply_cleaning_pipeline(original_df, chosen_actions)
            st.session_state.cleaned_df = cleaned
            st.session_state.applied_actions = chosen_actions
            st.session_state.audit_log = audit
            st.session_state.profile = cached_profile(cleaned)
            st.session_state.quality = cached_quality(cleaned, st.session_state.context)
            st.session_state.analysis = None
            st.session_state.charts = []
            st.session_state.insights = None
            mark_dataset_updated()
            _save_active_workspace()
            st.success(f"Applied {len(audit)} approved cleaning actions.")
            st.rerun()
        if c2.button("Undo last action", disabled=not st.session_state.applied_actions, icon=":material/undo:", width="stretch"):
            remaining = st.session_state.applied_actions[:-1]
            cleaned, audit = apply_cleaning_pipeline(original_df, remaining)
            st.session_state.cleaned_df = cleaned
            st.session_state.applied_actions = remaining
            st.session_state.audit_log = audit
            st.session_state.profile = cached_profile(cleaned)
            st.session_state.quality = cached_quality(cleaned, st.session_state.context)
            mark_dataset_updated()
            _save_active_workspace()
            st.rerun()
        if c3.button("Reset all cleaning", disabled=not st.session_state.applied_actions, icon=":material/restart_alt:", width="stretch"):
            st.session_state.cleaned_df = original_df.copy()
            st.session_state.applied_actions = []
            st.session_state.audit_log = []
            st.session_state.profile = None
            st.session_state.quality = None
            st.session_state.analysis = None
            st.session_state.charts = []
            st.session_state.insights = None
            mark_dataset_updated()
            _save_active_workspace()
            st.rerun()

    before_profile = cached_profile(original_df)
    after_profile = cached_profile(st.session_state.cleaned_df)
    st.markdown("#### Before and after")
    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Rows", f"{after_profile['row_count']:,}", delta=after_profile["row_count"] - before_profile["row_count"])
    b2.metric("Missing cells", f"{sum(after_profile['missing_counts'].values()):,}", delta=sum(after_profile["missing_counts"].values()) - sum(before_profile["missing_counts"].values()))
    b3.metric("Duplicates", f"{after_profile['exact_duplicate_rows']:,}", delta=after_profile["exact_duplicate_rows"] - before_profile["exact_duplicate_rows"])
    b4.metric("Columns", f"{after_profile['column_count']:,}", delta=after_profile["column_count"] - before_profile["column_count"])

    if st.session_state.audit_log:
        st.markdown("#### Cleaning audit log")
        st.dataframe(cleaning_log_to_dataframe(st.session_state.audit_log), width="stretch", height=260)
        st.download_button(
            "Download cleaning log",
            data=audit_log_json(st.session_state.audit_log),
            file_name="cleaning_audit_log.json",
            mime="application/json",
            width="stretch",
        )

    uploaded_config = st.file_uploader("Apply saved cleaning configuration", type=["json"], key="cleaning_config_upload")
    if uploaded_config and st.button("Apply uploaded configuration", icon=":material/upload_file:", width="stretch"):
        try:
            actions = json.loads(uploaded_config.getvalue().decode("utf-8"))
            cleaned, audit = apply_cleaning_pipeline(original_df, actions)
            st.session_state.cleaned_df = cleaned
            st.session_state.applied_actions = actions
            st.session_state.audit_log = audit
            mark_dataset_updated()
            _save_active_workspace()
            st.success("Saved cleaning configuration applied.")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not apply configuration: {exc}")

    navigation_controls(back_enabled=True, next_enabled=True)


def render_analysis_step() -> None:
    st.subheader("Run Analysis", icon=":material/query_stats:")
    df = st.session_state.cleaned_df
    if df is None:
        st.info("Upload and clean a dataset first.")
        navigation_controls(back_enabled=True, next_enabled=False)
        return

    if st.button("Run statistical analysis", type="primary", icon=":material/play_arrow:", width="stretch") or st.session_state.analysis is None:
        with st.spinner("Calculating statistics, anomalies, tests, charts, and insights..."):
            analysis = cached_analysis(df, st.session_state.context)
            profile = st.session_state.profile or cached_profile(df)
            quality = st.session_state.quality or cached_quality(df, st.session_state.context)
            charts = __import__("core.visualization", fromlist=["build_dashboard_figures"]).build_dashboard_figures(
                analysis["prepared_df"], profile, quality, analysis, context_model()
            )
            insights = generate_insights(profile, quality, analysis, context_model())
            st.session_state.analysis = analysis
            st.session_state.charts = charts
            st.session_state.insights = insights
            st.session_state.profile = profile
            st.session_state.quality = quality
            _save_active_workspace()
            st.success("Analysis complete.")

    analysis = st.session_state.analysis
    tabs = st.tabs(["Summary", "Correlations", "Segments", "Anomalies", "Tests"])
    with tabs[0]:
        render_kpi_summary(analysis.get("kpis", {}))
        summary = analysis.get("numeric_summary")
        if isinstance(summary, pd.DataFrame) and not summary.empty:
            st.dataframe(summary, width="stretch")
    with tabs[1]:
        corr = analysis.get("pearson_correlation")
        if isinstance(corr, pd.DataFrame) and not corr.empty:
            st.dataframe(corr.round(3), width="stretch")
        else:
            st.info("At least two numerical columns are required for correlations.")
    with tabs[2]:
        grouped = analysis.get("group_comparison")
        if isinstance(grouped, pd.DataFrame) and not grouped.empty:
            st.dataframe(grouped, width="stretch")
        else:
            st.info("A numerical KPI and categorical dimension are required for segment comparison.")
    with tabs[3]:
        anomalies = analysis.get("anomalies")
        if isinstance(anomalies, pd.DataFrame) and not anomalies.empty:
            st.dataframe(anomalies, width="stretch")
        else:
            st.info("No anomalies were flagged by the current analytical checks.")
    with tabs[4]:
        tests = analysis.get("inferential_tests", [])
        if tests:
            st.dataframe(pd.DataFrame(tests), width="stretch")
        else:
            st.info("No inferential test was meaningful enough to run automatically.")

    if not st.session_state.run_recorded:
        try:
            metadata = {"provider": st.session_state.insights.get("provider") if st.session_state.insights else None}
            gateway = active_gateway()
            if gateway is not None:
                gateway.record_analysis_run(
                    project_name=context_model().company_or_project,
                    file_name=st.session_state.file_name or "uploaded_data",
                    row_count=int(st.session_state.profile.get("row_count", len(df))),
                    column_count=int(st.session_state.profile.get("column_count", len(df.columns))),
                    quality_score=float(st.session_state.quality.get("scores", {}).get("overall", 0)),
                    metadata=metadata,
                )
            else:
                db_path = init_history_db()
                record_analysis_run(
                    db_path,
                    context_model().company_or_project,
                    st.session_state.file_name or "uploaded_data",
                    int(st.session_state.profile.get("row_count", len(df))),
                    int(st.session_state.profile.get("column_count", len(df.columns))),
                    float(st.session_state.quality.get("scores", {}).get("overall", 0)),
                    metadata,
                )
            st.session_state.run_recorded = True
            _save_active_workspace()
        except Exception:
            pass

    navigation_controls(back_enabled=True, next_enabled=True)


def _filtered_dashboard_frame(df: pd.DataFrame, analysis: dict[str, Any]) -> pd.DataFrame:
    filtered = df.copy()
    groups = analysis.get("column_groups", {})
    date_cols = groups.get("date", [])
    categorical = groups.get("categorical", [])
    with st.sidebar:
        st.markdown("### Dashboard filters")
        if date_cols:
            date_col = st.selectbox("Date field", date_cols)
            dates = pd.to_datetime(filtered[date_col], errors="coerce")
            if dates.notna().any():
                min_date = dates.min().date()
                max_date = dates.max().date()
                selected = st.date_input("Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
                if isinstance(selected, tuple) and len(selected) == 2:
                    start, end = selected
                    filtered = filtered[(dates.dt.date >= start) & (dates.dt.date <= end)]
        for column in categorical[:3]:
            values = filtered[column].dropna().astype(str).value_counts().head(30).index.tolist()
            selected_values = st.multiselect(column, values, default=values)
            if selected_values:
                filtered = filtered[filtered[column].astype(str).isin(selected_values)]
    return filtered


def render_dashboard_step() -> None:
    st.subheader("Explore Dashboard", icon=":material/dashboard:")
    df = st.session_state.cleaned_df
    analysis = st.session_state.analysis
    if df is None or analysis is None:
        st.info("Run the analysis first.")
        navigation_controls(back_enabled=True, next_enabled=False)
        return

    filtered = _filtered_dashboard_frame(analysis["prepared_df"], analysis)
    profile = cached_profile(filtered)
    quality = cached_quality(filtered, st.session_state.context)
    filtered_analysis = cached_analysis(filtered, st.session_state.context)
    from core.visualization import build_dashboard_figures

    charts = build_dashboard_figures(filtered_analysis["prepared_df"], profile, quality, filtered_analysis, context_model())

    score = quality.get("scores", {}).get("overall", "n/a")
    kpis = filtered_analysis.get("kpis", {})
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("Quality score", f"{score}/100", "Heuristic data-quality index")
    with c2:
        metric_card("Rows in view", f"{len(filtered):,}", "After dashboard filters")
    with c3:
        metric_card("Missing cells", f"{kpis.get('missing_cells', 0):,}", "Current view")
    with c4:
        metric_card("Duplicate rows", f"{kpis.get('duplicate_rows', 0):,}", "Current view")

    insights = st.session_state.insights or generate_insights(profile, quality, filtered_analysis, context_model())
    with st.expander("Executive summary", expanded=True):
        for item in insights.get("sections", {}).get("Executive Summary", []):
            st.write(item)

    if charts:
        for index in range(0, len(charts), 2):
            left, right = st.columns(2)
            for column, chart in zip([left, right], charts[index : index + 2]):
                with column:
                    st.plotly_chart(chart["figure"], width="stretch")
                    st.caption(
                        f"{chart['interpretation']} "
                        f"Source columns: {', '.join(chart['source_columns'])}. "
                        f"{'Rendered from a sample for responsiveness.' if chart.get('sampled') else ''}"
                    )
    else:
        st.info("No dashboard charts were generated for the current filtered view.")

    st.markdown("#### Recommendations")
    recommendations = insights.get("recommendations", [])
    if recommendations:
        st.dataframe(pd.DataFrame(recommendations), width="stretch", height=300)
    else:
        st.info("No recommendations passed the evidence threshold.")

    navigation_controls(back_enabled=True, next_enabled=True)


def render_download_step() -> None:
    st.subheader("Download Files and Reports", icon=":material/download:")
    df = st.session_state.cleaned_df
    if df is None:
        st.info("Upload a dataset first.")
        navigation_controls(back_enabled=True, next_enabled=False)
        return

    profile = st.session_state.profile or cached_profile(df)
    quality = st.session_state.quality or cached_quality(df, st.session_state.context)
    analysis = st.session_state.analysis or cached_analysis(df, st.session_state.context)
    charts = st.session_state.charts
    insights = st.session_state.insights or generate_insights(profile, quality, analysis, context_model())
    audit_log = st.session_state.audit_log

    html_report = build_html_report(profile, quality, analysis, insights, audit_log, context_model())

    d1, d2, d3 = st.columns(3)
    with d1:
        st.download_button("Cleaned CSV", dataframe_to_csv_bytes(df), "insightforge_cleaned_data.csv", "text/csv", icon=":material/download:", width="stretch")
        try:
            st.download_button(
                "Cleaned Parquet",
                dataframe_to_parquet_bytes(df),
                "insightforge_cleaned_data.parquet",
                "application/octet-stream",
                icon=":material/download:",
                width="stretch",
            )
        except Exception as exc:
            st.caption(f"Parquet export unavailable: {exc}")
        st.download_button(
            "Cleaning configuration JSON",
            cleaning_configuration_json(st.session_state.applied_actions),
            "insightforge_cleaning_config.json",
            "application/json",
            icon=":material/tune:",
            width="stretch",
        )
    with d2:
        excel_bytes = build_excel_analysis_workbook(df, quality, analysis, audit_log, insights)
        st.download_button(
            "Formatted Excel workbook",
            excel_bytes,
            "insightforge_analysis_workbook.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/table_chart:",
            width="stretch",
        )
        st.download_button("HTML report", html_report.encode("utf-8"), "insightforge_management_report.html", "text/html", icon=":material/article:", width="stretch")
        st.download_button("Data-quality report JSON", quality_report_json(quality), "insightforge_quality_report.json", "application/json", icon=":material/description:", width="stretch")
    with d3:
        try:
            pdf_bytes = generate_pdf_report(profile, quality, analysis, insights, audit_log, charts, context_model())
            st.download_button("PDF management report", pdf_bytes, "insightforge_management_report.pdf", "application/pdf", icon=":material/picture_as_pdf:", width="stretch")
        except Exception as exc:
            st.error(f"PDF report generation failed: {exc}")
        st.download_button("Cleaning audit log", audit_log_json(audit_log), "insightforge_cleaning_audit_log.json", "application/json", icon=":material/history:", width="stretch")
        try:
            st.download_button("Chart images ZIP", chart_images_zip(charts), "insightforge_chart_images.zip", "application/zip", icon=":material/image:", width="stretch")
        except Exception as exc:
            st.caption(f"Chart image export unavailable: {exc}")

    st.markdown("#### Final data preview")
    display_dataframe_preview(df, profile)
    navigation_controls(back_enabled=True, next_enabled=False)


def render_analytics_dashboard_step() -> None:
    df = st.session_state.cleaned_df
    if df is None:
        st.info("Upload a dataset first to generate an analytics dashboard.", icon=":material/upload_file:")
        navigation_controls(back_enabled=True, next_enabled=False)
        return

    analysis = st.session_state.analysis or cached_analysis(df, st.session_state.context)
    profile = st.session_state.profile or cached_profile(df)
    updated_at = st.session_state.get("data_updated_at")
    try:
        last_updated = datetime.fromisoformat(updated_at) if updated_at else None
    except (TypeError, ValueError):
        last_updated = None
    render_professional_analytics_dashboard(
        df,
        file_name=st.session_state.file_name,
        analysis=analysis,
        profile=profile,
        context=context_model(),
        last_updated=last_updated,
    )
    navigation_controls(back_enabled=True, next_enabled=False)


def main() -> None:
    st.set_page_config(page_title="InsightForge AI", page_icon=":material/analytics:", layout="wide")
    init_state()
    configure_production_access()

    with st.sidebar:
        render_sidebar_brand()
        st.session_state.theme_mode = "Light"
        render_workspace_selector()
        storage_records = render_storage_sidebar()
        selected_step = st.radio("Workflow", list(range(len(STEP_LABELS))), format_func=lambda i: STEP_LABELS[i], index=st.session_state.step)
        if selected_step != st.session_state.step:
            st.session_state.step = selected_step
            st.rerun()
        render_loaded_dataset_selector()
        st.progress((st.session_state.step + 1) / len(STEP_LABELS))
        st.caption(
            "Workspace data is protected by Supabase access controls."
            if production_enabled()
            else "Saved datasets stay on this device."
        )

    inject_global_styles(st.session_state.theme_mode)
    dataset_label = f"{len(storage_records)} saved dataset{'s' if len(storage_records) != 1 else ''}"
    app_header(context_model().company_or_project, storage_label=dataset_label)
    step_indicator(st.session_state.step)

    step = st.session_state.step
    if step == 0:
        render_upload_step()
    elif step == 1:
        render_profile_step()
    elif step == 2:
        render_cleaning_step()
    elif step == 3:
        render_analysis_step()
    elif step == 4:
        render_dashboard_step()
    elif step == 5:
        render_download_step()
    elif step == 6:
        render_analytics_dashboard_step()


if __name__ == "__main__":
    main()
