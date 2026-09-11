# Deployment Guide

InsightForge AI is a Streamlit app, so it should be deployed to a Python app host rather than static website hosting.

## Fastest Public Deployment: Streamlit Community Cloud

1. Push this project to a GitHub repository.
2. Go to https://share.streamlit.io and create a new app.
3. Select your repository and branch.
4. Use `streamlit_app.py` as the app file.
5. Open advanced settings and select Python 3.12.
6. Paste secrets from `.streamlit/secrets.example.toml`, filling `OPENAI_API_KEY` only if you want OpenAI-backed insights.
7. Deploy the app and copy the generated `streamlit.app` URL.

## Optional Power BI Embedded

The app can embed a real authorized Power BI report when the required server-side settings are configured in Streamlit secrets or environment variables:

- `POWERBI_TENANT_ID`
- `POWERBI_CLIENT_ID`
- `POWERBI_CLIENT_SECRET`
- `POWERBI_WORKSPACE_ID`
- `POWERBI_REPORT_ID`
- Optional `POWERBI_DATASET_ID`, `POWERBI_RLS_USERNAME`, `POWERBI_RLS_ROLES`, and `POWERBI_TOKEN_LIFETIME_MINUTES`

Uploaded local datasets are not automatically transferred to Power BI. Build or refresh the Power BI semantic model separately, then configure report embedding in this app. Use workspace permissions and row-level security for private data. Do not use Power BI **Publish to web** for confidential uploaded data because it creates a public unauthenticated report link.

## Generic Python Hosts

Hosts such as Render, Railway, Heroku-style platforms, and VPS servers can use the included `Procfile`.

```text
web: streamlit run streamlit_app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
```

For hosts that do not use `Procfile`, set the start command manually:

```bash
streamlit run streamlit_app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
```

## Production multi-user deployment

Use Supabase for production workspaces. It supplies private object storage, managed PostgreSQL, and row-level policies for owner, admin, editor, and viewer roles.

1. Apply `supabase/migrations/20260908_production_workspaces.sql` to a new Supabase project.
2. Add the following deployment secrets (never commit them):

```text
INSIGHTFORGE_STORAGE_BACKEND=supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=server-only-service-role-key
```

3. Configure a real OIDC provider under `[auth]` in Streamlit secrets. The redirect URL must end in `/oauth2callback` and match the identity-provider registration.
4. Run `python -m workers.production_worker` as a separate worker service. It handles queued large-file profiling and approved scheduled refresh jobs. Set `INSIGHTFORGE_REFRESH_ALLOWED_HOSTS` to a comma-separated allowlist before enabling any refresh connector.

The app will not enable Supabase storage until both the service secrets and a verified user identity are present. Local mode continues to use `data/` and SQLite, which is suitable only for single-user development.

Do not commit `.env`, `.streamlit/secrets.toml`, `data/`, or uploaded customer files.
