from __future__ import annotations

from core.powerbi import load_powerbi_config, powerbi_setup_checklist, required_powerbi_settings


def test_powerbi_config_reports_missing_required_settings(monkeypatch):
    for name in [
        "POWERBI_TENANT_ID",
        "POWERBI_CLIENT_ID",
        "POWERBI_CLIENT_SECRET",
        "POWERBI_WORKSPACE_ID",
        "POWERBI_REPORT_ID",
    ]:
        monkeypatch.delenv(name, raising=False)

    config = load_powerbi_config({})

    assert not config.is_configured
    assert "POWERBI_CLIENT_SECRET" in config.missing_required


def test_powerbi_config_uses_server_side_mapping_without_exposing_secret():
    config = load_powerbi_config(
        {
            "POWERBI_TENANT_ID": "tenant-1234567890",
            "POWERBI_CLIENT_ID": "client-1234567890",
            "POWERBI_CLIENT_SECRET": "super-secret-value",
            "POWERBI_WORKSPACE_ID": "workspace-1234567890",
            "POWERBI_REPORT_ID": "report-1234567890",
            "POWERBI_DATASET_ID": "dataset-1234567890",
            "POWERBI_RLS_USERNAME": "viewer@example.com",
            "POWERBI_RLS_ROLES": "sales, leadership",
            "POWERBI_TOKEN_LIFETIME_MINUTES": "30",
        }
    )

    summary = config.public_summary()

    assert config.is_configured
    assert config.rls_roles == ("sales", "leadership")
    assert config.token_lifetime_minutes == 30
    assert "super-secret-value" not in str(summary)
    assert summary["RLS username"] == "viewer@example.com"


def test_powerbi_setup_metadata_uses_placeholders_only():
    settings = required_powerbi_settings()
    checklist = powerbi_setup_checklist()

    assert any(item["Setting"] == "POWERBI_REPORT_ID" for item in settings)
    assert any("capacity" in item.lower() for item in checklist)
