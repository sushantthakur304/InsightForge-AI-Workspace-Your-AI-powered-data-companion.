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
- Explore a premium analytical dashboard with dataset-aware KPIs, date/category/search filters, trend analysis, segment comparisons, data downloads, and computed executive insights.
- Optionally embed a real authorized Power BI report with server-side token generation. When Power BI is not configured, the app uses the native local Streamlit dashboard and clearly labels it as such.
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
- Supabase (optional production backend: Postgres, Storage, and row-level access control)

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
|   |-- analytics_dashboard.py
|   |-- visualization.py
|   |-- insights.py
|   |-- powerbi.py
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

## Analytical Dashboard

The **Analytical Dashboard** is generated from the active uploaded or saved dataset. It infers safe date, measure, and dimension candidates from the cleaned dataframe, excludes identifier-like numeric columns from default sums, and lets the user override the selected fields.

- **Header:** shows the active dataset name, row count, column count, and last processed timestamp.
- **Filter toolbar:** supports date range filtering, primary measure/aggregation selection, primary segment selection, searchable row filtering, categorical filters, active filter indicators, and reset.
- **KPI cards:** show filtered record count, selected metric, completeness, top segment, date coverage, or duplicate count depending on the available data.
- **Charts:** show trend, category comparison, distribution, relationship checks, and missingness only when the dataset supports them.
- **Insights:** separates factual observations, suggested next actions, and reliability notes. It does not infer causation from correlation.
- **Data table and export:** previews the filtered dataset with sensitive masking and provides a filtered CSV download.

KPI formulas are displayed in the UI. Count-based metrics use filtered record counts; numeric metrics aggregate only valid numeric values and report excluded missing or invalid values.

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

Optional Power BI Embedded mode:

- `POWERBI_TENANT_ID=...`
- `POWERBI_CLIENT_ID=...`
- `POWERBI_CLIENT_SECRET=...`
- `POWERBI_WORKSPACE_ID=...`
- `POWERBI_REPORT_ID=...`
- `POWERBI_DATASET_ID=...`
- `POWERBI_RLS_USERNAME=...`
- `POWERBI_RLS_ROLES=...`
- `POWERBI_TOKEN_LIFETIME_MINUTES=45`

Power BI settings belong in Streamlit secrets or environment variables, never in browser-side code. The app generates embed tokens on the server and does not send uploaded local datasets to Power BI. Prepare or refresh the Power BI semantic model separately, and use workspace permissions plus row-level security when private data is involved. Do not use Power BI **Publish to web** for private uploaded datasets because it creates a public unauthenticated report link.

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

The current test suite covers ingestion, profiling, quality checks, cleaning/audit behavior, statistics, deterministic insight fallback, exports, analytical dashboard logic, Power BI configuration helpers, and Streamlit app initialization.

## Production workspaces (Supabase)

For a multi-user deployment, InsightForge uses **Supabase** as the production foundation: private object storage for files, PostgreSQL for project history, and database-enforced workspace roles. Local SQLite and the local dataset directory remain the default for development.

1. Create a Supabase project and apply [the production migration](supabase/migrations/20260908_production_workspaces.sql).
2. Create an OIDC application with your identity provider (Google Workspace, Microsoft Entra ID, Okta, or Auth0) and configure Streamlit's `[auth]` settings from `.streamlit/secrets.example.toml`.
3. Store the following only in the deployment secret manager: `INSIGHTFORGE_STORAGE_BACKEND=supabase`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY`.
4. Start a separate worker process with `python -m workers.production_worker`. Files at or above `INSIGHTFORGE_BACKGROUND_FILE_THRESHOLD_MB` are queued for background profiling. Schedule `refresh_dataset` jobs only from hosts in `INSIGHTFORGE_REFRESH_ALLOWED_HOSTS`.

The service-role key never reaches a browser. The app first verifies the Streamlit OIDC identity, then confirms that identity's workspace membership before any server-side Supabase operation. The migration also enables row-level policies for direct Supabase clients and team roles: owner, admin, editor, and viewer.

### Accuracy checks and validation policies

- The cleaning step now offers baseline, retail, finance, healthcare operations, marketing, and supply-chain policy templates. Templates add only rules that match columns in the uploaded dataset.
- Configure trusted HTTPS reference sources through `INSIGHTFORGE_REFERENCE_CHECKS_JSON` (example in `.env.example`). A mismatch is a review signal with source provenance, never an unsupported real-world accuracy claim.

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

The built-in dataset library stores files on the app server disk under `data/` in local mode. For production multi-user deployments, enable the Supabase workspace backend above instead of relying on server disk or SQLite.

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

- Workspace invitation and member-management screens.
- Additional managed data connectors for scheduled refreshes.
- FastAPI service layer and React/Next.js frontend for high-volume deployments.
