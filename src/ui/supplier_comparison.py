"""Current V4 comparison is separate from preserved legacy ranking."""

import json

import streamlit as st

from src.supply.comparison import comparison_document, comparison_rows


def render_supplier_comparison(results, repo, prefix):
    with st.expander("V4 comparison and evidence export", expanded=prefix == "saved"):
        st.caption(
            "Current V4 eligibility and explicit assumptions, calculated locally. "
            "Blank cells are unknown. Legacy AI ranking below retains its original meaning. "
            "Export includes timestamps, exact identities, saved choices, manual provenance, "
            "missing inputs and score gates; it makes no provider requests."
        )
        document = comparison_document(results, repo)
        st.dataframe(comparison_rows(document), hide_index=True, width="stretch")
        st.download_button(
            "Export V4 comparison and evidence (JSON)",
            data=json.dumps(document, indent=2, ensure_ascii=False),
            file_name="v4-product-comparison.json",
            mime="application/json",
            key=f"v4_export_{prefix}",
            on_click="ignore",
        )
