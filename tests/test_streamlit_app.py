from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from app import format_file_size
from core.dataset_store import list_stored_datasets


def test_file_size_formatter_uses_readable_units():
    assert format_file_size(0) == "0 B"
    assert format_file_size(999) == "999 B"
    assert format_file_size(1192883) == "1.1 MB"


def test_streamlit_app_initializes_workflow():
    app_path = Path(__file__).resolve().parents[1] / "app.py"

    app = AppTest.from_file(str(app_path), default_timeout=15).run()

    assert not app.exception
    assert any("Upload Data" == item.value for item in app.subheader)
    assert any("Choose a business dataset" == item.label for item in app.file_uploader)
    assert any("Workflow" in item.label for item in app.radio)


def test_profile_page_shows_readable_dataset_details():
    project_root = Path(__file__).resolve().parents[1]
    app_path = project_root / "app.py"
    csv_path = project_root / "sample_data" / "messy_sales_data.csv"

    app = AppTest.from_file(str(app_path), default_timeout=20).run()
    app.toggle(key="save_upload_permanently").set_value(False).run()
    app.file_uploader[0].upload(csv_path.name, csv_path.read_bytes(), "text/csv").run()
    app.button(key="load_uploaded_dataset").click().run()

    assert not app.exception
    assert app.session_state["step"] == 1
    assert not app.json
    details = app.table[0].value["value"].to_dict()
    rendered_details = " ".join(str(value) for value in details.values())

    assert details[":material/description: File"] == "messy_sales_data.csv"
    assert details[":material/storage: Size"] == "2.2 KB"
    assert details[":material/database: Storage"] == "Current browser session only"
    assert "file_size_bytes" not in rendered_details
    assert "file_name" not in rendered_details


def test_upload_can_save_to_permanent_dataset_library(tmp_path, monkeypatch):
    monkeypatch.setenv("INSIGHTFORGE_STORAGE_DB", str(tmp_path / "library.sqlite3"))
    monkeypatch.setenv("INSIGHTFORGE_STORAGE_DIR", str(tmp_path / "datasets"))
    project_root = Path(__file__).resolve().parents[1]
    app_path = project_root / "app.py"
    csv_path = project_root / "sample_data" / "messy_sales_data.csv"

    app = AppTest.from_file(str(app_path), default_timeout=20).run()
    app.file_uploader[0].upload(csv_path.name, csv_path.read_bytes(), "text/csv").run()
    app.button(key="load_uploaded_dataset").click().run()

    records = list_stored_datasets()

    assert not app.exception
    assert app.session_state["step"] == 1
    assert app.session_state["active_storage_record_id"] == records[0].id
    assert len(records) == 1
    assert records[0].file_name == "messy_sales_data.csv"


def test_analytical_dashboard_renders_with_uploaded_data():
    project_root = Path(__file__).resolve().parents[1]
    app_path = project_root / "app.py"
    csv_path = project_root / "sample_data" / "messy_sales_data.csv"

    app = AppTest.from_file(str(app_path), default_timeout=25).run()
    app.toggle(key="save_upload_permanently").set_value(False).run()
    app.file_uploader[0].upload(csv_path.name, csv_path.read_bytes(), "text/csv").run()
    app.button(key="load_uploaded_dataset").click().run()
    app.session_state["step"] = 4
    app.run()

    assert not app.exception
    assert app.session_state["analysis"] is not None
    assert app.session_state["analysis_last_processed"] is not None
    assert any("Power BI is not configured yet" in item.value for item in app.warning)
