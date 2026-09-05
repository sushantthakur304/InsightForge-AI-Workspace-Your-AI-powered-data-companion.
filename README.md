# InsightForge AI

InsightForge AI is a Streamlit MVP for turning messy business datasets into clean, analyzable, decision-ready information. It guides users through upload, profiling, cleaning recommendations, statistical analysis, dashboard exploration, grounded insight generation, and downloadable management reports.

## Main Features

- Upload CSV, Excel, JSON, and Parquet files.
- Select one or more Excel sheets, analyze sheets separately, and combine compatible sheets.
- Profile row counts, columns, missingness, duplicates, data types, unique values, memory use, identifier columns, and sensitive fields.
- Score data quality across completeness, validity, consistency, uniqueness, accuracy indicators, and data-type reliability.
- Review cleaning recommendations before any change is applied.
- Apply a reversible cleaning pipeline with an audit log, undo/reset controls, saved cleaning configurations, and key-column duplicate handling.
- Calculate descriptive statistics, correlations, group comparisons, time summaries, Pareto analysis, anomalies, missing-data patterns, and selected inferential tests.
- Generate interactive Plotly dashboards with business-context-aware charts and filters.
- Produce deterministic business insights without an AI key, with optional API-backed insight generation.
- Download cleaned data, Excel analysis workbook, PDF report, HTML report, quality report, chart images, audit log, and cleaning configuration.

## Screenshots

Screenshots can be added after running the app locally with `sample_data/messy_sales_data.csv`.

## Technology Stack

- Python 3.11+
- Streamlit
- Pandas, Polars, NumPy
- SciPy, scikit-learn
- Plotly
- ReportLab
- OpenPyXL, XlsxWriter, xlrd
- Pydantic
- Pytest
- SQLite

## Architecture

```text
.
|-- app.py
|-- components/
|-- core/
|   |-- ingestion.py
|   |-- profiler.py
|   |-- cleaning.py
|   |-- validation.py
|   |-- statistics.py
|   |-- visualization.py
|   |-- insights.py
|   |-- reporting.py
|   |-- exporting.py
|   |-- history.py
|   `-- security.py
|-- models/
|-- sample_data/
|-- tests/
|-- .streamlit/
|-- .env.example
|-- requirements.txt
`-- LICENSE
```

The Streamlit interface in `app.py` is intentionally thin. Most business logic lives in `core/`, so a future FastAPI backend and React/Next.js frontend can reuse the ingestion, profiling, cleaning, analysis, insight, and export engines.

## Local Installation

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### macOS and Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Environment Variables

Copy `.env.example` to `.env` if you want to configure optional settings. The app works without an AI API key.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS and Linux:

```bash
cp .env.example .env
```

Optional AI mode:

- `INSIGHTFORGE_AI_PROVIDER=openai`
- `OPENAI_API_KEY=...`
- `OPENAI_MODEL=gpt-4.1-mini`

The AI layer sends only metadata, aggregate statistics, data-quality summaries, statistical-test summaries, trend summaries, anomaly summaries, and business context. It does not send the full dataset by default.

## Run The Application

Windows PowerShell:

```powershell
.\.venv\Scripts\streamlit.exe run app.py
```

macOS and Linux:

```bash
streamlit run app.py
```

Use `sample_data/messy_sales_data.csv` to test the full workflow quickly.

## Run Tests

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

macOS and Linux:

```bash
pytest
```

The current test suite covers ingestion, profiling, quality checks, cleaning/audit behavior, statistics, deterministic insight fallback, exports, and Streamlit app initialization.

## Deploy Online

This project is ready for Streamlit Community Cloud or any Python app host that supports Streamlit.

### Streamlit Community Cloud

1. Push the project to GitHub.
2. Open https://share.streamlit.io and choose **Create app**.
3. Select the GitHub repository and branch.
4. Set the entrypoint file to `streamlit_app.py`.
5. In advanced settings, choose Python 3.12 and paste secrets from `.streamlit/secrets.example.toml`.
6. Deploy and share the generated `streamlit.app` URL.

### Render, Railway, Heroku-style Hosts, or VPS

Use the included `Procfile`, or configure this start command:

```bash
streamlit run streamlit_app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
```

### Cloud Storage Note

The built-in dataset library stores files on the app server disk under `data/`. That is permanent enough for local use and some single-server deployments, but public cloud platforms can reset local disk on restart or redeploy. For production multi-user use, connect the dataset library to durable external storage such as S3, Google Cloud Storage, Supabase, or PostgreSQL-backed object storage.

## Supported File Types

- `.csv`
- `.xlsx`
- `.xls`
- `.json`
- `.parquet`

Excel workbooks show available sheets. Compatible sheets can be combined; incompatible schemas are reported before analysis. Loaded sheets can be switched from the sidebar and analyzed separately without re-uploading.

## Privacy

InsightForge AI processes files locally by default. When dataset library storage is enabled, uploaded datasets are saved on the configured server disk; otherwise they stay in the current app session. The app avoids logging complete sensitive data. Sensitive-looking columns such as emails, phone numbers, addresses, IDs, and payment fields are detected and can be masked in previews. Spreadsheet exports protect against formula injection.

## Known Limitations

- Fuzzy duplicate detection is advisory and conservative.
- AI recommendations are deterministic unless an API provider is configured.
- Chart PNG export requires Kaleido, which is included in `requirements.txt`.
- `.xls` support depends on `xlrd`; malformed legacy workbooks may fail with a clear error.
- Statistical tests are selected conservatively and skipped when assumptions or sample sizes are weak.
- Real-world accuracy is not claimed unless external reference data is supplied.

## Future Roadmap

- FastAPI service layer with authenticated analysis jobs.
- React/Next.js frontend.
- Persistent workspace projects and analysis history.
- Richer validation-rule builder and reusable policy templates.
- Reference-data checks for real-world accuracy validation.
- Role-based governance, sharing, and scheduled refreshes.
