"""Reusable ranked table, product cards and full analysis details."""

import streamlit as st

from src.config import load_settings
from src.database.database import ProductRepository
from src.research.scoring import hydrate_results
from src.schemas.product import ResearchResult
from src.services.product_service import SORT_KEYS, filter_results
from src.services.scoring import WEIGHTS
from src.supply.service import SupplierIntelligenceService
from src.ui.market_economics import render_market_economics
from src.ui.market_intelligence import render_market_intelligence
from src.ui.research_details import render_economics_view, render_research_view, render_sources_view
from src.ui.supplier_comparison import render_supplier_comparison
from src.ui.supplier_intelligence import render_supplier_intelligence, research_destination
from src.ui.supplier_requirements import render_supplier_requirements


def render_target_requirements(result, repo, prefix):
    product = result.product
    render_supplier_requirements(product, repo, research_destination(product, repo), "assumptions")
    st.markdown("**Target variant requirements · your intended product**")
    st.caption(
        "Declare requirements you actually intend, for example Color: Black; Capacity: 500ml; "
        "Count: 1. Use separate lines or semicolons. Blank color remains unspecified and can "
        "block a colored variant. This edits target inputs, not supplier evidence. "
        "Existing analysis remains historical; new research is an explicit action."
    )
    with st.form(f"target_requirements_{prefix}_{product.id}"):
        description = st.text_area(
            "Target description / variant requirements",
            value=product.description,
            max_chars=2000,
            key=f"target_description_{prefix}_{product.id}",
        )
        save = st.form_submit_button("Save target requirements and recheck saved offers")
    if save:
        # Preserve the original saved analysis/estimates rather than persisting hydrated economics.
        original = next((r for r in repo.list_saved() if r.product.id == product.id), result)
        updated = original.model_copy(
            update={
                "product": original.product.model_copy(update={"description": description.strip()})
            }
        )
        repo.save(updated)
        candidate = next((p for p in repo.list_candidates() if p.id == product.id), None)
        if candidate:
            repo.add_candidate(candidate.model_copy(update={"description": description.strip()}))
        st.session_state["results"] = [
            updated if r.product.id == product.id else r
            for r in st.session_state.get("results", [])
        ]
        SupplierIntelligenceService(repo).recheck_saved(
            updated.product, research_destination(updated.product, repo)
        )
        st.session_state["flash"] = (
            "Target requirements saved and supplier matches rechecked locally. "
            "No provider requests; observation times, selection and costs are preserved."
        )
        st.rerun()


def money_text(value: float | None) -> str:
    return f"USD {value:.2f}" if value is not None else "Unknown"


def margin_text(value: float | None) -> str:
    return f"{value:.1f}%" if value is not None else "Unknown"


def render_products(
    results: list[ResearchResult], repo: ProductRepository, prefix: str, title: str
) -> None:
    results = hydrate_results(results, repo)
    st.subheader(title)
    if not results:
        st.info(
            "No products match your search. Try a broader category or use Research this product "
            "above for a new specific name."
            if prefix == "research"
            else "No products match your search. Try a broader category or add a product manually."
        )
        return
    modes = {r.mode for r in results}
    if "demo" in modes:
        st.info("DEMO ANALYSIS · Estimated inputs and mock judgements. No verified market data.")
    if "openai" in modes:
        st.info(
            "AI ANALYSIS · Scores are judgements; local prices are estimates. "
            "Market demand is unverified."
        )
    notices = sorted({r.notice for r in results if r.notice})
    for notice in notices:
        st.warning(notice)
    with st.expander("Sort and filter", expanded=True):
        top = st.columns([2, 1, 2])
        sort = top[0].selectbox("Sort by", list(SORT_KEYS), key=f"sort_{prefix}")
        descending = top[1].toggle("Descending", value=True, key=f"descending_{prefix}")
        options = sorted({r.product.category for r in results})
        category_key = f"categories_{prefix}"
        if category_key in st.session_state:
            st.session_state[category_key] = [
                c for c in st.session_state[category_key] if c in options
            ]
        categories = top[2].multiselect("Categories", options, key=category_key)
        bottom = st.columns(3)
        min_score = bottom[0].slider("Minimum AI score", 0, 100, 0, key=f"minscore_{prefix}")
        recs = bottom[1].multiselect(
            "Recommendation",
            ["Strong candidate", "Worth investigating", "Weak candidate"],
            key=f"recs_{prefix}",
        )
        with bottom[2]:
            apply_margin = st.checkbox("Filter by minimum margin", key=f"usemargin_{prefix}")
            min_margin = st.number_input(
                "Minimum margin %",
                min_value=-10000.0,
                max_value=100.0,
                value=30.0,
                step=5.0,
                disabled=not apply_margin,
                key=f"minmargin_{prefix}",
            )
    rows = filter_results(
        results,
        categories=categories,
        min_score=min_score,
        min_margin=min_margin if apply_margin else None,
        recommendations=recs,
        sort_by=sort,
        descending=descending,
    )
    st.caption(
        f"{len(rows)} of {len(results)} products · All prices in USD · "
        "Lower competition is better. Gross margin excludes freight, ads, fees, taxes and returns."
    )
    if not rows:
        st.info("No products match these filters. Lower a threshold or clear a filter.")
        return
    table = [
        {
            "Product name": r.product.name,
            "Category": r.product.category,
            "Estimated product cost": r.product.cost,
            "Estimated selling price": r.product.selling_price,
            "Gross margin %": round(r.gross_margin, 1) if r.gross_margin is not None else None,
            "Demand": r.assessment.demand,
            "Competition": r.assessment.competition,
            "Trend": r.assessment.trend,
            "Profit potential": r.score.profit_potential,
            "Marketing": r.assessment.marketing,
            "Overall AI Score": r.score.total,
            "Recommendation": r.recommendation,
            "Short AI explanation": r.assessment.explanation,
            "Risks": " | ".join(r.assessment.risks),
            "Analysis mode": "Demo" if r.mode == "demo" else "OpenAI",
            "Score basis": r.score_basis,
            "Evidence confidence": r.confidence_level,
        }
        for r in rows
    ]
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            "Estimated product cost": st.column_config.NumberColumn(format="$%.2f"),
            "Estimated selling price": st.column_config.NumberColumn(format="$%.2f"),
            "Gross margin %": st.column_config.NumberColumn(format="%.1f%%"),
            "Overall AI Score": st.column_config.ProgressColumn(
                min_value=0, max_value=100, format="%.1f"
            ),
        },
    )
    render_supplier_comparison(rows, repo, prefix)
    detail_key = f"details_{prefix}"
    ids = [r.product.id for r in rows]
    if st.session_state.get(detail_key) not in ids:
        st.session_state[detail_key] = ids[0]
    st.caption("Open a candidate below, or choose any product in the details selector.")
    for offset in range(0, min(len(rows), 6), 3):
        columns = st.columns(3)
        for column, r in zip(columns, rows[offset : offset + 3], strict=False):
            with column, st.container(border=True):
                st.markdown(f"**{r.product.name}**")
                st.caption(r.product.category)
                st.metric("AI Score", f"{r.score.total:.1f} / 100")
                st.write(r.recommendation)
                st.caption(
                    f"Margin {margin_text(r.gross_margin)} · Cost {money_text(r.product.cost)} · "
                    f"Price {money_text(r.product.selling_price)}"
                )
                if st.button("View details", key=f"open_{prefix}_{r.product.id}", width="stretch"):
                    st.session_state[detail_key] = r.product.id
    lookup = {r.product.id: r for r in rows}
    selected = st.selectbox(
        "Product details",
        ids,
        key=detail_key,
        format_func=lambda product_id: lookup[product_id].product.name,
    )
    render_details(lookup[selected], repo, prefix)


def render_details(result: ResearchResult, repo: ProductRepository, prefix: str) -> None:
    product, analysis = result.product, result.assessment
    st.subheader(f"Product details · {product.name}")
    st.caption(
        f"{product.category} · Source: {product.source} · Analyst: {result.model} · "
        f"Analyzed {result.analyzed_at:%Y-%m-%d %H:%M} UTC"
    )
    saved_ids = {r.product.id for r in repo.list_saved()}
    actions = st.columns([1, 1, 3])
    save_label = "Update saved analysis" if product.id in saved_ids else "Save product"
    if actions[0].button(
        save_label, type="primary", key=f"save_{prefix}_{product.id}", width="stretch"
    ):
        created = repo.save(result)
        st.session_state["flash"] = (
            "Product saved locally." if created else "Saved analysis updated."
        )
        st.rerun()
    if product.id in saved_ids and actions[1].button(
        "Remove saved product", key=f"remove_{prefix}_{product.id}", width="stretch"
    ):
        repo.remove_saved(product.id)
        st.session_state["flash"] = "Saved product removed."
        st.rerun()
    (
        overview_tab,
        evidence_tab,
        score_tab,
        research_tab,
        sources_tab,
        economics_tab,
        market_tab,
        supplier_tab,
    ) = st.tabs(
        [
            "Analysis",
            "Data & assumptions",
            "Score calculation",
            "Research",
            "Sources",
            "Economics",
            "Market Intelligence",
            "Supplier Intelligence",
        ],
        default="Supplier Intelligence"
        if st.session_state.get("supplier_focus_product") == product.id or prefix == "v5_candidate"
        else "Research"
        if st.session_state.get("research_focus_product") == product.id
        else "Analysis",
    )
    with overview_tab:
        st.markdown(f"**{result.recommendation} · {result.score.total:.1f}/100**")
        st.write(analysis.explanation)
        left, right = st.columns(2)
        with left:
            st.markdown("**Overview**")
            st.write(analysis.overview)
            st.markdown("**Target customer · hypothesis**")
            st.write(analysis.target_customer)
            st.markdown("**Why a customer might buy it**")
            st.write(analysis.purchase_motivation)
            st.markdown("**Potential marketing angles**")
            for angle in analysis.marketing_angles:
                st.write(f"• {angle}")
            st.markdown("**Competition**")
            st.write(analysis.competition_reasoning)
        with right:
            st.markdown("**Suggested price range · hypothesis**")
            if (
                analysis.suggested_price_min is not None
                and analysis.suggested_price_max is not None
            ):
                st.write(
                    f"USD {analysis.suggested_price_min:.2f}–{analysis.suggested_price_max:.2f}"
                )
            else:
                st.write("Unknown; no price estimate provided.")
            st.markdown("**Estimated margin at input selling price**")
            st.write(f"{margin_text(result.gross_margin)} at {money_text(product.selling_price)}")
            st.markdown("**Potential problems**")
            for problem in analysis.problems:
                st.write(f"• {problem}")
            st.markdown("**Risks**")
            for risk in analysis.risks:
                st.write(f"• {risk}")
            st.markdown("**Next research steps**")
            for step in analysis.next_steps:
                st.write(f"• {step}")
    with evidence_tab:
        render_target_requirements(result, repo, prefix)
        st.markdown("**Verified data · source evidence only**")
        if product.evidence:
            for evidence in product.evidence:
                st.write(f"{evidence.fact} — Source: {evidence.source}")
        else:
            st.write("None. No verified market evidence has been provided for this product.")
        st.markdown("**Estimated data**")
        st.write(
            f"Product cost {money_text(product.cost)}; "
            f"selling price {money_text(product.selling_price)}. "
            "Local source estimates have not been validated against supplier or market quotes."
        )
        st.write({"Input score assumptions (0–10)": product.hints.model_dump()})
        st.markdown("**AI judgement / demo judgement**")
        st.write(
            f"Demand {analysis.demand:g}, competition {analysis.competition:g}, "
            f"trend {analysis.trend:g}, marketing {analysis.marketing:g} (each out of 10)."
        )
        st.write("Audience, positioning, risks, price range and next steps are analyst hypotheses.")
        st.warning(analysis.uncertainty)
    with score_tab:
        st.markdown("**Transparent weighted score**")
        if result.score_basis == "evidence":
            st.info(
                f"Evidence-backed score · confidence {result.confidence_level.upper()}. "
                "The profit factor uses estimated NET margin, including shipping, fees and ads."
            )
        st.code(
            "10 × (0.25 × demand + 0.25 × margin_score + 0.20 × trend\n"
            "    + 0.15 × (10 − competition) + 0.15 × marketing)"
        )
        values = {
            "Demand": analysis.demand,
            "Profit margin": result.score.profit_potential,
            "Trend": analysis.trend,
            "Competition (inverted)": 10 - analysis.competition,
            "Marketing": analysis.marketing,
        }
        st.dataframe(
            [
                {
                    "Factor": k,
                    "Input (0–10)": round(values[k], 2),
                    "Weight %": round(WEIGHTS[k] * 100),
                    "Weighted points": v,
                }
                for k, v in result.score.components.items()
            ],
            hide_index=True,
            width="stretch",
        )
        if result.score.unadjusted_total is not None:
            st.write(
                f"Raw weighted score {result.score.unadjusted_total:.4f} "
                f"× confidence factor {result.score.confidence_factor:.2f}"
            )
            st.caption(
                "Weak/moderate/strong map to 3/6/9; unsupported dimensions contribute zero "
                "(unknown competition gives no advantage). Low confidence ×0.50, medium ×0.85. "
                "Web summaries never qualify as high-confidence verification."
            )
        st.write(f"**Total: {result.score.total:.1f}/100** (rounded to one decimal).")
        st.caption(
            (
                "Margin score = clamp(estimated net margin % / 10, 0, 10). "
                "Unknown net margin gives zero points."
                if result.score_basis == "evidence"
                else "Margin score = clamp(gross margin % / 10, 0, 10). "
                "Full-precision margin is used "
                "for scoring. Profit potential is this margin score, not estimated net profit."
            )
        )
        if product.selling_price is not None and product.cost is not None:
            st.code(
                f"({product.selling_price:.2f} − {product.cost:.2f}) / "
                f"{product.selling_price:.2f} × 100 = {result.gross_margin:.1f}%"
            )
        else:
            st.info(
                "Product cost or selling price is unknown. No profit-margin points are assumed."
            )
        st.caption(
            "Strong candidate ≥75; Worth investigating ≥55; Weak candidate <55. "
            "This is a prioritization tool, not a probability of success."
        )
    with research_tab:
        render_research_view(product, repo, load_settings())
    with sources_tab:
        render_sources_view(product, repo)
    with economics_tab:
        render_economics_view(product, repo)
        render_market_economics(product, repo)
    with market_tab:
        render_market_intelligence(product, repo)
    with supplier_tab:
        render_supplier_intelligence(product, repo)
