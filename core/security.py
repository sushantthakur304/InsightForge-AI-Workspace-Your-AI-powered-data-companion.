from __future__ import annotations

import mimetypes
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterable

import pandas as pd

from models.schemas import FileValidationResult


ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json", ".parquet"}
FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
DEFAULT_MAX_UPLOAD_MB = int(os.getenv("INSIGHTFORGE_MAX_UPLOAD_MB", "100"))

SENSITIVE_NAME_PATTERNS = {
    "email": re.compile(r"e[-_ ]?mail|email", re.I),
    "phone": re.compile(r"phone|mobile|contact|telephone", re.I),
    "address": re.compile(r"address|street|zip|postal|postcode", re.I),
    "id": re.compile(r"(^id$|[_ -]id$|id[_ -]|customer[_ -]?id|account|ssn|passport|license)", re.I),
    "payment": re.compile(r"card|iban|routing|payment|bank|cvv|pan", re.I),
}

SENSITIVE_VALUE_PATTERNS = {
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "phone": re.compile(r"(?<!\d)(?:\+?\d[\d .()/-]{7,}\d)(?!\d)"),
    "payment": re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)"),
}


def validate_upload(
    file_name: str,
    size_bytes: int,
    mime_type: str | None = None,
    max_size_mb: int = DEFAULT_MAX_UPLOAD_MB,
) -> FileValidationResult:
    """Validate user-provided upload metadata before reading file contents."""

    extension = Path(file_name).suffix.lower()
    errors: list[str] = []
    warnings: list[str] = []

    if extension not in ALLOWED_EXTENSIONS:
        errors.append(
            f"Unsupported file extension '{extension or '(none)'}'. "
            f"Supported types: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )

    max_bytes = max_size_mb * 1024 * 1024
    if size_bytes <= 0:
        errors.append("The uploaded file is empty.")
    elif size_bytes > max_bytes:
        errors.append(f"The uploaded file is larger than the configured {max_size_mb} MB limit.")

    guessed_mime, _ = mimetypes.guess_type(file_name)
    if mime_type and guessed_mime and mime_type != guessed_mime:
        warnings.append(
            f"The browser reported MIME type '{mime_type}', while the extension suggests '{guessed_mime}'."
        )

    return FileValidationResult(
        is_valid=not errors,
        file_name=file_name,
        extension=extension,
        size_bytes=size_bytes,
        errors=errors,
        warnings=warnings,
    )


def read_file_bytes(source: bytes | bytearray | str | Path | BinaryIO) -> bytes:
    """Read bytes from a path, raw bytes, or file-like upload without consuming state permanently."""

    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    position = None
    if hasattr(source, "tell") and hasattr(source, "seek"):
        try:
            position = source.tell()
            source.seek(0)
        except Exception:
            position = None
    data = source.read()
    if position is not None:
        try:
            source.seek(position)
        except Exception:
            pass
    return bytes(data)


@contextmanager
def safe_named_temp_file(suffix: str = ""):
    """Create a temporary file that is cleaned up after use."""

    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.close()
        yield Path(handle.name)
    finally:
        try:
            Path(handle.name).unlink(missing_ok=True)
        except Exception:
            pass


def sanitize_excel_value(value):
    """Protect spreadsheet exports from formula injection."""

    if isinstance(value, str) and value.startswith(FORMULA_INJECTION_PREFIXES):
        return "'" + value
    return value


def protect_dataframe_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    protected = df.copy()
    for column in protected.select_dtypes(include=["object", "string"]).columns:
        protected[column] = protected[column].map(sanitize_excel_value)
    return protected


def detect_sensitive_columns(df: pd.DataFrame, sample_size: int = 200) -> dict[str, list[str]]:
    """Return sensitive-looking columns and the reasons they were flagged."""

    detected: dict[str, list[str]] = {}
    sample = df.head(sample_size)
    for column in df.columns:
        reasons: list[str] = []
        column_name = str(column)
        for label, pattern in SENSITIVE_NAME_PATTERNS.items():
            if pattern.search(column_name):
                reasons.append(f"name:{label}")

        values = sample[column].dropna().astype(str).head(sample_size)
        if not values.empty:
            text = "\n".join(values.tolist())
            for label, pattern in SENSITIVE_VALUE_PATTERNS.items():
                match_count = sum(bool(pattern.search(value)) for value in values)
                if match_count / max(len(values), 1) >= 0.2:
                    reasons.append(f"value:{label}")

        if reasons:
            detected[column_name] = sorted(set(reasons))
    return detected


def mask_sensitive_value(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value)
    if "@" in text:
        name, _, domain = text.partition("@")
        return f"{name[:2]}***@{domain[:1]}***"
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 7:
        return f"***{digits[-4:]}"
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def mask_sensitive_preview(df: pd.DataFrame, sensitive_columns: Iterable[str]) -> pd.DataFrame:
    preview = df.copy()
    for column in sensitive_columns:
        if column in preview.columns:
            preview[column] = preview[column].map(mask_sensitive_value)
    return preview


def normalize_column_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\s]+", "", str(name).strip().lower())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "column"


def make_unique_column_names(names: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for raw in names:
        base = normalize_column_name(raw)
        count = seen.get(base, 0)
        seen[base] = count + 1
        result.append(base if count == 0 else f"{base}_{count + 1}")
    return result

