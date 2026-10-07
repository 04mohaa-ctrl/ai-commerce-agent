"""Research query and durable manual candidate input."""

import streamlit as st
from pydantic import ValidationError

from src.agents.product_research_agent import ProductResearchAgent
from src.config import Settings
from src.database.database import ProductRepository
from src.schemas.product import Product, ScoreHints
from src.services.product_service import ResearchService
from src.ui.research_details import run_product_research
from src.ui.supplier_intelligence import render_target_inputs


def render_research(repo: ProductRepository, settings: Settings) -> None:
    st.subheader("Start your research")
    st.caption(
        "Enter a specific product to open and research it, or a category to browse candidates. "
        "Specific product: Electric heated lunch box · Category: Kitchen gadgets."
    )
    with st.form("research_form"):
        query = st.text_input(
            "What product or category do you want to research?",
            placeholder="Electric heated lunch box or Kitchen gadgets",
            key="research_query",
            max_chars=200,
        )
        render_target_inputs()
        submit = st.form_submit_button("Find / Analyze Products", type="primary")
    agent = ProductResearchAgent(
        api_key=settings.api_key, model=settings.model, force_demo=st.session_state["use_demo"]
    )
    service = ResearchService(repo, agent)

    def open_product(product: Product) -> None:
        # Candidate initialization is offline. Both entry points then use the
        # same evidence action, with no second estimate-only model request.
        st.session_state["results"] = [ProductResearchAgent(force_demo=True).analyze(product)]
        st.session_state["last_query"] = product.name
        st.session_state["details_research"] = product.id
        st.session_state["research_focus_product"] = product.id
        for key, value in {
            "minscore_research": 0,
            "usemargin_research": False,
            "recs_research": [],
            "categories_research": [],
        }.items():
            st.session_state[key] = value
        run_product_research(product, repo, settings)
        st.rerun()

    if submit:
        st.session_state["submitted_research_query"] = query.strip()
        st.session_state.pop("research_focus_product", None)
        exact = service.exact_products(query)
        if len(exact) == 1:
            open_product(exact[0])
        if len(exact) > 1:
            st.session_state["results"] = [
                ProductResearchAgent(force_demo=True).analyze(p) for p in exact
            ]
            st.session_state["last_query"] = query.strip()
            st.session_state["flash"] = (
                "Several products share this name. Select a candidate and use Research product."
            )
            st.rerun()
        candidates = service.candidates(query)
        with st.spinner(f"Analyzing {min(len(candidates), 20)} local candidates…"):
            st.session_state["results"] = service.research(query)
            st.session_state["last_query"] = query.strip() or "All local candidates"
        if len(candidates) > 20:
            st.session_state["flash"] = (
                f"Analyzed the first 20 of {len(candidates)} matches. Narrow your search for more."
            )
        st.rerun()
    submitted = st.session_state.get("submitted_research_query", "")
    if (
        submitted
        and not service.exact_products(submitted)
        and not service.is_category_query(submitted)
    ):
        with st.container(border=True):
            st.write(f"No exact candidate named “{submitted}”.")
            st.caption(
                "Research this name as a custom product. Costs and selling price stay unknown "
                "until you enter them in Economics. Demo Mode applies when enabled."
            )
            if st.button(
                "Research this product",
                type="primary",
                key="research_custom_product",
                disabled=len(Product.normalize_text(submitted)) > 120,
            ):
                open_product(service.get_or_create_custom(submitted))
            if len(Product.normalize_text(submitted)) > 120:
                st.info(
                    "Use a product name of at most 120 characters to create a custom candidate."
                )
    elif submitted and service.is_category_query(submitted):
        st.caption(
            "Category results are local or connected-source candidates. "
            "Select a product and use Research product for web evidence."
        )
    with st.expander("Add a product manually"):
        st.caption(
            "Treat all inputs as estimates. Adding the same name and category "
            "updates the local candidate."
        )
        with st.form("manual_form"):
            left, right = st.columns(2)
            name = left.text_input("Product name", key="manual_name", max_chars=120)
            category = right.selectbox(
                "Category",
                [
                    "Kitchen gadgets",
                    "Pet products",
                    "Car accessories",
                    "Travel",
                    "Office",
                    "Home fitness",
                    "Other",
                ],
                key="manual_category",
            )
            cost = left.number_input(
                "Estimated product cost (USD)",
                min_value=0.0,
                max_value=1_000_000.0,
                value=5.0,
                step=0.5,
                key="manual_cost",
            )
            price = right.number_input(
                "Estimated selling price (USD)",
                min_value=0.01,
                max_value=1_000_000.0,
                value=19.99,
                step=0.5,
                key="manual_price",
            )
            description = st.text_area(
                "Product description / problem it solves", key="manual_description", max_chars=2000
            )
            hint_cols = st.columns(4)
            hints = {
                field: column.slider(label, 0.0, 10.0, 5.0, 0.1, key=f"manual_{field}")
                for field, label, column in zip(
                    ["demand", "competition", "trend", "marketing"],
                    [
                        "Demand assumption",
                        "Competition assumption",
                        "Trend assumption",
                        "Marketing assumption",
                    ],
                    hint_cols,
                    strict=True,
                )
            }
            add = st.form_submit_button("Add and analyze product")
        if add:
            try:
                product = Product(
                    name=name,
                    category=category,
                    cost=cost,
                    selling_price=price,
                    description=description,
                    source="manual",
                    hints=ScoreHints(**hints),
                )
            except ValidationError:
                st.error(
                    "Enter a product name and valid finite prices: cost ≥ 0 and selling price > 0."
                )
            else:
                repo.add_candidate(product)
                with st.spinner("Analyzing your candidate…"):
                    st.session_state["results"] = [agent.analyze(product)]
                st.session_state["last_query"] = product.name
                st.session_state["flash"] = "Manual candidate stored locally and analyzed."
                st.rerun()
