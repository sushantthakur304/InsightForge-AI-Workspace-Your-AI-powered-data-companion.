from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def init_history_db(path: str | Path = "insightforge_history.sqlite3") -> Path:
    db_path = Path(path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                project_name TEXT,
                file_name TEXT,
                row_count INTEGER,
                column_count INTEGER,
                quality_score REAL,
                metadata_json TEXT
            )
            """
        )
    return db_path


def record_analysis_run(
    db_path: str | Path,
    project_name: str | None,
    file_name: str,
    row_count: int,
    column_count: int,
    quality_score: float,
    metadata: dict[str, Any] | None = None,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO analysis_runs
            (created_at, project_name, file_name, row_count, column_count, quality_score, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                project_name,
                file_name,
                row_count,
                column_count,
                quality_score,
                json.dumps(metadata or {}, default=str),
            ),
        )


def list_analysis_runs(db_path: str | Path, limit: int = 25) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM analysis_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]

