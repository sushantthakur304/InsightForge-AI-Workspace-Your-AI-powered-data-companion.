from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
POWERBI_API_ROOT = "https://api.powerbi.com/v1.0/myorg"
POWERBI_AUTHORITY_HOST = "https://login.microsoftonline.com"


class PowerBIConfigurationError(RuntimeError):
    """Raised when the Power BI integration is incomplete."""


class PowerBIEmbedError(RuntimeError):
    """Raised when Power BI token or report retrieval fails."""


@dataclass(frozen=True)
class PowerBIConfig:
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    workspace_id: str | None = None
    report_id: str | None = None
    dataset_id: str | None = None
    rls_username: str | None = None
    rls_roles: tuple[str, ...] = ()
    token_lifetime_minutes: int = 45

    @property
    def missing_required(self) -> list[str]:
        required = {
            "POWERBI_TENANT_ID": self.tenant_id,
            "POWERBI_CLIENT_ID": self.client_id,
            "POWERBI_CLIENT_SECRET": self.client_secret,
            "POWERBI_WORKSPACE_ID": self.workspace_id,
            "POWERBI_REPORT_ID": self.report_id,
        }
        return [name for name, value in required.items() if not value]

    @property
    def is_configured(self) -> bool:
        return not self.missing_required

    def public_summary(self) -> dict[str, str]:
        return {
            "Tenant ID": _mask(self.tenant_id),
            "Client ID": _mask(self.client_id),
            "Workspace ID": _mask(self.workspace_id),
            "Report ID": _mask(self.report_id),
            "Dataset ID": _mask(self.dataset_id),
            "RLS username": self.rls_username or "Not set",
            "RLS roles": ", ".join(self.rls_roles) if self.rls_roles else "Not set",
        }


@dataclass(frozen=True)
class PowerBIEmbedPayload:
    report_id: str
    report_name: str
    embed_url: str
    embed_token: str
    expiration: str | None
    dataset_id: str | None


def _mask(value: str | None) -> str:
    if not value:
        return "Not set"
    if len(value) <= 8:
        return "Set"
    return f"{value[:4]}...{value[-4:]}"


def _coerce_secret(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _lookup(name: str, secrets: Mapping[str, Any] | None = None) -> str | None:
    if secrets and name in secrets:
        return _coerce_secret(secrets.get(name))
    return _coerce_secret(os.getenv(name))


def load_powerbi_config(secrets: Mapping[str, Any] | None = None) -> PowerBIConfig:
    roles_raw = _lookup("POWERBI_RLS_ROLES", secrets)
    roles = tuple(role.strip() for role in roles_raw.split(",") if role.strip()) if roles_raw else ()
    lifetime_raw = _lookup("POWERBI_TOKEN_LIFETIME_MINUTES", secrets)
    try:
        lifetime = int(lifetime_raw) if lifetime_raw else 45
    except ValueError:
        lifetime = 45
    lifetime = max(10, min(lifetime, 60))
    return PowerBIConfig(
        tenant_id=_lookup("POWERBI_TENANT_ID", secrets),
        client_id=_lookup("POWERBI_CLIENT_ID", secrets),
        client_secret=_lookup("POWERBI_CLIENT_SECRET", secrets),
        workspace_id=_lookup("POWERBI_WORKSPACE_ID", secrets),
        report_id=_lookup("POWERBI_REPORT_ID", secrets),
        dataset_id=_lookup("POWERBI_DATASET_ID", secrets),
        rls_username=_lookup("POWERBI_RLS_USERNAME", secrets),
        rls_roles=roles,
        token_lifetime_minutes=lifetime,
    )


def required_powerbi_settings() -> list[dict[str, str]]:
    return [
        {"Setting": "POWERBI_TENANT_ID", "Purpose": "Microsoft Entra tenant that owns the Power BI workspace."},
        {"Setting": "POWERBI_CLIENT_ID", "Purpose": "Application/client ID for the service principal."},
        {"Setting": "POWERBI_CLIENT_SECRET", "Purpose": "Client secret stored only in Streamlit secrets or environment variables."},
        {"Setting": "POWERBI_WORKSPACE_ID", "Purpose": "Power BI workspace/group ID that contains the report."},
        {"Setting": "POWERBI_REPORT_ID", "Purpose": "Report ID for the existing Power BI report to embed."},
        {"Setting": "POWERBI_DATASET_ID", "Purpose": "Optional semantic model ID. If omitted, the report metadata dataset ID is used."},
        {"Setting": "POWERBI_RLS_USERNAME", "Purpose": "Optional effective identity username for row-level security."},
        {"Setting": "POWERBI_RLS_ROLES", "Purpose": "Optional comma-separated RLS role names."},
        {"Setting": "POWERBI_TOKEN_LIFETIME_MINUTES", "Purpose": "Optional embed-token lifetime from 10 to 60 minutes."},
    ]


def powerbi_setup_checklist() -> list[str]:
    return [
        "Create or reuse a Microsoft Entra app registration and service principal.",
        "Allow the service principal to use Power BI APIs in the tenant settings.",
        "Grant the service principal access to the Power BI workspace that contains the report.",
        "Publish a Power BI report backed by a semantic model whose fields match the intended dataset structure.",
        "Configure row-level security or workspace isolation for each user, tenant, or customer as required.",
        "Use Power BI Embedded, Premium, or Fabric capacity for production embedding.",
        "Store only placeholder-free secrets in Streamlit secrets or server environment variables.",
    ]


def _http_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PowerBIEmbedError(f"Power BI API returned HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise PowerBIEmbedError(f"Power BI API request failed: {exc.reason}") from exc


def _request_entra_access_token(config: PowerBIConfig) -> str:
    token_url = f"{POWERBI_AUTHORITY_HOST}/{config.tenant_id}/oauth2/v2.0/token"
    form = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "scope": POWERBI_SCOPE,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        token_url,
        data=form,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PowerBIEmbedError(f"Microsoft Entra token request failed with HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise PowerBIEmbedError(f"Microsoft Entra token request failed: {exc.reason}") from exc
    token = payload.get("access_token")
    if not token:
        raise PowerBIEmbedError("Microsoft Entra did not return an access token.")
    return str(token)


def _get_report_metadata(config: PowerBIConfig, access_token: str) -> dict[str, Any]:
    url = f"{POWERBI_API_ROOT}/groups/{config.workspace_id}/reports/{config.report_id}"
    return _http_json(url, headers={"Authorization": f"Bearer {access_token}"})


def _generate_embed_token(config: PowerBIConfig, access_token: str, dataset_id: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "reports": [{"id": config.report_id, "allowEdit": False}],
        "lifetimeInMinutes": config.token_lifetime_minutes,
    }
    if dataset_id:
        body["datasets"] = [{"id": dataset_id}]
    if dataset_id and config.rls_username and config.rls_roles:
        body["identities"] = [
            {
                "username": config.rls_username,
                "roles": list(config.rls_roles),
                "datasets": [dataset_id],
            }
        ]
    return _http_json(
        f"{POWERBI_API_ROOT}/GenerateToken",
        method="POST",
        headers={"Authorization": f"Bearer {access_token}"},
        body=body,
    )


def generate_powerbi_embed_payload(config: PowerBIConfig) -> PowerBIEmbedPayload:
    if not config.is_configured:
        raise PowerBIConfigurationError(f"Missing Power BI settings: {', '.join(config.missing_required)}")
    access_token = _request_entra_access_token(config)
    report = _get_report_metadata(config, access_token)
    dataset_id = config.dataset_id or report.get("datasetId")
    token_payload = _generate_embed_token(config, access_token, dataset_id)
    embed_token = token_payload.get("token")
    if not embed_token:
        raise PowerBIEmbedError("Power BI did not return an embed token.")
    embed_url = report.get("embedUrl")
    if not embed_url:
        raise PowerBIEmbedError("Power BI report metadata did not include an embed URL.")
    return PowerBIEmbedPayload(
        report_id=str(config.report_id),
        report_name=str(report.get("name") or "Power BI report"),
        embed_url=str(embed_url),
        embed_token=str(embed_token),
        expiration=token_payload.get("expiration"),
        dataset_id=str(dataset_id) if dataset_id else None,
    )


def build_powerbi_embed_html(payload: PowerBIEmbedPayload) -> str:
    config = {
        "type": "report",
        "id": payload.report_id,
        "embedUrl": payload.embed_url,
        "accessToken": payload.embed_token,
    }
    config_json = json.dumps(config)
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <script src="https://cdn.jsdelivr.net/npm/powerbi-client@2.23.7/dist/powerbi.min.js"></script>
  <style>
    html, body, #reportContainer {{
      width: 100%;
      height: 100%;
      margin: 0;
      background: #ffffff;
      overflow: hidden;
      font-family: Inter, Segoe UI, Arial, sans-serif;
    }}
    #reportContainer {{
      min-height: 720px;
      border: 1px solid #E5E7EB;
      border-radius: 12px;
    }}
    #message {{
      padding: 18px;
      color: #111827;
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <div id="reportContainer"></div>
  <div id="message" hidden></div>
  <script>
    const baseConfig = {config_json};
    const models = window["powerbi-client"].models;
    const embedConfig = {{
      ...baseConfig,
      tokenType: models.TokenType.Embed,
      permissions: models.Permissions.Read,
      settings: {{
        panes: {{
          filters: {{ visible: false, expanded: false }},
          pageNavigation: {{ visible: true }}
        }},
        background: models.BackgroundType.Transparent
      }}
    }};
    const container = document.getElementById("reportContainer");
    const message = document.getElementById("message");
    try {{
      const report = powerbi.embed(container, embedConfig);
      report.on("error", event => {{
        message.hidden = false;
        message.textContent = "Power BI report failed to load. Check workspace access, report ID, token lifetime, and RLS configuration.";
      }});
    }} catch (error) {{
      message.hidden = false;
      message.textContent = "Power BI embed initialization failed.";
    }}
  </script>
</body>
</html>
"""
