"""Application shell, navigation and metrics."""

import json
import os
import sys
from statistics import mean

import streamlit as st
from pydantic import ValidationError

from src.agents.product_research_agent import ProductResearchAgent
from src.config import PROJECT_ROOT, load_settings, offline_mode
from src.database.database import DataStoreError, ProductRepository
from src.research.scoring import hydrate_results
from src.services.product_service import ResearchService
from src.ui.products import render_products
from src.ui.research import render_research
from src.ui.settings import render_settings
from src.ui.supplier_intelligence import optional_provider_configured
from src.ui.supplier_requirements import WORKFLOW_REVISION


def main() -> None:
    st.set_page_config(page_title="AI Commerce Agent", page_icon="◈", layout="wide")
    st.markdown(
        """<style>
        .block-container {max-width: 1450px; padding-top: 2rem;}
        [data-testid="stMetric"] {background: white; border: 1px solid #dde5ee;
            border-radius: 12px; padding: 16px;}
        [data-testid="stSidebar"] {border-right: 1px solid #dde5ee;}
        h1 {letter-spacing: -0.035em;}
        </style>""",
        unsafe_allow_html=True,
    )
    settings = load_settings()
    # This setting outlives the Settings-only toggle's widget lifecycle.
    if (
        offline_mode()
        or "use_demo" not in st.session_state
        or not (settings.api_key or optional_provider_configured())
    ):
        st.session_state["use_demo"] = True
    with st.sidebar:
        st.title("◈ AI Commerce")
        st.caption("PRODUCT RESEARCH WORKSPACE")
        page = st.radio(
            "Navigation",
            [
                "Dashboard",
                "Discover",
                "Candidates",
                "Compare",
                "Research",
                "Saved Products",
                "Settings",
            ],
            key="nav",
            label_visibility="collapsed",
        )
        st.divider()
        st.caption("ONE OPERATOR · V5")
        st.caption("Local workspace · shared-user access is not supported")
        if offline_mode():
            st.info("OFFLINE ACCEPTANCE · providers disabled")
        st.write(
            "Demo mode"
            if st.session_state["use_demo"]
            else "OpenAI mode"
            if settings.api_key
            else "Research mode"
        )
        st.caption("Local candidates. Clear assumptions.\nBuild a shortlist worth researching.")
        with st.expander("App runtime"):
            st.write(f"Process {os.getpid()} · {WORKFLOW_REVISION}")
            st.write(f"Checkout: {PROJECT_ROOT}")
            st.write(f"Database: {settings.database_path}")
            st.write(f"Python: {sys.executable}")
    st.title("AI Commerce Agent")
    st.caption("Find promising product ideas and understand the assumptions behind every score.")
    try:
        repo = ProductRepository(settings.database_path)
        if "results" not in st.session_state:
            initial = ResearchService(repo, ProductResearchAgent(force_demo=True))
            st.session_state["results"] = initial.research("")
            st.session_state["last_query"] = "Demo catalogue"
        saved = repo.list_saved()
        results = hydrate_results(st.session_state["results"], repo)
        if page in {"Discover", "Candidates", "Compare"}:
            st.caption(
                f"V5 workflow · {len(saved)} saved candidates · local single-operator workspace"
            )
        else:
            columns = st.columns(4)
            columns[0].metric("Products analyzed", str(len(results)))
            columns[1].metric("Saved products", str(len(saved)))
            columns[2].metric(
                "Average AI score",
                f"{mean(r.score.total for r in results):.1f}" if results else "—",
            )
            columns[3].metric(
                "Highest score", f"{max(r.score.total for r in results):.1f}" if results else "—"
            )
            st.caption(
                "Analysis metrics reflect the latest research in this session. "
                "Saved products persist locally."
            )
        if message := st.session_state.pop("flash", None):
            st.success(message)
        if page == "Discover":
            from src.ui.discovery import render_discovery

            render_discovery(repo)
        elif page == "Candidates":
            from src.ui.discovery import render_candidates

            render_candidates(repo)
        elif page == "Compare":
            from src.ui.comparison_workspace import render_comparison_workspace

            render_comparison_workspace(repo)
        elif page == "Settings":
            render_settings(settings)
        elif page == "Research":
            render_research(repo, settings)
            render_products(
                st.session_state["results"], repo, prefix="research", title="Research results"
            )
        elif page == "Saved Products":
            st.subheader("Your shortlist")
            st.caption(
                "Saved analysis snapshots keep their inputs, reasoning and scores after a restart."
            )
            if not saved:
                st.info("No saved products yet. Open a product and choose Save product.")
            else:
                render_products(saved, repo, prefix="saved", title="Saved Products")
        else:
            st.subheader("Product opportunities")
            st.caption(f"Latest research: {st.session_state.get('last_query', 'Demo catalogue')}")
            render_products(results, repo, prefix="dashboard", title="Ranked products")
    except DataStoreError as exc:
        st.error(str(exc))
        st.info("Check DATABASE_PATH in .env and restore a backup if the file is corrupt.")
    except (OSError, ValidationError, json.JSONDecodeError):
        st.error("The local product dataset could not be loaded. Check data/demo_products.json.")
