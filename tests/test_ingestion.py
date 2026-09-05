from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest

from core.ingestion import load_dataset, list_excel_sheets


def test_csv_ingestion_loads_sample_dataset():
    result = load_dataset("sample_data/messy_sales_data.csv")

    assert result.file_type == ".csv"
    assert result.dataframe.shape[0] == 20
    assert "Sales Amount" in result.dataframe.columns
    assert result.active_sheet == "Data"


def test_excel_ingestion_lists_and_combines_compatible_sheets():
    buffer = BytesIO()
    first = pd.DataFrame({"region": ["North"], "sales": [10]})
    second = pd.DataFrame({"region": ["South"], "sales": [20]})
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        first.to_excel(writer, sheet_name="Jan", index=False)
        second.to_excel(writer, sheet_name="Feb", index=False)

    data = buffer.getvalue()
    assert list_excel_sheets(data) == ["Jan", "Feb"]

    result = load_dataset(data, filename="workbook.xlsx", selected_sheets=["Jan", "Feb"], combine_sheets=True)

    assert result.combined is True
    assert result.active_sheet == "Combined"
    assert result.dataframe.shape[0] == 2
    assert "source_sheet" in result.dataframe.columns


def test_excel_ingestion_warns_on_incompatible_sheets():
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        pd.DataFrame({"region": ["North"], "sales": [10]}).to_excel(writer, sheet_name="Sales", index=False)
        pd.DataFrame({"region": ["North"], "cost": [8]}).to_excel(writer, sheet_name="Costs", index=False)

    result = load_dataset(buffer.getvalue(), filename="workbook.xlsx", selected_sheets=["Sales", "Costs"], combine_sheets=True)

    assert result.combined is False
    assert result.schema_warnings


def test_unsupported_file_extension_is_rejected():
    with pytest.raises(ValueError, match="Unsupported file extension"):
        load_dataset(b"hello", filename="data.txt")

