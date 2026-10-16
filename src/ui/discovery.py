"""Explicit supplier discovery and everyday candidate workspace."""

import streamlit as st
from pydantic import ValidationError

from src.config import offline_mode
from src.discovery.models import CatalogItem, DiscoveryResult, DiscoverySearch
from src.discovery.repository import DiscoveryRepository
from src.discovery.service import DiscoveryService, save_candidate
from src.supply.models import (
    ActionTelemetry,
    Destination,
    ProviderOutcome,
    SupplierProductCandidate,
)
from src.ui.supplier_intelligence import COUNTRIES


def render_discovery(repo):
    st.subheader("Discover supplier products")
    st.write(
        ("Discover → Save candidates → Specify variants → Research → Compare → Decide next action")
    )
    st.caption(
        (
            "Catalog presence does not prove stock, quality or demand. Catalog prices are"
            " observed listing metadata; select and adopt variant costs explicitly later."
        )
    )
    with st.form("v5_discovery"):
        query = st.text_input("CJ keyword or SKU", max_chars=200, key="v5_discovery_query")
        cols = st.columns(3)
        country = cols[0].selectbox(
            "Supplier inventory country filter", ["Any", "CN", "US", "GB", "DE", "FR", "SE"]
        )
        minimum = cols[1].number_input("Minimum catalog price (USD)", value=None, min_value=0.0)
        maximum = cols[2].number_input("Maximum catalog price (USD)", value=None, min_value=0.0)
        category = st.text_input("CJ category ID (optional, exact third-level ID)", max_chars=200)
        st.caption(
            (
                "One explicit page request: at most 10 products, 4 local HTTP attempts "
                "including auth/retry, 30-second action budget. CJ quota points are provider "
                "limits, not a dollar price. No account-specific money or points charge is "
                "known here. No automatic next page."
            )
        )
        refresh = st.checkbox("Refresh this catalog page instead of reusing a compatible cache")
        submitted = st.form_submit_button(
            "Search CJ catalog", type="primary", disabled=st.session_state.get("use_demo", True)
        )
    if st.session_state.get("use_demo", True):
        st.info(
            (
                "Live discovery is blocked by Demo Mode. Configure CJ privately and disable "
                "Demo Mode in Settings when ready. Offline acceptance examples are synthetic."
            )
        )
    if submitted:
        try:
            search = DiscoverySearch(
                query=query,
                country=None if country == "Any" else country,
                min_price=minimum,
                max_price=maximum,
                category_id=category or None,
            )
            st.session_state["v5_discovery_result"] = DiscoveryService(repo).search(
                search, force=refresh
            )
        except ValueError:
            st.error("Enter a keyword and a valid price range. Minimum cannot exceed maximum.")
    if (
        offline_mode()
        and not st.session_state.get("v5_capture_only", False)
        and st.button("Load synthetic discovery examples (offline)")
    ):
        items = [
            CatalogItem(
                candidate=SupplierProductCandidate(
                    provider="cj", product_id=f"SYNTHETIC-{index}", name=name
                ),
                catalog_price=price,
                currency="USD",
                evidence_kind="SYNTHETIC",
            )
            for index, (name, price) in enumerate(
                [("Laptop stand", "4.00-8.00"), ("Pet brush", "3.25"), ("Lunch box", "9.50")], 1
            )
        ]
        from src.research.models import utc_now

        st.session_state["v5_discovery_result"] = DiscoveryResult(
            search=DiscoverySearch(query="Synthetic acceptance examples"),
            outcome=ProviderOutcome(
                status="SUCCESS", records=[i.model_dump(mode="json") for i in items]
            ),
            telemetry=ActionTelemetry(action="synthetic_examples"),
            searched_at=utc_now(),
        )
    result = st.session_state.get("v5_discovery_result")
    if not result:
        st.info("Search explicitly to request page 1. No requests run while typing or navigating.")
        return
    st.write(
        f"Results for “{result.search.query}” · page {result.search.page}/2 · "
        f"{result.outcome.status}" + (" · compatible cache" if result.cached else "")
    )
    if result.outcome.partial:
        st.warning(
            f"Partial response: {result.outcome.rejected} invalid records rejected. "
            "Valid products remain available."
        )
    if result.outcome.notice:
        st.info(result.outcome.notice)
    if not result.outcome.records:
        st.info(
            (
                "No products available in this response. Empty, unavailable and failed "
                "searches do not establish demand or stock."
            )
        )
    cols = st.columns(3)
    market = cols[0].selectbox(
        "Market for saved candidates", list(COUNTRIES), index=2, format_func=COUNTRIES.get
    )
    quantity = cols[1].number_input(
        "Candidate units per order", min_value=1, max_value=1000, value=1
    )
    delivery = cols[2].number_input(
        "Candidate maximum delivery days", min_value=1, max_value=365, value=14
    )
    saved_origins = {
        r.product.supplier_identity.product_id
        for r in repo.list_saved()
        if r.product.supplier_identity and r.product.supplier_identity.provider == "cj"
    }
    for payload in result.outcome.records:
        try:
            item = CatalogItem.model_validate(payload)
        except ValidationError:
            st.warning("A catalog record was invalid and has been omitted.")
            continue
        candidate = item.candidate
        with st.container(border=True):
            columns = st.columns([1, 4])
            if candidate.image_url and not offline_mode():
                columns[0].image(candidate.image_url, width=150)
            with columns[1]:
                st.markdown(f"**{candidate.name}**")
                st.write(f"CJ product ID: {candidate.product_id}")
                st.caption(
                    f"Catalog sell price: {item.currency or ''} "
                    f"{item.catalog_price or 'Unknown'} · "
                    f"observed {candidate.observed_at.isoformat()} · {item.evidence_kind}"
                )
                if candidate.source_url:
                    st.link_button("Open supplied listing link", candidate.source_url)
                else:
                    st.caption("Listing link not supplied by this catalog response.")
                already = candidate.product_id in saved_origins
                if st.button(
                    "Save candidate", key=f"v5_save_{candidate.product_id}", disabled=already
                ):
                    save_candidate(
                        repo,
                        item,
                        Destination(country=market, quantity=quantity, max_delivery_days=delivery),
                    )
                    st.session_state["flash"] = (
                        "Candidate saved. Open Candidates to specify variants and research."
                    )
                    st.rerun()
                if already:
                    st.caption("Already saved; duplicate prevented.")
    if result.search.page < 2 and result.outcome.records and not offline_mode():
        if st.button(
            "Request next page (same submitted filters)",
            disabled=st.session_state.get("use_demo", True),
        ):
            st.session_state["v5_discovery_result"] = DiscoveryService(repo).search(
                result.search.model_copy(update={"page": 2})
            )
            st.rerun()
    with st.expander("Discovery request details"):
        st.json(result.model_dump(mode="json"))


def render_candidates(repo):
    from src.ui.products import render_details
    from src.ui.query_review import render_query_review
    from src.ui.supplier_intelligence import research_destination

    st.subheader("Saved candidates · specify and research")
    st.caption(
        (
            "Select a candidate, specify target requirements, select an observed variant "
            "and warehouse, request freight, and explicitly adopt costs in V4 economics. "
            "Then open Compare to decide a next action."
        )
    )
    rows = repo.list_saved()
    if not rows:
        st.info("Save candidates in Discover first. Existing Saved Products also appear here.")
        return
    lookup = {r.product.id: r for r in rows}
    selected = st.selectbox(
        "Candidate to investigate",
        list(lookup),
        format_func=lambda key: lookup[key].product.name,
        key="v5_candidate",
    )
    result = lookup[selected]
    origin = DiscoveryRepository(repo).get_origin(selected)
    if origin:
        st.caption(
            f"Saved supplier identity {origin.candidate.product_id} · "
            f"evidence: {origin.evidence_kind}. "
            "No catalog price has been adopted automatically."
        )
        if origin.evidence_kind == "SYNTHETIC":
            st.warning(
                (
                    "SYNTHETIC acceptance candidate. This is not a real supplier listing or "
                    "market observation."
                )
            )
    render_query_review(result.product, repo, research_destination(result.product, repo))
    render_details(result, repo, "v5_candidate")
