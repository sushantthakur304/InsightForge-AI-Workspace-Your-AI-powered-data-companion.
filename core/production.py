"""Production workspace services backed by Supabase.

The Streamlit application remains local-first by default.  Setting
``INSIGHTFORGE_STORAGE_BACKEND=supabase`` switches dataset metadata, project
history, and background-job records to Supabase.  The module deliberately
reads credentials only from the process environment so secrets are never
stored in the repository.
"""

from __future__ import annotations

import os
import re
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


class ProductionConfigurationError(RuntimeError):
    """Raised when production storage is enabled without the required setup."""


@dataclass(frozen=True)
class UserIdentity:
    """Identity verified by Streamlit's configured OIDC provider."""

    user_id: str
    email: str | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class ProductionSettings:
    backend: str
    supabase_url: str | None
    service_role_key: str | None
    bucket: str
    background_file_threshold_mb: int

    @property
    def enabled(self) -> bool:
        return self.backend == "supabase"

    @classmethod
    def from_environment(cls) -> "ProductionSettings":
        return cls(
            backend=os.getenv("INSIGHTFORGE_STORAGE_BACKEND", "local").strip().lower(),
            supabase_url=os.getenv("SUPABASE_URL", "").strip().rstrip("/") or None,
            service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip() or None,
            bucket=os.getenv("INSIGHTFORGE_SUPABASE_BUCKET", "dataset-files").strip() or "dataset-files",
            background_file_threshold_mb=max(1, int(os.getenv("INSIGHTFORGE_BACKGROUND_FILE_THRESHOLD_MB", "25"))),
        )

    def validate(self) -> None:
        if not self.enabled:
            return
        if not self.supabase_url or not self.service_role_key:
            raise ProductionConfigurationError(
                "Supabase storage requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY. "
                "Keep the service-role key in deployment secrets only."
            )


_identity_context: ContextVar[UserIdentity | None] = ContextVar("insightforge_identity", default=None)
_workspace_context: ContextVar[str | None] = ContextVar("insightforge_workspace", default=None)


def production_settings() -> ProductionSettings:
    return ProductionSettings.from_environment()


def production_enabled() -> bool:
    return production_settings().enabled


def configure_request_context(identity: UserIdentity | None, workspace_id: str | None = None) -> None:
    """Bind verified identity and workspace to this Streamlit script run."""

    _identity_context.set(identity)
    _workspace_context.set(workspace_id)


def current_identity() -> UserIdentity | None:
    return _identity_context.get()


def set_active_workspace(workspace_id: str | None) -> None:
    _workspace_context.set(workspace_id)


def active_workspace_id() -> str | None:
    return _workspace_context.get()


def _safe_object_name(file_name: str) -> str:
    stem = Path(file_name).name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-")
    return stem or "dataset.bin"


class SupabaseGateway:
    """Small server-side REST client for Supabase Storage and PostgREST.

    Calls use the service-role key, which must stay on the Streamlit server.
    Every operation also verifies the Streamlit-authenticated actor's workspace
    membership through server-only RPC functions created by the SQL migration.
    """

    def __init__(self, settings: ProductionSettings, identity: UserIdentity):
        settings.validate()
        self.settings = settings
        self.identity = identity
        self.workspace_id = active_workspace_id()
        self.session = requests.Session()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.settings.service_role_key or "",
            "Authorization": f"Bearer {self.settings.service_role_key}",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        response = self.session.request(
            method,
            f"{self.settings.supabase_url}{path}",
            headers={**self._headers, **kwargs.pop("headers", {})},
            timeout=30,
            **kwargs,
        )
        if response.status_code >= 400:
            detail = response.text[:600]
            raise ProductionConfigurationError(f"Supabase request failed ({response.status_code}): {detail}")
        return response

    def rpc(self, function: str, payload: dict[str, Any]) -> Any:
        response = self._request("POST", f"/rest/v1/rpc/{function}", json=payload)
        return response.json() if response.content else None

    def ensure_personal_workspace(self) -> dict[str, Any]:
        payload = self.rpc(
            "ensure_personal_workspace",
            {
                "p_user_id": self.identity.user_id,
                "p_email": self.identity.email,
                "p_display_name": self.identity.display_name,
            },
        )
        if not isinstance(payload, dict) or not payload.get("workspace_id"):
            raise ProductionConfigurationError("Supabase did not return a personal workspace.")
        self.workspace_id = str(payload["workspace_id"])
        set_active_workspace(self.workspace_id)
        return payload

    def list_workspaces(self) -> list[dict[str, Any]]:
        payload = self.rpc("list_user_workspaces", {"p_user_id": self.identity.user_id})
        if payload is None:
            return []
        return payload if isinstance(payload, list) else [payload]

    def select_workspace(self, workspace_id: str) -> dict[str, Any]:
        workspaces = self.list_workspaces()
        selected = next((item for item in workspaces if str(item.get("id")) == workspace_id), None)
        if selected is None:
            raise PermissionError("You do not have access to the selected workspace.")
        self.workspace_id = workspace_id
        set_active_workspace(workspace_id)
        return selected

    def require_workspace(self) -> str:
        if self.workspace_id:
            self.select_workspace(self.workspace_id)
            return self.workspace_id
        return str(self.ensure_personal_workspace()["workspace_id"])

    def _dataset_params(self, dataset_id: str | None = None) -> dict[str, str]:
        params = {"workspace_id": f"eq.{self.require_workspace()}"}
        if dataset_id:
            params["id"] = f"eq.{dataset_id}"
        return params

    def list_datasets(self) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            "/rest/v1/datasets",
            params={**self._dataset_params(), "select": "*", "order": "created_at.desc"},
        )
        return response.json()

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        response = self._request(
            "GET",
            "/rest/v1/datasets",
            params={**self._dataset_params(dataset_id), "select": "*", "limit": "1"},
        )
        rows = response.json()
        return rows[0] if rows else None

    def save_dataset(
        self,
        content: bytes,
        *,
        file_name: str,
        file_type: str,
        size_bytes: int,
        row_count: int,
        column_count: int,
        available_sheets: list[str],
        selected_sheets: list[str],
        active_sheet: str,
        combined: bool,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        workspace_id = self.require_workspace()
        dataset_id = str(uuid.uuid4())
        object_key = f"{workspace_id}/{dataset_id}/{_safe_object_name(file_name)}"
        encoded_key = quote(object_key, safe="/")
        self._request(
            "POST",
            f"/storage/v1/object/{self.settings.bucket}/{encoded_key}",
            headers={"Content-Type": "application/octet-stream", "x-upsert": "false"},
            data=content,
        )

        record = {
            "id": dataset_id,
            "workspace_id": workspace_id,
            "created_by": self.identity.user_id,
            "file_name": file_name,
            "file_type": file_type,
            "size_bytes": size_bytes,
            "row_count": row_count,
            "column_count": column_count,
            "available_sheets": available_sheets,
            "selected_sheets": selected_sheets,
            "active_sheet": active_sheet,
            "combined": combined,
            "storage_key": object_key,
            "context": context,
            "processing_status": "ready",
        }
        try:
            response = self._request(
                "POST",
                "/rest/v1/datasets",
                headers={"Prefer": "return=representation"},
                json=record,
            )
        except Exception:
            self._request("DELETE", f"/storage/v1/object/{self.settings.bucket}/{encoded_key}")
            raise
        rows = response.json()
        saved = rows[0] if isinstance(rows, list) and rows else record
        if size_bytes >= self.settings.background_file_threshold_mb * 1024 * 1024:
            self.enqueue_job("profile_dataset", {"dataset_id": dataset_id})
        return saved

    def download_dataset(self, record: dict[str, Any]) -> bytes:
        encoded_key = quote(str(record["storage_key"]), safe="/")
        response = self._request("GET", f"/storage/v1/object/{self.settings.bucket}/{encoded_key}")
        return response.content

    def mark_dataset_loaded(self, dataset_id: str) -> None:
        self._request(
            "PATCH",
            "/rest/v1/datasets",
            params=self._dataset_params(dataset_id),
            json={"last_loaded_at": datetime.now(timezone.utc).isoformat()},
        )

    def delete_dataset(self, record: dict[str, Any]) -> None:
        dataset_id = str(record["id"])
        encoded_key = quote(str(record["storage_key"]), safe="/")
        self._request("DELETE", f"/storage/v1/object/{self.settings.bucket}/{encoded_key}")
        self._request("DELETE", "/rest/v1/datasets", params=self._dataset_params(dataset_id))

    def record_analysis_run(
        self,
        *,
        project_name: str | None,
        file_name: str,
        row_count: int,
        column_count: int,
        quality_score: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._request(
            "POST",
            "/rest/v1/analysis_runs",
            json={
                "workspace_id": self.require_workspace(),
                "created_by": self.identity.user_id,
                "project_name": project_name,
                "file_name": file_name,
                "row_count": row_count,
                "column_count": column_count,
                "quality_score": quality_score,
                "metadata": metadata or {},
            },
        )

    def enqueue_job(self, job_type: str, payload: dict[str, Any], scheduled_for: str | None = None) -> None:
        self._request(
            "POST",
            "/rest/v1/background_jobs",
            json={
                "workspace_id": self.require_workspace(),
                "created_by": self.identity.user_id,
                "job_type": job_type,
                "payload": payload,
                "scheduled_for": scheduled_for or datetime.now(timezone.utc).isoformat(),
            },
        )


def active_gateway() -> SupabaseGateway | None:
    settings = production_settings()
    if not settings.enabled:
        return None
    identity = current_identity()
    if identity is None:
        raise ProductionConfigurationError(
            "A verified user identity is required before production data can be stored."
        )
    return SupabaseGateway(settings, identity)
