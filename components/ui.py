from __future__ import annotations

import base64
import html
from pathlib import Path

import streamlit as st


STEP_META = [
    (
        "cloud_upload",
        "Upload Data",
        "Upload a file or open a saved dataset.",
    ),
    (
        "database",
        "Profile Data",
        "Profile datatypes, missing values, and quality.",
    ),
    (
        "cleaning_services",
        "Review Cleaning",
        "Review cleanup recommendations and risk.",
    ),
    (
        "query_stats",
        "Run Analysis",
        "Analyze trends, segments, anomalies, and KPIs.",
    ),
    (
        "monitoring",
        "Analytical Dashboard",
        "Explore KPIs, filters, trends, and report views.",
    ),
    (
        "download",
        "Download Files",
        "Download reports, cleaned data, and audit logs.",
    ),
]

STEP_LABELS = [step[1] for step in STEP_META]


def render_sidebar_brand() -> None:
    """Render the uploaded InsightForge identity at the top of the sidebar."""
    logo_path = Path(__file__).resolve().parents[1] / "assets" / "insightforge-logo.png"
    logo_data = base64.b64encode(logo_path.read_bytes()).decode("ascii")
    st.html(
        f"""
        <div class="if-sidebar-brand" aria-label="InsightForge AI Workspace">
            <img class="if-sidebar-brand-image" src="data:image/png;base64,{logo_data}" alt="InsightForge AI Workspace logo">
        </div>
        """
    )


def inject_global_styles(theme_mode: str = "Light") -> None:
    dark = theme_mode.lower() == "dark"
    body_font = '"Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    heading_font = '"Poppins", "Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'

    background = "#0b1020" if dark else "#f7f8fb"
    background_alt = "#111827" if dark else "#eef3f8"
    surface = "#121a2b" if dark else "#ffffff"
    surface_elevated = "#172236" if dark else "rgba(255, 255, 255, 0.86)"
    surface_soft = "#1c2941" if dark else "#f2f7fb"
    text = "#ecf1f8" if dark else "#111827"
    muted = "#a9b5c8" if dark else "#687385"
    subtle = "#76849a" if dark else "#7a8494"
    border = "#2b3a52" if dark else "#dce4ed"
    border_strong = "#42526b" if dark else "#c7d1dc"
    shadow = "0 24px 60px rgba(0, 0, 0, 0.36)" if dark else "0 22px 48px rgba(36, 48, 74, 0.13)"
    shadow_soft = "0 14px 32px rgba(0, 0, 0, 0.28)" if dark else "0 12px 30px rgba(31, 41, 55, 0.10)"
    sidebar_bg = "#0b1020" if dark else "#f4f6fa"
    sidebar_panel = "#141f33" if dark else "rgba(255, 255, 255, 0.72)"
    input_bg = "#111b2d" if dark else "#ffffff"
    hero_text = "#f8fbff" if dark else "#0f172a"
    hero_subtext = "#d8e5f3" if dark else "#1f2937"
    hero_gradient = (
        "linear-gradient(102deg, #172036 0%, #21516a 48%, #13827d 100%)"
        if dark
        else "linear-gradient(102deg, #ff7c72 0%, #ffd486 47%, #65ddd8 100%)"
    )

    st.html(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,400,0,0&display=swap');

        :root {{
            --if-bg: {background};
            --if-bg-alt: {background_alt};
            --if-surface: {surface};
            --if-surface-elevated: {surface_elevated};
            --if-surface-soft: {surface_soft};
            --if-text: {text};
            --if-muted: {muted};
            --if-subtle: {subtle};
            --if-border: {border};
            --if-border-strong: {border_strong};
            --if-shadow: {shadow};
            --if-shadow-soft: {shadow_soft};
            --if-primary: #fb806f;
            --if-secondary: #61d9d4;
            --if-accent: #f3bc63;
            --if-green: #1f9d72;
            --if-blue: #4077df;
            --if-red: #dc5b53;
        }}

        html,
        body,
        .stApp {{
            font-family: {body_font};
        }}

        .stApp {{
            background:
                linear-gradient(125deg, rgba(251, 128, 111, 0.10) 0%, rgba(247, 248, 251, 0) 26%),
                linear-gradient(90deg, rgba(97, 217, 212, 0.08) 68%, rgba(247, 248, 251, 0) 100%),
                linear-gradient(180deg, {background_alt} 0%, {background} 36%, {background} 100%);
            color: var(--if-text);
        }}

        .block-container {{
            padding-top: 3.25rem;
            padding-bottom: 3rem;
            max-width: 940px;
            position: relative;
            z-index: 1;
        }}

        h1,
        h2,
        h3,
        [data-testid="stHeading"] [data-heading-text] {{
            color: var(--if-text);
            font-family: {heading_font};
            letter-spacing: 0;
        }}

        h2,
        h3 {{
            font-weight: 700;
        }}

        p,
        label,
        span,
        div {{
            letter-spacing: 0;
        }}

        [data-testid="stToolbar"] {{
            right: 0.75rem;
        }}

        [data-testid="stSidebar"] {{
            width: 215px !important;
            min-width: 215px !important;
            max-width: 215px !important;
            background:
                linear-gradient(180deg, rgba(255, 255, 255, 0.42), rgba(255, 255, 255, 0)),
                {sidebar_bg};
            border-right: 1px solid {"#222d40" if dark else "#e3e8ef"};
            box-shadow: 12px 0 36px rgba(15, 23, 42, 0.08);
        }}

        [data-testid="stSidebar"] > div:first-child {{
            width: 215px !important;
            min-width: 215px !important;
            max-width: 215px !important;
        }}

        [data-testid="stSidebar"] * {{
            color: {"#edf4ff" if dark else "#111827"};
        }}

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] label {{
            color: {"#edf4ff" if dark else "#111827"};
        }}

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {{
            font-size: 15px;
            margin-top: 0.55rem;
            margin-bottom: 0.2rem;
        }}

        [data-testid="stSidebar"] div[role="radiogroup"],
        [data-testid="stSidebar"] [data-baseweb="segmented-control"] {{
            background: {sidebar_panel};
            border: 1px solid {"#24344f" if dark else "#e2e8f0"};
            border-radius: 8px;
            padding: 6px;
            box-shadow: 0 12px 28px rgba(15, 23, 42, 0.05);
        }}

        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{
            color: {"#bdc9d9" if dark else "#6b7280"};
        }}

        .if-sidebar-brand {{
            margin: 0.15rem 0 0.9rem;
            background: transparent;
            border: 0;
            box-shadow: none;
        }}

        .if-sidebar-brand-image {{
            display: block;
            width: 100%;
            height: auto;
        }}

        [translate="no"][data-testid*="Icon"],
        [data-testid="stHeadingIcon"],
        [data-testid="stHeadingIconWrapper"] span,
        [data-testid="stBadge"] [translate="no"] {{
            font-family: "Material Symbols Rounded" !important;
            font-weight: normal !important;
            font-style: normal !important;
            line-height: 1 !important;
            letter-spacing: 0 !important;
            text-transform: none !important;
            white-space: nowrap !important;
            overflow-wrap: normal !important;
            direction: ltr !important;
            font-variation-settings: "FILL" 0, "wght" 400, "GRAD" 0, "opsz" 24 !important;
        }}

        div[data-testid="stVerticalBlock"] > div:has(> .if-hero-wrap) {{
            margin-bottom: 0;
        }}

        .if-hero-wrap {{
            width: min(100%, 860px);
            margin: 0 auto 16px;
        }}

        .if-shell-title {{
            min-height: 122px;
            padding: 25px 28px 23px;
            border: 1px solid rgba(255, 255, 255, 0.52);
            border-radius: 8px;
            background: {hero_gradient};
            box-shadow:
                var(--if-shadow),
                0 0 62px rgba(97, 217, 212, 0.22),
                inset 0 1px 0 rgba(255, 255, 255, 0.46);
            position: relative;
            overflow: hidden;
            text-align: center;
            transform-style: preserve-3d;
        }}

        .if-shell-title::before {{
            content: "";
            position: absolute;
            inset: 0;
            background:
                linear-gradient(110deg, rgba(255, 255, 255, 0.28), rgba(255, 255, 255, 0) 42%),
                linear-gradient(180deg, rgba(255, 255, 255, 0.18), rgba(255, 255, 255, 0));
            pointer-events: none;
        }}

        .if-title-kicker,
        .if-title-main,
        .if-title-sub {{
            position: relative;
            z-index: 1;
        }}

        .if-title-kicker {{
            color: {hero_subtext};
            font-size: 10px;
            line-height: 1.35;
            font-weight: 700;
            text-transform: uppercase;
            margin-bottom: 7px;
        }}

        .if-title-main {{
            color: {hero_text};
            font-family: {heading_font};
            font-size: 29px;
            line-height: 1.16;
            font-weight: 750;
            overflow-wrap: anywhere;
            text-shadow: 0 12px 24px rgba(255, 255, 255, 0.20);
        }}

        .if-title-sub {{
            color: {hero_subtext};
            font-size: 13px;
            line-height: 1.45;
            margin-top: 7px;
            font-weight: 500;
        }}

        .if-status-strip {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
            margin-top: 12px;
        }}

        .if-status-chip {{
            min-height: 32px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 7px;
            border: 1px solid var(--if-border);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.66);
            color: var(--if-text);
            font-size: 12px;
            font-weight: 600;
            box-shadow:
                0 8px 18px rgba(31, 41, 55, 0.08),
                inset 0 1px 0 rgba(255, 255, 255, 0.78);
            backdrop-filter: blur(10px);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .if-material-icon {{
            font-family: "Material Symbols Rounded";
            font-weight: normal;
            font-style: normal;
            font-size: 16px;
            line-height: 1;
            display: inline-block;
            text-transform: none;
            white-space: nowrap;
            overflow-wrap: normal;
            direction: ltr;
            color: var(--if-primary);
            font-variation-settings: "FILL" 0, "wght" 400, "GRAD" 0, "opsz" 24;
        }}

        .if-step-grid {{
            width: min(100%, 860px);
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 14px;
            margin: 14px auto 24px;
            perspective: 1000px;
        }}

        .if-step-card {{
            min-height: 92px;
            display: grid;
            grid-template-columns: 42px minmax(0, 1fr);
            gap: 12px;
            align-items: center;
            border: 1px solid var(--if-border);
            border-radius: 8px;
            padding: 14px;
            background:
                linear-gradient(145deg, rgba(255, 255, 255, 0.95), rgba(255, 255, 255, 0.72)),
                var(--if-surface-elevated);
            box-shadow:
                0 12px 22px rgba(15, 23, 42, 0.10),
                inset 0 1px 0 rgba(255, 255, 255, 0.72);
            transform: translateY(0) rotateX(0);
            transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
        }}

        .if-step-card:hover {{
            transform: translateY(-2px) rotateX(1deg);
            border-color: var(--if-border-strong);
            box-shadow: 0 18px 34px rgba(15, 23, 42, 0.13);
        }}

        .if-step-card-active {{
            border-color: rgba(251, 128, 111, 0.48);
            background:
                linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(252, 244, 235, 0.92)),
                var(--if-surface);
        }}

        .if-step-icon {{
            width: 38px;
            height: 38px;
            display: grid;
            place-items: center;
            border-radius: 8px;
            background: #fff0ec;
            box-shadow:
                inset 0 1px 0 rgba(255, 255, 255, 0.72),
                0 8px 18px rgba(251, 128, 111, 0.12);
        }}

        .if-step-icon .if-material-icon {{
            color: var(--if-primary);
            font-size: 22px;
        }}

        .if-step-body {{
            min-width: 0;
        }}

        .if-step-title {{
            color: var(--if-text);
            font-size: 14px;
            line-height: 1.25;
            font-weight: 750;
            font-family: {heading_font};
            overflow-wrap: anywhere;
        }}

        .if-step-index {{
            color: var(--if-muted);
            font-size: 12px;
            line-height: 1.25;
            font-weight: 700;
            margin-bottom: 2px;
        }}

        .if-step-desc {{
            color: var(--if-text);
            font-size: 10px;
            line-height: 1.2;
            font-weight: 500;
            margin-top: 2px;
        }}

        .if-step-card-active .if-step-index {{
            color: var(--if-primary);
        }}

        .if-upload-showcase {{
            width: min(100%, 860px);
            min-height: 178px;
            display: grid;
            grid-template-columns: minmax(0, 1.15fr) minmax(230px, 0.85fr);
            align-items: stretch;
            gap: 18px;
            margin: 4px auto 18px;
            border: 1px solid var(--if-border);
            border-radius: 8px;
            background:
                linear-gradient(115deg, rgba(255, 255, 255, 0.94), rgba(255, 255, 255, 0.78)),
                var(--if-surface);
            box-shadow:
                0 20px 42px rgba(15, 23, 42, 0.12),
                inset 0 1px 0 rgba(255, 255, 255, 0.78);
            overflow: hidden;
            position: relative;
        }}

        .if-upload-copy {{
            padding: 20px 0 18px 20px;
            min-width: 0;
        }}

        .if-upload-title {{
            color: var(--if-text);
            font-family: {heading_font};
            font-size: 18px;
            line-height: 1.2;
            font-weight: 750;
            margin-bottom: 8px;
        }}

        .if-upload-kicker {{
            color: var(--if-text);
            font-size: 11px;
            line-height: 1.25;
            font-weight: 700;
            text-transform: uppercase;
            margin-bottom: 4px;
        }}

        .if-upload-text {{
            color: var(--if-text);
            font-size: 12px;
            line-height: 1.38;
            max-width: 410px;
        }}

        .if-upload-concepts {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 8px;
            margin-top: 13px;
        }}

        .if-concept-card {{
            min-height: 52px;
            border: 1px solid var(--if-border);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.76);
            padding: 8px;
            box-shadow: 0 8px 18px rgba(15, 23, 42, 0.07);
        }}

        .if-concept-name {{
            color: var(--if-text);
            font-size: 10px;
            font-weight: 700;
            line-height: 1.2;
            margin-bottom: 6px;
        }}

        .if-mini-bars {{
            display: grid;
            gap: 4px;
        }}

        .if-mini-bars span {{
            display: block;
            height: 4px;
            border-radius: 999px;
            background: var(--if-primary);
        }}

        .if-mini-bars span:nth-child(2) {{
            width: 82%;
            background: var(--if-accent);
        }}

        .if-mini-bars span:nth-child(3) {{
            width: 64%;
            background: var(--if-secondary);
        }}

        .if-upload-visual {{
            position: relative;
            min-height: 178px;
            background:
                linear-gradient(90deg, rgba(255, 255, 255, 0), rgba(97, 217, 212, 0.15)),
                linear-gradient(180deg, rgba(255, 240, 236, 0.55), rgba(255, 255, 255, 0));
            transform-style: preserve-3d;
        }}

        .if-brain {{
            position: absolute;
            width: 94px;
            height: 86px;
            right: 118px;
            top: 42px;
            border: 2px solid #2b3038;
            border-radius: 48% 50% 45% 52%;
            background: linear-gradient(145deg, #ffb19e, #ff8d78);
            box-shadow: 0 18px 32px rgba(251, 128, 111, 0.24);
            transform: rotate(-9deg) translateZ(24px);
        }}

        .if-brain::before,
        .if-brain::after {{
            content: "";
            position: absolute;
            border: 2px solid #2b3038;
            border-left: 0;
            border-bottom: 0;
            border-radius: 999px;
        }}

        .if-brain::before {{
            width: 42px;
            height: 34px;
            left: 15px;
            top: 17px;
        }}

        .if-brain::after {{
            width: 35px;
            height: 28px;
            right: 12px;
            bottom: 13px;
        }}

        .if-eye {{
            position: absolute;
            width: 45px;
            height: 26px;
            right: 220px;
            top: 40px;
            border: 2px solid #2b3038;
            border-radius: 50%;
            background: #fff6e8;
            transform: rotate(-7deg);
            box-shadow: 0 8px 18px rgba(15, 23, 42, 0.12);
        }}

        .if-eye::before {{
            content: "";
            position: absolute;
            width: 12px;
            height: 12px;
            left: 15px;
            top: 5px;
            border-radius: 999px;
            background: #2dd4bf;
            border: 2px solid #2b3038;
        }}

        .if-node-card {{
            position: absolute;
            width: 67px;
            height: 67px;
            right: 68px;
            top: 50px;
            border: 2px solid #2b3038;
            border-radius: 8px;
            background: linear-gradient(145deg, #f8dda2, #5fded6);
            box-shadow: 0 16px 28px rgba(31, 41, 55, 0.16);
            transform: rotate(17deg) translateZ(18px);
        }}

        .if-node-card span {{
            position: absolute;
            width: 7px;
            height: 7px;
            border-radius: 999px;
            background: #fff;
            border: 2px solid #2b3038;
        }}

        .if-node-card span:nth-child(1) {{ left: 13px; top: 14px; }}
        .if-node-card span:nth-child(2) {{ right: 13px; top: 18px; }}
        .if-node-card span:nth-child(3) {{ left: 29px; bottom: 13px; }}

        .if-viz-bars {{
            position: absolute;
            display: flex;
            align-items: flex-end;
            gap: 8px;
            right: 15px;
            bottom: 24px;
            height: 72px;
        }}

        .if-viz-bars span {{
            width: 12px;
            border-radius: 4px 4px 0 0;
            background: var(--if-primary);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.38);
        }}

        .if-viz-bars span:nth-child(1) {{ height: 28px; background: #65ddd8; }}
        .if-viz-bars span:nth-child(2) {{ height: 42px; background: #f3bc63; }}
        .if-viz-bars span:nth-child(3) {{ height: 58px; background: #fb806f; }}
        .if-viz-bars span:nth-child(4) {{ height: 36px; background: #65ddd8; }}

        .if-visual-lines {{
            position: absolute;
            left: 18px;
            bottom: 34px;
            width: 84px;
            display: grid;
            gap: 8px;
        }}

        .if-visual-lines span {{
            height: 5px;
            border-radius: 999px;
            background: #65ddd8;
        }}

        .if-visual-lines span:nth-child(2) {{
            width: 72%;
            background: #fb806f;
        }}

        .if-visual-lines span:nth-child(3) {{
            width: 58%;
            background: #f3bc63;
        }}

        .if-panel,
        .if-soft-panel {{
            width: min(100%, 860px);
            margin-left: auto;
            margin-right: auto;
        }}

        .if-panel {{
            border: 1px solid var(--if-border);
            border-radius: 8px;
            padding: 16px;
            background: var(--if-surface-elevated);
            margin-bottom: 14px;
            box-shadow: var(--if-shadow-soft);
        }}

        .if-soft-panel {{
            border: 1px solid var(--if-border);
            border-radius: 8px;
            padding: 13px 15px;
            background:
                linear-gradient(115deg, rgba(255, 240, 236, 0.82), rgba(236, 252, 251, 0.88)),
                var(--if-surface-soft);
            margin-bottom: 14px;
            color: var(--if-text);
            font-weight: 600;
            box-shadow: 0 10px 24px rgba(31, 41, 55, 0.08);
        }}

        .if-metric {{
            border: 1px solid var(--if-border);
            border-radius: 8px;
            padding: 15px 16px;
            background:
                linear-gradient(145deg, rgba(255, 255, 255, 0.92), rgba(255, 255, 255, 0.72)),
                var(--if-surface-elevated);
            min-height: 104px;
            box-shadow: var(--if-shadow-soft), inset 0 1px 0 rgba(255, 255, 255, 0.68);
            position: relative;
            overflow: hidden;
        }}

        .if-metric::before {{
            content: "";
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: 4px;
            background: linear-gradient(180deg, var(--if-primary), var(--if-secondary));
        }}

        .if-metric-label {{
            color: var(--if-muted);
            font-size: 12px;
            text-transform: uppercase;
            font-weight: 800;
        }}

        .if-metric-value {{
            color: var(--if-text);
            font-size: 28px;
            line-height: 1.25;
            font-weight: 800;
            overflow-wrap: anywhere;
        }}

        .if-metric-note {{
            color: var(--if-muted);
            font-size: 12px;
            margin-top: 4px;
        }}

        div[data-testid="stMetric"] {{
            border: 1px solid var(--if-border);
            border-radius: 8px;
            padding: 14px 16px;
            background:
                linear-gradient(145deg, rgba(255, 255, 255, 0.95), rgba(255, 255, 255, 0.76)),
                var(--if-surface-elevated);
            box-shadow: var(--if-shadow-soft), inset 0 1px 0 rgba(255, 255, 255, 0.68);
            min-height: 106px;
        }}

        div[data-testid="stMetric"] label {{
            color: var(--if-muted);
            font-weight: 750;
            text-transform: uppercase;
            letter-spacing: 0;
        }}

        .stDownloadButton > button,
        .stButton > button {{
            border-radius: 8px;
            border: 1px solid var(--if-border);
            font-weight: 700;
            box-shadow: 0 10px 20px rgba(15, 23, 42, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.52);
        }}

        .stButton > button[kind="primary"],
        .stDownloadButton > button[kind="primary"] {{
            border: 0;
            background: linear-gradient(115deg, #fb806f, #f3bc63 48%, #61d9d4);
            color: #111827;
        }}

        .stButton > button:hover,
        .stDownloadButton > button:hover {{
            border-color: var(--if-border-strong);
            transform: translateY(-1px);
            transition: transform 140ms ease, border-color 140ms ease, box-shadow 140ms ease;
            box-shadow: 0 14px 26px rgba(15, 23, 42, 0.11);
        }}

        [data-testid="stFileUploaderDropzone"] {{
            border-radius: 8px;
            border: 1.5px dashed #9dc4d2;
            background:
                linear-gradient(115deg, rgba(255, 240, 236, 0.50), rgba(236, 252, 251, 0.70)),
                var(--if-surface-elevated);
            box-shadow: var(--if-shadow-soft);
        }}

        [data-testid="stFileUploaderDropzone"] button {{
            border-radius: 8px;
            font-weight: 750;
        }}

        div[data-testid="stDataFrame"] {{
            border-radius: 8px;
            border: 1px solid var(--if-border);
            box-shadow: var(--if-shadow-soft);
            overflow: hidden;
        }}

        div[data-testid="stExpander"],
        div[data-testid="stForm"] {{
            border-color: var(--if-border);
            border-radius: 8px;
            background: var(--if-surface-elevated);
            box-shadow: var(--if-shadow-soft);
        }}

        div[data-testid="stAlert"] {{
            border-radius: 8px;
            border: 1px solid var(--if-border);
        }}

        input,
        textarea,
        [data-baseweb="select"] > div {{
            background-color: {input_bg};
        }}

        [data-testid="stProgress"] > div > div > div > div {{
            background: linear-gradient(90deg, #fb806f, #61d9d4);
        }}

        .if-warning {{
            border-left: 4px solid var(--if-accent);
            padding: 10px 12px;
            background: {"#402719" if dark else "#fff8e8"};
            border-radius: 8px;
            color: var(--if-text);
        }}

        @media (max-width: 760px) {{
            .block-container {{
                padding-top: 3.35rem;
                max-width: 92vw;
            }}

            .if-status-strip {{
                grid-template-columns: 1fr;
            }}

            .if-step-grid {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }}

            .if-upload-showcase {{
                grid-template-columns: 1fr;
            }}

            .if-upload-copy {{
                padding: 18px;
            }}

            .if-upload-visual {{
                min-height: 152px;
            }}
        }}

        @media (max-width: 560px) {{
            [data-testid="stSidebar"],
            [data-testid="stSidebar"] > div:first-child {{
                width: 235px !important;
                min-width: 235px !important;
                max-width: 235px !important;
            }}

            .block-container {{
                padding-left: 0.9rem;
                padding-right: 0.9rem;
                max-width: 100%;
            }}

            .if-shell-title {{
                min-height: 112px;
                padding: 20px 15px;
            }}

            .if-title-main {{
                font-size: 24px;
            }}

            .if-title-sub {{
                font-size: 12px;
            }}

            .if-step-grid {{
                grid-template-columns: 1fr;
                gap: 10px;
            }}

            .if-step-card {{
                min-height: 82px;
            }}

            .if-upload-concepts {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }}

            .if-eye {{
                right: 186px;
            }}

            .if-brain {{
                right: 88px;
            }}

            .if-node-card {{
                right: 46px;
            }}

            .if-viz-bars {{
                right: 12px;
            }}
        }}
        </style>
        """
    )


def app_header(project_name: str | None = None, storage_label: str = "Permanent local storage") -> None:
    safe_project = html.escape(project_name or "Local privacy-first MVP")
    safe_storage = html.escape(storage_label)
    st.html(
        f"""
        <div class="if-hero-wrap">
            <div class="if-shell-title">
                <div class="if-title-kicker">Business data intelligence for modern teams</div>
                <div class="if-title-main">InsightForge AI Workspace</div>
                <div class="if-title-sub">Your AI-powered data companion.</div>
            </div>
            <div class="if-status-strip" aria-label="Workspace status">
                <div class="if-status-chip" title="{safe_project}">
                    <span class="if-material-icon" aria-hidden="true">verified_user</span>
                    <span>{safe_project}</span>
                </div>
                <div class="if-status-chip" title="{safe_storage}">
                    <span class="if-material-icon" aria-hidden="true">folder</span>
                    <span>{safe_storage}</span>
                </div>
                <div class="if-status-chip">
                    <span class="if-material-icon" aria-hidden="true">lock</span>
                    <span>Private by default</span>
                </div>
            </div>
        </div>
        """
    )


def step_indicator(active_step: int) -> None:
    cards = []
    for index, (icon, label, description) in enumerate(STEP_META):
        active = index == active_step
        classes = "if-step-card if-step-card-active" if active else "if-step-card"
        current = "step" if active else "false"
        cards.append(
            f"""
            <div class="{classes}" aria-current="{current}">
                <div class="if-step-icon">
                    <span class="if-material-icon" aria-hidden="true">{html.escape(icon)}</span>
                </div>
                <div class="if-step-body">
                    <div class="if-step-index">Step {index + 1}</div>
                    <div class="if-step-title">{html.escape(label)}</div>
                    <div class="if-step-desc">{html.escape(description)}</div>
                </div>
            </div>
            """
        )
    st.html(f"<div class='if-step-grid'>{''.join(cards)}</div>")


def upload_showcase() -> None:
    st.html(
        """
        <div class="if-upload-showcase">
            <div class="if-upload-copy">
                <div class="if-upload-title">Upload Data</div>
                <div class="if-upload-kicker">Collaborate with AI and unlock new insights</div>
                <div class="if-upload-text">
                    Keep datasets saved locally, then move through profiling, cleaning,
                    analysis, dashboards, and export without losing your workspace.
                </div>
                <div class="if-upload-concepts" aria-label="Design pillars">
                    <div class="if-concept-card">
                        <div class="if-concept-name">Text-driven workspace</div>
                        <div class="if-mini-bars"><span></span><span></span><span></span></div>
                    </div>
                    <div class="if-concept-card">
                        <div class="if-concept-name">Minimal iconography</div>
                        <div class="if-mini-bars"><span></span><span></span><span></span></div>
                    </div>
                    <div class="if-concept-card">
                        <div class="if-concept-name">Process timeline</div>
                        <div class="if-mini-bars"><span></span><span></span><span></span></div>
                    </div>
                    <div class="if-concept-card">
                        <div class="if-concept-name">Immersive visuals</div>
                        <div class="if-mini-bars"><span></span><span></span><span></span></div>
                    </div>
                </div>
            </div>
            <div class="if-upload-visual" aria-hidden="true">
                <div class="if-eye"></div>
                <div class="if-brain"></div>
                <div class="if-node-card"><span></span><span></span><span></span></div>
                <div class="if-viz-bars"><span></span><span></span><span></span><span></span></div>
                <div class="if-visual-lines"><span></span><span></span><span></span></div>
            </div>
        </div>
        """
    )


def metric_card(label: str, value: str | int | float, note: str | None = None) -> None:
    safe_label = html.escape(str(label))
    safe_value = html.escape(str(value))
    safe_note = html.escape(str(note or ""))
    st.html(
        f"""
        <div class="if-metric">
            <div class="if-metric-label">{safe_label}</div>
            <div class="if-metric-value">{safe_value}</div>
            <div class="if-metric-note">{safe_note}</div>
        </div>
        """
    )


def panel_start(kind: str = "panel") -> None:
    css = "if-soft-panel" if kind == "soft" else "if-panel"
    st.html(f"<div class='{css}'>")


def panel_end() -> None:
    st.html("</div>")
