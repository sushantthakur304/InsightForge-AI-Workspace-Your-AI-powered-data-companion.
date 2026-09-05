from __future__ import annotations

from pathlib import Path

from core.dataset_store import (
    delete_stored_dataset,
    list_stored_datasets,
    load_stored_dataset,
    save_dataset_bytes,
)
from core.ingestion import load_dataset


def test_dataset_store_round_trips_uploaded_file(tmp_path: Path):
    db_path = tmp_path / "store.sqlite3"
    storage_dir = tmp_path / "datasets"
    source_path = Path("sample_data/messy_sales_data.csv")
    content = source_path.read_bytes()
    ingestion = load_dataset(content, filename=source_path.name, mime_type="text/csv")

    saved = save_dataset_bytes(
        content,
        ingestion,
        context={"company_or_project": "Retail demo"},
        db_path=db_path,
        storage_dir=storage_dir,
    )

    records = list_stored_datasets(db_path=db_path, storage_dir=storage_dir)
    loaded, record = load_stored_dataset(saved.id, db_path=db_path, storage_dir=storage_dir)

    assert len(records) == 1
    assert record.file_name == source_path.name
    assert record.context["company_or_project"] == "Retail demo"
    assert loaded.dataframe.equals(ingestion.dataframe)
    assert Path(record.storage_path).exists()

    assert delete_stored_dataset(saved.id, db_path=db_path, storage_dir=storage_dir) is True
    assert list_stored_datasets(db_path=db_path, storage_dir=storage_dir) == []
    assert not Path(record.storage_path).exists()
