"""Supabase queue worker for expensive dataset jobs.

Run this as a separate process in production, never inside a Streamlit rerun:
``python -m workers.production_worker``.  A scheduler may enqueue
``refresh_dataset`` jobs using the ``scheduled_refreshes`` table; large uploads
automatically enqueue ``profile_dataset`` jobs.
"""

from __future__ import annotations

import argparse
import os
import socket
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

import requests

from core.ingestion import load_dataset
from core.production import ProductionSettings
from core.profiler import profile_dataframe


class ProductionWorker:
    def __init__(self) -> None:
        self.settings = ProductionSettings.from_environment()
        self.settings.validate()
        self.worker_id = os.getenv("INSIGHTFORGE_WORKER_ID", socket.gethostname())
        self.session = requests.Session()

    @property
    def headers(self) -> dict[str, str]:
        return {
            "apikey": self.settings.service_role_key or "",
            "Authorization": f"Bearer {self.settings.service_role_key}",
        }

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        response = self.session.request(
            method,
            f"{self.settings.supabase_url}{path}",
            headers={**self.headers, **kwargs.pop("headers", {})},
            timeout=60,
            **kwargs,
        )
        response.raise_for_status()
        return response

    def claim_job(self) -> dict[str, Any] | None:
        response = self.request("POST", "/rest/v1/rpc/claim_next_background_job", json={"p_worker_id": self.worker_id})
        payload = response.json() if response.content else None
        if not payload:
            return None
        return payload[0] if isinstance(payload, list) else payload

    def dataset(self, dataset_id: str) -> dict[str, Any]:
        response = self.request("GET", "/rest/v1/datasets", params={"id": f"eq.{dataset_id}", "select": "*", "limit": "1"})
        rows = response.json()
        if not rows:
            raise ValueError(f"Dataset {dataset_id} no longer exists.")
        return rows[0]

    def mark_job(self, job_id: str, status: str, error_message: str | None = None) -> None:
        payload: dict[str, Any] = {
            "status": status,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if error_message:
            payload["error_message"] = error_message[:2000]
        self.request("PATCH", "/rest/v1/background_jobs", params={"id": f"eq.{job_id}"}, json=payload)

    def profile_dataset(self, dataset_id: str) -> None:
        dataset = self.dataset(dataset_id)
        object_key = quote(str(dataset["storage_key"]), safe="/")
        content = self.request("GET", f"/storage/v1/object/{self.settings.bucket}/{object_key}").content
        ingestion = load_dataset(
            content,
            filename=str(dataset["file_name"]),
            selected_sheets=list(dataset.get("selected_sheets") or []),
            combine_sheets=bool(dataset.get("combined")),
        )
        profile = profile_dataframe(ingestion.dataframe)
        self.request(
            "POST",
            "/rest/v1/dataset_profiles",
            json={"dataset_id": dataset_id, "profile": profile},
        )
        self.request(
            "PATCH",
            "/rest/v1/datasets",
            params={"id": f"eq.{dataset_id}"},
            json={
                "row_count": int(ingestion.dataframe.shape[0]),
                "column_count": int(ingestion.dataframe.shape[1]),
                "processing_status": "ready",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def refresh_dataset(self, dataset_id: str, source_url: str) -> None:
        """Refresh a dataset only from operator-approved HTTPS hosts."""

        allowed_hosts = {
            host.strip().lower()
            for host in os.getenv("INSIGHTFORGE_REFRESH_ALLOWED_HOSTS", "").split(",")
            if host.strip()
        }
        parsed = urlparse(source_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.lower() not in allowed_hosts:
            raise ValueError("Refresh source is not in INSIGHTFORGE_REFRESH_ALLOWED_HOSTS.")
        dataset = self.dataset(dataset_id)
        source = requests.get(source_url, timeout=60, allow_redirects=False)
        source.raise_for_status()
        content = source.content
        ingestion = load_dataset(content, filename=str(dataset["file_name"]))
        object_key = quote(str(dataset["storage_key"]), safe="/")
        self.request(
            "POST",
            f"/storage/v1/object/{self.settings.bucket}/{object_key}",
            headers={"Content-Type": "application/octet-stream", "x-upsert": "true"},
            data=content,
        )
        self.request(
            "PATCH",
            "/rest/v1/datasets",
            params={"id": f"eq.{dataset_id}"},
            json={
                "size_bytes": len(content),
                "row_count": int(ingestion.dataframe.shape[0]),
                "column_count": int(ingestion.dataframe.shape[1]),
                "processing_status": "ready",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def run_once(self) -> bool:
        job = self.claim_job()
        if job is None:
            return False
        try:
            payload = job.get("payload") or {}
            if job["job_type"] == "profile_dataset":
                self.profile_dataset(str(payload["dataset_id"]))
            elif job["job_type"] == "refresh_dataset":
                self.refresh_dataset(str(payload["dataset_id"]), str(payload["source_url"]))
            else:
                raise ValueError(f"Unsupported background job type: {job['job_type']}")
        except Exception as exc:
            self.mark_job(str(job["id"]), "failed", str(exc))
            return True
        self.mark_job(str(job["id"]), "succeeded")
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Run InsightForge production background jobs.")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job.")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()
    worker = ProductionWorker()
    while True:
        worked = worker.run_once()
        if args.once:
            return
        if not worked:
            time.sleep(max(0.5, args.poll_seconds))


if __name__ == "__main__":
    main()
