"""Groups of 3–5 saved candidates with V4 evidence and explicit next actions."""

import json

import streamlit as st

from src.discovery.comparison import (
    ComparisonGroup,
    comparison_workspace,
    save_group,
    workspace_rows,
)
from src.discovery.repository import DiscoveryRepository


def render_comparison_workspace(repo):
    st.subheader("Compare candidates and decide a next action")
    st.caption(
        (
            "Local comparison makes no provider requests. Choose 3–5 distinct saved "
            "candidates. Blank values remain unknown; scores prioritize investigation and"
            " cannot guarantee a winner."
        )
    )
    lookup = {r.product.id: r for r in repo.list_saved()}
    groups = DiscoveryRepository(repo).list_groups()
    group = None
    selected = "__new__"
    if groups:
        selected = st.selectbox(
            "Saved comparison group",
            [g["name"] for g in groups] + ["__new__"],
            format_func=lambda value: "Create a new group" if value == "__new__" else value,
            key="v5_saved_group",
        )
        if selected != "__new__":
            group = ComparisonGroup.model_validate(next(g for g in groups if g["name"] == selected))
    editor_keys = ("v5_group_name", "v5_group_members", "v5_group_decision", "v5_group_notes")
    if st.session_state.get("v5_group_editor_owner") != selected or any(
        key not in st.session_state for key in editor_keys
    ):
        st.session_state["v5_group_editor_owner"] = selected
        st.session_state["v5_group_name"] = group.name if group else ""
        st.session_state["v5_group_members"] = (
            [pid for pid in group.product_ids if pid in lookup] if group else []
        )
        st.session_state["v5_group_decision"] = group.decision if group else "Undecided"
        st.session_state["v5_group_notes"] = group.notes if group else ""
    if len(lookup) < 3:
        st.info("Comparison needs at least three saved candidates. Save more in Discover.")
    with st.form("v5_group_form"):
        name = st.text_input(
            "Comparison group name",
            max_chars=100,
            key="v5_group_name",
        )
        ids = st.multiselect(
            "Candidates (3–5)",
            list(lookup),
            format_func=lambda key: lookup[key].product.name,
            key="v5_group_members",
            max_selections=5,
        )
        decisions = list(ComparisonGroup.model_fields["decision"].annotation.__args__)
        decision = st.selectbox(
            "Next-action decision (your judgement)",
            decisions,
            key="v5_group_decision",
        )
        notes = st.text_area(
            "Decision reasons and remaining questions",
            key="v5_group_notes",
            max_chars=2000,
        )
        save = st.form_submit_button("Save comparison group")
    if save:
        try:
            group = ComparisonGroup(name=name, product_ids=ids, decision=decision, notes=notes)
            save_group(repo, group)
            st.success("Comparison group and decision saved locally.")
        except ValueError:
            st.error("Enter a group name and choose 3–5 distinct saved candidates.")
    if not group:
        return
    missing = [pid for pid in group.product_ids if pid not in lookup]
    if missing:
        st.warning(
            f"{len(missing)} group candidate(s) are no longer saved. "
            "Restore them or edit the group before relying on this comparison."
        )
    rows = [lookup[pid] for pid in group.product_ids if pid in lookup]
    document = comparison_workspace(rows, repo, group=group)
    if missing:
        document["comparability"]["directly_comparable"] = False
        document["comparability"]["issues"].append("Group members missing: " + ", ".join(missing))
    if document["comparability"]["directly_comparable"]:
        st.success(
            "Economic scenarios use consistent assumptions. Review evidence quality separately."
        )
    else:
        st.warning("Not directly comparable: " + " ".join(document["comparability"]["issues"]))
    st.dataframe(workspace_rows(document), hide_index=True, width="stretch")
    for item in document["products"]:
        with st.container(border=True):
            st.markdown(f"**{item['product']['name']} · next actions**")
            from src.ui.market_economics import LABELS
            from src.ui.supplier_financial import FIELD_LABELS

            for action in item["next_actions"]:
                for field, label in (LABELS | FIELD_LABELS).items():
                    action = action.replace(field, label)
                st.write("• " + action)
            snapshot = item["financial"]["snapshot"]
            st.caption(
                f"Market {item['destination']['country']} · "
                f"quantity {item['destination']['quantity']} · currency {snapshot['currency']} · "
                f"VAT basis {snapshot['tax_assumptions']['price_basis']} · "
                f"saved finance {item['financial']['saved']}"
            )
            score = item["opportunity_score"]
            st.caption(
                f"V4 opportunity confidence {score['confidence']} · "
                f"coverage {score['coverage']}%. "
                "See evidence details for assumptions and gates."
            )
            with st.expander(f"Assumptions and evidence · {item['product']['name']}"):
                st.json(item)
    st.write(document["prioritization"]["basis"])
    st.caption(document["semantics"]["query_series"])
    st.download_button(
        "Export V5 comparison and evidence (JSON)",
        data=json.dumps(document, indent=2, ensure_ascii=False),
        file_name="v5-product-comparison.json",
        mime="application/json",
        on_click="ignore",
    )
