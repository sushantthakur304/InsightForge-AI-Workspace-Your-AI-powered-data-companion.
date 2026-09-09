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
