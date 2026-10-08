"""Explicit product-scoped preferences; saves and rechecks are entirely local."""

import streamlit as st
from pydantic import ValidationError

from src.database.supply_repository import SupplyRepository
from src.supply.models import SupplierRequirements
from src.supply.service import SupplierIntelligenceService

WORKFLOW_REVISION = "structured-supplier-workflow-v2"


def render_supplier_requirements(product, repo, destination, prefix):
    extension = SupplyRepository(repo)
    saved = extension.get_requirements(product.id)
    key = f"supplier_color_{prefix}_{product.id}"
    owner = key + "_saved"
    if st.session_state.get(owner) != saved.color:
        st.session_state[key] = saved.color or ""
        st.session_state[owner] = saved.color
    st.markdown("**Supplier target requirements**")
    st.caption(
        f"Saved target color: {saved.color or 'unspecified'} · "
        f"Product {product.name} · {product.id}"
    )
    st.caption(
        "Blank means you have not declared a color preference; it does not mean supplier color "
        "evidence is absent. Under the matching contract, a comparable color must be declared "
        "before selecting a colored variant. Choose your intended color; "
        "no offer is approved automatically."
    )
    with st.form(f"supplier_requirements_{prefix}_{product.id}"):
        color = st.text_input(
            "Required supplier color",
            key=key,
            max_chars=40,
            placeholder="Enter your intended color, or leave unspecified",
        )
        save = st.form_submit_button(
            "Save supplier requirements and recheck"
            if prefix == "offers"
            else "Save structured target requirements"
        )
    if save:
        try:
            requirements = SupplierRequirements(color=color)
        except ValidationError:
            st.error("Enter a plain color name without control characters or parsing syntax.")
        else:
            extension.save_requirements(product.id, requirements)
            SupplierIntelligenceService(extension).recheck_saved(product, destination)
            st.session_state["supplier_focus_product"] = product.id
            st.session_state["flash"] = (
                "Supplier requirements saved for this product and matches rechecked locally. "
                "Observations, selection, costs and demand retain their original times."
            )
            st.rerun()
