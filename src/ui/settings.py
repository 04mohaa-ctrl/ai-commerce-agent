"""Safe configuration display; credentials never enter the UI."""

import streamlit as st

from src.config import Settings


def _remember_demo_mode() -> None:
    st.session_state["use_demo"] = st.session_state["demo_mode"]


def render_settings(settings: Settings) -> None:
    st.subheader("Settings")
    st.session_state["demo_mode"] = st.session_state["use_demo"]
    st.toggle(
        "Use deterministic demo analysis",
        key="demo_mode",
        disabled=not bool(settings.api_key),
        on_change=_remember_demo_mode,
        help="With a key configured, turn this off to use OpenAI on the next research submission.",
    )
    if settings.api_key:
        st.success("OpenAI API key configured. The key is never shown here.")
    else:
        st.info("OpenAI API key not configured. The app remains fully usable in demo mode.")
    st.write(f"Model: **{settings.model}**")
    st.write(f"Web research model: **{settings.research_model}**")
    st.caption(
        "Live mode sends each selected product to OpenAI when you submit research. "
        "It uses your API account and may incur charges. Navigation and saving do not call the API."
    )
    st.markdown("**Enable OpenAI analysis**")
    st.code(
        "# Copy .env.example to .env and edit locally\n"
        "OPENAI_API_KEY=your-key\nOPENAI_MODEL=gpt-4o-mini\nOPENAI_RESEARCH_MODEL=gpt-4.1-mini",
        language="bash",
    )
    st.caption(
        "After editing .env, reload the app and turn demo mode off here. "
        "Keep .env private; it is excluded from Git."
    )
    st.markdown("**Local storage**")
    st.code(str(settings.database_path), language=None)
    st.caption(
        "Saved analyses and manual candidates live in this SQLite file. "
        "Back up the file with the app stopped. Keep the same DATABASE_PATH after restarting."
    )
    st.markdown("**Scoring weights**")
    st.write(
        "Demand 25% · Product gross margin 25% · Trend 20% · "
        "Inverted competition 15% · Marketing 15%"
    )
