from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pandas as pd

try:
    import polars as pl
except Exception:  # pragma: no cover - optional fallback
    pl = None

from core.security import read_file_bytes, validate_upload


@dataclass
class IngestionResult:
    file_name: str
    file_type: str
    size_bytes: int
    dataframes: dict[str, pd.DataFrame]
    active_sheet: str
    selected_sheets: list[str] = field(default_factory=list)
    available_sheets: list[str] = field(default_factory=list)
    combined: bool = False
    schema_warnings: list[str] = field(default_factory=list)
    load_warnings: list[str] = field(default_factory=list)

    @property
    def dataframe(self) -> pd.DataFrame:
        return self.dataframes[self.active_sheet]


def _infer_filename(source: bytes | bytearray | str | Path | BinaryIO, filename: str | None) -> str:
    if filename:
        return filename
    if isinstance(source, (str, Path)):
        return Path(source).name
    return getattr(source, "name", "uploaded_data")


def _read_csv(data: bytes, use_polars_threshold_mb: int = 20) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    size_mb = len(data) / (1024 * 1024)
    if size_mb >= use_polars_threshold_mb and pl is not None:
        try:
            return pl.read_csv(BytesIO(data), infer_schema_length=2000).to_pandas(), warnings
        except Exception as exc:
            warnings.append(f"Polars CSV reader fell back to pandas: {exc}")

    for encoding in ("utf-8", "utf-8-sig", "latin1"):
        try:
            return pd.read_csv(BytesIO(data), encoding=encoding, encoding_errors="replace"), warnings
        except UnicodeDecodeError:
            continue
    return pd.read_csv(BytesIO(data), encoding="latin1", encoding_errors="replace"), warnings


def _read_json(data: bytes) -> pd.DataFrame:
    buffer = BytesIO(data)
    try:
        frame = pd.read_json(buffer)
    except ValueError:
        buffer.seek(0)
        frame = pd.read_json(buffer, lines=True)
    if isinstance(frame, pd.Series):
        frame = frame.to_frame(name="value")
    return frame


def list_excel_sheets(source: bytes | bytearray | str | Path | BinaryIO) -> list[str]:
    data = read_file_bytes(source)
    with pd.ExcelFile(BytesIO(data)) as workbook:
        return list(workbook.sheet_names)


def _schemas_are_compatible(frames: dict[str, pd.DataFrame]) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    if not frames:
        return False, ["No sheets were selected."]
    first_name = next(iter(frames))
    first_columns = list(frames[first_name].columns)
    for sheet_name, frame in frames.items():
        if list(frame.columns) != first_columns:
            missing = sorted(set(first_columns) - set(frame.columns))
            extra = sorted(set(frame.columns) - set(first_columns))
            warnings.append(
                f"Sheet '{sheet_name}' has an incompatible schema. "
                f"Missing columns: {missing or 'none'}; extra columns: {extra or 'none'}."
            )
    return not warnings, warnings


def load_dataset(
    source: bytes | bytearray | str | Path | BinaryIO,
    filename: str | None = None,
    selected_sheets: list[str] | None = None,
    combine_sheets: bool = False,
    mime_type: str | None = None,
    max_size_mb: int = 100,
) -> IngestionResult:
    """Load an uploaded business dataset into one or more pandas DataFrames."""

    resolved_filename = _infer_filename(source, filename)
    data = read_file_bytes(source)
    validation = validate_upload(resolved_filename, len(data), mime_type=mime_type, max_size_mb=max_size_mb)
    if not validation.is_valid:
        raise ValueError("; ".join(validation.errors))

    extension = Path(resolved_filename).suffix.lower()
    load_warnings = list(validation.warnings)

    if extension == ".csv":
        frame, warnings = _read_csv(data)
        load_warnings.extend(warnings)
        return IngestionResult(
            file_name=resolved_filename,
            file_type=extension,
            size_bytes=len(data),
            dataframes={"Data": frame},
            active_sheet="Data",
            selected_sheets=["Data"],
            available_sheets=["Data"],
            load_warnings=load_warnings,
        )

    if extension in {".xlsx", ".xls"}:
        with pd.ExcelFile(BytesIO(data)) as workbook:
            available = list(workbook.sheet_names)
            sheets_to_read = selected_sheets or available[:1]
            invalid = sorted(set(sheets_to_read) - set(available))
            if invalid:
                raise ValueError(f"Selected sheet(s) not found: {', '.join(invalid)}")
            frames = {sheet: workbook.parse(sheet) for sheet in sheets_to_read}

        schema_warnings: list[str] = []
        if combine_sheets and len(frames) > 1:
            compatible, schema_warnings = _schemas_are_compatible(frames)
            if compatible:
                combined_frames = []
                for sheet_name, frame in frames.items():
                    temp = frame.copy()
                    temp["source_sheet"] = sheet_name
                    combined_frames.append(temp)
                combined = pd.concat(combined_frames, ignore_index=True)
                frames = {"Combined": combined, **frames}
                active_sheet = "Combined"
            else:
                active_sheet = sheets_to_read[0]
        else:
            active_sheet = sheets_to_read[0]

        return IngestionResult(
            file_name=resolved_filename,
            file_type=extension,
            size_bytes=len(data),
            dataframes=frames,
            active_sheet=active_sheet,
            selected_sheets=sheets_to_read,
            available_sheets=available,
            combined=combine_sheets and active_sheet == "Combined",
            schema_warnings=schema_warnings,
            load_warnings=load_warnings,
        )

    if extension == ".json":
        frame = _read_json(data)
        return IngestionResult(
            file_name=resolved_filename,
            file_type=extension,
            size_bytes=len(data),
            dataframes={"Data": frame},
            active_sheet="Data",
            selected_sheets=["Data"],
            available_sheets=["Data"],
            load_warnings=load_warnings,
        )

    if extension == ".parquet":
        frame = pd.read_parquet(BytesIO(data))
        return IngestionResult(
            file_name=resolved_filename,
            file_type=extension,
            size_bytes=len(data),
            dataframes={"Data": frame},
            active_sheet="Data",
            selected_sheets=["Data"],
            available_sheets=["Data"],
            load_warnings=load_warnings,
        )

    raise ValueError(f"Unsupported file extension: {extension}")

