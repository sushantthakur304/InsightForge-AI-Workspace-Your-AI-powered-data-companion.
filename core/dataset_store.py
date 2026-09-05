from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.ingestion import IngestionResult, load_dataset


def default_storage_dir() -> Path:
    return Path(os.getenv("INSIGHTFORGE_STORAGE_DIR", "data/datasets"))


def default_db_path() -> Path:
    return Path(os.getenv("INSIGHTFORGE_STORAGE_DB", "data/insightforge_storage.sqlite3"))


@dataclass(frozen=True)
class StoredDatasetRecord:
    id: str
    created_at: str
    updated_at: str
    last_loaded_at: str | None
    file_name: str
    file_type: str
    size_bytes: int
    row_count: int
    column_count: int
    available_sheets: list[str]
    selected_sheets: list[str]
    active_sheet: str
    combined: bool
    storage_path: str
    context: dict[str, Any]


def init_dataset_store(
    db_path: str | Path | None = None,
    storage_dir: str | Path | None = None,
) -> Path:
    resolved_db_path = Path(db_path) if db_path is not None else default_db_path()
    resolved_storage_dir = Path(storage_dir) if storage_dir is not None else default_storage_dir()
    resolved_storage_dir.mkdir(parents=True, exist_ok=True)
    resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(resolved_db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stored_datasets (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_loaded_at TEXT,
                file_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                row_count INTEGER NOT NULL,
                column_count INTEGER NOT NULL,
                available_sheets_json TEXT NOT NULL,
                selected_sheets_json TEXT NOT NULL,
                active_sheet TEXT NOT NULL,
                combined INTEGER NOT NULL,
                storage_path TEXT NOT NULL,
                context_json TEXT NOT NULL
            )
            """
        )
    return resolved_db_path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_file_stem(file_name: str) -> str:
    stem = Path(file_name).stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return stem or "dataset"


def _record_from_row(row: sqlite3.Row) -> StoredDatasetRecord:
    return StoredDatasetRecord(
        id=row["id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_loaded_at=row["last_loaded_at"],
        file_name=row["file_name"],
        file_type=row["file_type"],
        size_bytes=int(row["size_bytes"]),
        row_count=int(row["row_count"]),
        column_count=int(row["column_count"]),
        available_sheets=json.loads(row["available_sheets_json"]),
        selected_sheets=json.loads(row["selected_sheets_json"]),
        active_sheet=row["active_sheet"],
        combined=bool(row["combined"]),
        storage_path=row["storage_path"],
        context=json.loads(row["context_json"]),
    )


def _resolve_storage_path(path: str | Path, storage_dir: str | Path | None = None) -> Path:
    resolved_storage_dir = (Path(storage_dir) if storage_dir is not None else default_storage_dir()).resolve()
    resolved_path = Path(path).resolve()
    try:
        resolved_path.relative_to(resolved_storage_dir)
    except ValueError as exc:
        raise ValueError("Stored dataset path is outside the configured storage directory.") from exc
    return resolved_path


def save_dataset_bytes(
    content: bytes,
    ingestion: IngestionResult,
    context: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
    storage_dir: str | Path | None = None,
) -> StoredDatasetRecord:
    resolved_db_path = init_dataset_store(db_path, storage_dir)
    resolved_storage_dir = Path(storage_dir) if storage_dir is not None else default_storage_dir()
    resolved_storage_dir.mkdir(parents=True, exist_ok=True)

    dataset_id = uuid.uuid4().hex
    extension = Path(ingestion.file_name).suffix.lower() or ingestion.file_type or ".data"
    saved_name = f"{_safe_file_stem(ingestion.file_name)}-{dataset_id[:10]}{extension}"
    destination = resolved_storage_dir / saved_name
    temp_destination = destination.with_suffix(destination.suffix + ".tmp")
    temp_destination.write_bytes(content)
    temp_destination.replace(destination)

    timestamp = _utc_now()
    record = StoredDatasetRecord(
        id=dataset_id,
        created_at=timestamp,
        updated_at=timestamp,
        last_loaded_at=None,
        file_name=ingestion.file_name,
        file_type=ingestion.file_type,
        size_bytes=ingestion.size_bytes,
        row_count=int(ingestion.dataframe.shape[0]),
        column_count=int(ingestion.dataframe.shape[1]),
        available_sheets=list(ingestion.available_sheets),
        selected_sheets=list(ingestion.selected_sheets),
        active_sheet=ingestion.active_sheet,
        combined=bool(ingestion.combined),
        storage_path=str(destination),
        context=context or {},
    )

    with sqlite3.connect(resolved_db_path) as conn:
        conn.execute(
            """
            INSERT INTO stored_datasets (
                id, created_at, updated_at, last_loaded_at, file_name, file_type, size_bytes,
                row_count, column_count, available_sheets_json, selected_sheets_json,
                active_sheet, combined, storage_path, context_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.created_at,
                record.updated_at,
                record.last_loaded_at,
                record.file_name,
                record.file_type,
                record.size_bytes,
                record.row_count,
                record.column_count,
                json.dumps(record.available_sheets),
                json.dumps(record.selected_sheets),
                record.active_sheet,
                int(record.combined),
                record.storage_path,
                json.dumps(record.context, default=str),
            ),
        )
    return record


def list_stored_datasets(
    db_path: str | Path | None = None,
    storage_dir: str | Path | None = None,
) -> list[StoredDatasetRecord]:
    resolved_db_path = init_dataset_store(db_path, storage_dir)
    with sqlite3.connect(resolved_db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM stored_datasets ORDER BY created_at DESC"
        ).fetchall()
    return [_record_from_row(row) for row in rows]


def get_stored_dataset(
    dataset_id: str,
    db_path: str | Path | None = None,
    storage_dir: str | Path | None = None,
) -> StoredDatasetRecord | None:
    resolved_db_path = init_dataset_store(db_path, storage_dir)
    with sqlite3.connect(resolved_db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM stored_datasets WHERE id = ?",
            (dataset_id,),
        ).fetchone()
    return _record_from_row(row) if row else None


def load_stored_dataset(
    dataset_id: str,
    db_path: str | Path | None = None,
    storage_dir: str | Path | None = None,
) -> tuple[IngestionResult, StoredDatasetRecord]:
    resolved_db_path = init_dataset_store(db_path, storage_dir)
    record = get_stored_dataset(dataset_id, resolved_db_path, storage_dir)
    if record is None:
        raise ValueError("Saved dataset was not found.")

    stored_path = _resolve_storage_path(record.storage_path, storage_dir)
    if not stored_path.exists():
        raise FileNotFoundError(f"Stored file is missing: {record.file_name}")

    result = load_dataset(
        stored_path,
        filename=record.file_name,
        selected_sheets=record.selected_sheets,
        combine_sheets=record.combined,
    )
    if record.active_sheet in result.dataframes:
        result.active_sheet = record.active_sheet

    with sqlite3.connect(resolved_db_path) as conn:
        conn.execute(
            "UPDATE stored_datasets SET last_loaded_at = ?, updated_at = ? WHERE id = ?",
            (_utc_now(), _utc_now(), dataset_id),
        )
    return result, record


def delete_stored_dataset(
    dataset_id: str,
    db_path: str | Path | None = None,
    storage_dir: str | Path | None = None,
) -> bool:
    resolved_db_path = init_dataset_store(db_path, storage_dir)
    record = get_stored_dataset(dataset_id, resolved_db_path, storage_dir)
    if record is None:
        return False

    stored_path = _resolve_storage_path(record.storage_path, storage_dir)
    if stored_path.exists():
        stored_path.unlink()
    with sqlite3.connect(resolved_db_path) as conn:
        conn.execute("DELETE FROM stored_datasets WHERE id = ?", (dataset_id,))
    return True
