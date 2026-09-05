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

## Dataset Storage Note

The app has local dataset storage under `data/` by default. On a public cloud service, that server disk may reset when the app restarts, redeploys, or moves machines. For real permanent multi-user storage, connect the dataset library to an external service such as S3, Google Cloud Storage, Supabase, or PostgreSQL-backed object storage.

Do not commit `.env`, `.streamlit/secrets.toml`, `data/`, or uploaded customer files.
