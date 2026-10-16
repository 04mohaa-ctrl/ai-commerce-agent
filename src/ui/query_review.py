"""User-reviewed Swedish and English queries, each with its own evidence."""

import streamlit as st

from src.discovery.queries import (
    QueryPlan,
    QueryTerm,
    get_query_plan,
    run_queries,
    save_query_plan,
    suggestions,
)
from src.supply.demand import DemandIntelligenceService


def render_query_review(product, repo, destination):
    st.markdown("**Review demand queries**")
    st.caption(
        f"Original product: {product.name} · Market: {destination.country}. "
        "Suggestions may be translations or broader terms; review relevance explicitly. "
        "They never replace the original product. One closed year ending yesterday per new request."
    )
    plan = get_query_plan(repo, product, destination.country)
    options = suggestions(product)
    if options:
        st.write(
            "Suggestions (unverified relevance): "
            + "; ".join(f"{t.language}: {t.query}" for t in options)
        )
    with st.form(f"v5_queries_{product.id}_{destination.country}"):
        include = st.checkbox(
            "Include original product name as an exact query",
            value=not plan or any(t.query == product.name for t in plan.terms),
        )
        default = (
            "\n".join(f"{t.language}: {t.query}" for t in plan.terms if t.query != product.name)
            if plan
            else ""
        )
        text = st.text_area(
            "Chosen additional queries (one sv: or en: term per line)",
            value=default,
            key=f"v5_extra_queries_{product.id}_{destination.country}",
            max_chars=650,
        )
        save = st.form_submit_button("Save reviewed query plan")
    if save:
        try:
            terms = [QueryTerm(query=product.name, language="other")] if include else []
            for line in text.splitlines():
                if not line.strip():
                    continue
                language, separator, query = line.partition(":")
                if not separator or language.strip() not in {"sv", "en"}:
                    raise ValueError("Use sv: or en: at the start of each line.")
                terms.append(QueryTerm(query=query, language=language.strip()))
            plan = QueryPlan(country=destination.country, terms=terms)
            save_query_plan(repo, product, plan)
            st.success("Explicitly reviewed query plan saved locally. No requests made.")
        except ValueError:
            st.error(
                (
                    "Choose 1–5 distinct queries, at most 120 characters each. Prefix additional "
                    "terms with sv: or en:."
                )
            )
    if not plan:
        st.info("Demand batch blocked: save a reviewed query plan first.")
        return
    st.write("Chosen scope: " + "; ".join(f"{t.language}: {t.query}" for t in plan.terms))
    st.caption(
        f"One candidate, {len(plan.terms)} exact query series, market {plan.country}. "
        f"At most {len(plan.terms)} DataForSEO requests, 120-second action budget; "
        "compatible caches reused. Monetary cost follows your provider account and is not "
        "known here. CJ quota points do not apply. "
        "No automatic retry of uncertain paid submissions."
    )
    demo = st.session_state.get("use_demo", True)
    if st.button(
        "Research reviewed demand queries", disabled=demo, key=f"v5_run_queries_{product.id}"
    ):
        st.session_state[f"v5_query_outcomes_{product.id}"] = run_queries(
            repo, product, destination, plan
        )
    if demo:
        st.caption(
            "Blocked by Demo Mode; disable it only when configured and ready for provider charges."
        )
    st.info(
        (
            "Each relative-interest series has its own normalization. Index values cannot"
            " be added or directly compared across terms or products. Extra terms are "
            "exploratory; V4 scores retain the original query."
        )
    )
    service = DemandIntelligenceService(repo)
    for term in plan.terms:
        snapshot = service.get_current(product, destination, query=term.query)
        if not snapshot:
            st.caption(
                f"{term.query}: not requested. Next action: explicitly research reviewed queries."
            )
            continue
        usable = sum(not o.missing and o.value is not None for o in snapshot.demand.observations)
        st.write(
            f"{term.query} · {snapshot.outcome.status} · "
            f"{usable}/{len(snapshot.demand.observations)} usable observations · "
            f"trend {snapshot.trend.classification} · current {snapshot.current_eligible}"
        )
        st.caption(
            f"{snapshot.provider} · {snapshot.location} · "
            f"{snapshot.period_start}–{snapshot.period_end} · "
            f"observed {snapshot.outcome.observed_at.isoformat()}"
        )
        with st.expander(f"Query evidence and request details · {term.query}"):
            st.json(snapshot.model_dump(mode="json"))
    for outcome in st.session_state.get(f"v5_query_outcomes_{product.id}", []):
        st.caption(f"{outcome['query']}: {outcome['status']} · {outcome['notice']}")
