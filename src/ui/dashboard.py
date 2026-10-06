"""Application shell, navigation and metrics."""

import json
from statistics import mean

import streamlit as st
from pydantic import ValidationError

from src.agents.product_research_agent import ProductResearchAgent
from src.config import load_settings
from src.database.database import DataStoreError, ProductRepository
from src.research.scoring import hydrate_results
from src.services.product_service import ResearchService
from src.ui.products import render_products
from src.ui.research import render_research
from src.ui.settings import render_settings


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
    if "use_demo" not in st.session_state or not settings.api_key:
        st.session_state["use_demo"] = True
    with st.sidebar:
        st.title("◈ AI Commerce")
        st.caption("PRODUCT RESEARCH WORKSPACE")
        page = st.radio(
            "Navigation",
            ["Dashboard", "Research", "Saved Products", "Settings"],
            key="nav",
            label_visibility="collapsed",
        )
        st.divider()
        st.caption("ONE ANALYST · V3")
        st.write("Demo mode" if st.session_state["use_demo"] else "OpenAI mode")
        st.caption("Local candidates. Clear assumptions.\nBuild a shortlist worth researching.")
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
        columns = st.columns(4)
        columns[0].metric("Products analyzed", str(len(results)))
        columns[1].metric("Saved products", str(len(saved)))
        columns[2].metric(
            "Average AI score", f"{mean(r.score.total for r in results):.1f}" if results else "—"
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
        if page == "Settings":
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
