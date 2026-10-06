"""Research states, inline citations and editable deterministic unit economics."""

import streamlit as st
from pydantic import ValidationError

from src.config import Settings
from src.database.database import ProductRepository
from src.research.models import EvidenceFinding, ResearchReport, utc_now
from src.research.providers.base import product_fingerprint
from src.research.research_service import EvidenceResearchService
from src.research.scoring import confidence_for
from src.schemas.product import Product
from src.services.economics import EconomicsInputs, calculate_economics


def current_report(product: Product, repo: ProductRepository) -> ResearchReport | None:
    report = repo.get_research(product.id)
    if report and report.input_fingerprint != product_fingerprint(product):
        return None
    return report


def link_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def render_findings(title: str, findings: list[EvidenceFinding], report: ResearchReport) -> None:
    st.markdown(f"**{title}**")
    if not findings:
        st.write("Insufficient evidence")
        return
    lookup = {s.id: s for s in report.sources}
    for finding in findings:
        st.write(f"AI JUDGEMENT · {finding.claim}")
        st.caption(f"Cited search-report excerpt (AI summary): {finding.supporting_excerpt}")
        links = " · ".join(
            f"[{link_label(lookup[sid].title)}](<{lookup[sid].url}>)" for sid in finding.source_ids
        )
        st.markdown(f"Supporting sources: {links}")


def render_research_view(product: Product, repo: ProductRepository, settings: Settings) -> None:
    st.markdown("**RESEARCH · current external evidence**")
    report = current_report(product, repo)
    stored = repo.get_research(product.id)
    attempt = repo.get_research_attempt(product.id)
    if report and report.status == "completed" and attempt and attempt.status == "insufficient":
        st.warning(
            "Latest attempt: Insufficient evidence. Previous completed research was retained."
        )
    if stored and not report:
        st.warning(
            "Stored research describes different product inputs. Research again to update it."
        )
    if attempt and attempt.status == "failed":
        st.error(f"Research failed · {attempt.notice}")
    elif attempt and attempt.status == "researching":
        st.warning("Researching · a previous attempt may have been interrupted. Retry explicitly.")
    if report is None:
        st.info("No research performed for this product.")
    elif report.status == "completed":
        if attempt and attempt.status in {"failed", "insufficient"}:
            st.info("Previous completed research retained; the latest attempt did not complete.")
        else:
            st.success("Research completed")
    elif report.status == "failed":
        if not attempt or attempt.status != "failed":
            st.error(f"Research failed · {report.notice}")
    else:
        st.warning("Insufficient evidence")
    if report and report.mode == "demo":
        st.info(report.notice)
    elif report and report.notice:
        st.caption(report.notice)
    if st.button("Research product", key=f"research_product_{product.id}", type="primary"):
        run_product_research(product, repo, settings)
        st.rerun()
    st.caption(
        "Explicit research refreshes the latest snapshot. "
        "OpenAI web research may incur API charges. "
        "The Settings demo switch prevents external research. Navigation makes no requests."
    )
    if not report:
        return
    st.caption(
        f"Researched {report.researched_at:%Y-%m-%d %H:%M} UTC · "
        f"Provider {report.provider} · Evidence confidence {confidence_for(report).upper()}"
    )
    if (utc_now() - report.researched_at).days >= 7:
        st.warning("This evidence is over seven days old. Confidence is reduced until refreshed.")
    st.markdown("**Summary · AI JUDGEMENT**")
    st.write(report.research_summary)
    st.caption(
        " · ".join(
            f"{name.title()}: {value.upper()}"
            for name, value in report.dimensions.model_dump().items()
        )
    )
    render_findings("Demand evidence", report.demand_evidence, report)
    render_findings("Competition evidence", report.competition_evidence, report)
    render_findings("Trend evidence", report.trend_evidence, report)
    st.markdown("**Pricing evidence · OBSERVED listing metadata**")
    if report.observed_price_range:
        prices = report.observed_price_range
        st.write(
            f"USD {prices.minimum:.2f}–{prices.maximum:.2f} · "
            f"{prices.sample_size} comparable offers."
        )
        st.caption(
            "Observed JSON-LD listing prices, not a verified market-wide range or sales volume. "
            "Variants, promotions and prices can change; inspect each listing."
        )
        lookup = {s.id: s for s in report.sources}
        for price in report.price_observations:
            source = lookup[price.source_id]
            st.markdown(
                f"{link_label(price.product_title)} · USD {price.price:.2f} · "
                f"[{link_label(source.title)}](<{source.url}>)"
            )
    else:
        st.write("Insufficient evidence: no matching USD Product/Offer metadata was observed.")
    render_findings("Common marketing angles", report.marketing_angles, report)
    render_findings("Common customer complaints", report.common_customer_complaints, report)
    st.markdown("**Risks · AI JUDGEMENT**")
    for risk in report.risks:
        st.write(f"• {risk}")


def run_product_research(
    product: Product, repo: ProductRepository, settings: Settings
) -> ResearchReport:
    """One shared V2 action used by Details and the product-or-category entry point."""
    service = EvidenceResearchService(
        repo,
        api_key=settings.api_key,
        model=settings.research_model,
        force_demo=st.session_state["use_demo"],
    )
    with st.status("Researching", expanded=True) as status:
        progress = st.progress(0)
        stage = [0]

        def update(message):
            stage[0] += 1
            progress.progress(min(90, stage[0] * 25))
            status.write(message)

        result = service.research_product(product, force=True, progress=update)
        progress.progress(100)
        status.update(
            label="Research failed"
            if result.status == "failed"
            else "Research completed"
            if result.status == "completed"
            else "Insufficient evidence",
            state="error" if result.status == "failed" else "complete",
            expanded=False,
        )
    return result


def render_sources_view(product: Product, repo: ProductRepository) -> None:
    st.markdown("**SOURCES · VERIFIED / OBSERVED citation provenance**")
    st.caption(
        "URLs and access times come from web-search tool citations. Source-linked summaries "
        "are AI interpretations; citation presence does not independently verify a market claim."
    )
    report = current_report(product, repo)
    if not report or not report.sources:
        st.info("No sources available. No citations are invented in Demo Mode.")
        return
    for source in report.sources:
        st.markdown(f"[{link_label(source.title)}](<{source.url}>)")
        st.caption(f"Accessed {source.accessed_at:%Y-%m-%d %H:%M:%S} UTC · {source.source_type}")
        st.write(
            f"AI JUDGEMENT · Unverified search-report context: {source.what_claim_it_supports}"
        )


def render_economics_view(product: Product, repo: ProductRepository) -> None:
    st.markdown("**ECONOMICS · ESTIMATED user inputs**")
    inputs = repo.get_economics(product.id) or EconomicsInputs(
        product_cost=product.cost, selling_price=product.selling_price
    )
    fields = [
        "product_cost",
        "selling_price",
        "shipping_cost",
        "payment_fee_percent",
        "estimated_ad_cost_per_order",
    ]
    if st.session_state.get("_economics_owner") != product.id:
        for field in fields:
            st.session_state[f"econ_{field}"] = getattr(inputs, field)
        st.session_state["_economics_owner"] = product.id
    for field in fields:
        if f"econ_{field}" not in st.session_state:
            st.session_state[f"econ_{field}"] = getattr(inputs, field)
    st.caption(
        "Leave unknown shipping, fees and ad cost blank. "
        "Enter 0 only when you intend a zero-cost assumption."
    )
    with st.form("economics_form"):
        columns = st.columns(2)
        cost = columns[0].number_input(
            "Product cost (USD)",
            min_value=0.0,
            max_value=1_000_000.0,
            key="econ_product_cost",
            value=None,
            step=0.5,
        )
        selling = columns[1].number_input(
            "Selling price (USD)",
            min_value=0.01,
            max_value=1_000_000.0,
            key="econ_selling_price",
            value=None,
            step=0.5,
        )
        shipping = columns[0].number_input(
            "Shipping cost (USD)",
            min_value=0.0,
            max_value=1_000_000.0,
            value=None,
            key="econ_shipping_cost",
            step=0.5,
        )
        fees = columns[1].number_input(
            "Payment fee (%)",
            min_value=0.0,
            max_value=100.0,
            value=None,
            key="econ_payment_fee_percent",
            step=0.1,
        )
        ads = columns[0].number_input(
            "Estimated ad cost per order (USD)",
            min_value=0.0,
            max_value=1_000_000.0,
            value=None,
            key="econ_estimated_ad_cost_per_order",
            step=0.5,
        )
        save = st.form_submit_button("Save economics assumptions")
    if save:
        try:
            inputs = EconomicsInputs(
                product_cost=cost,
                selling_price=selling,
                shipping_cost=shipping,
                payment_fee_percent=fees,
                estimated_ad_cost_per_order=ads,
            )
        except ValidationError:
            st.error(
                "Enter valid finite costs and a positive selling price. "
                "Payment fees must be 0–100%."
            )
        else:
            repo.save_economics(product.id, inputs)
            st.session_state["flash"] = (
                "Economics assumptions saved. Scores recalculated without an API request."
            )
            st.rerun()
    result = calculate_economics(inputs)
    top = st.columns(3)
    bottom = st.columns(3)

    def money(value):
        return f"USD {value:.2f}" if value is not None else "Unknown"

    def percent(value):
        return f"{value:.2f}%" if value is not None else "Unknown"

    top[0].metric("Gross profit", money(result.gross_profit))
    top[1].metric("Gross margin after shipping", percent(result.gross_margin_percent))
    top[2].metric("Payment fees", money(result.payment_fee))
    bottom[0].metric("Estimated net profit", money(result.estimated_net_profit))
    bottom[1].metric("Estimated net margin", percent(result.estimated_net_margin_percent))
    bottom[2].metric("Break-even CPA", money(result.break_even_ad_cost))
    if result.missing_inputs:
        st.info(
            "Unknown assumptions: "
            + ", ".join(f.replace("_", " ") for f in result.missing_inputs)
            + ". Dependent outputs are unavailable; "
            "research scoring gives no net-margin points."
        )
    if result.break_even_ad_cost is not None and result.break_even_ad_cost < 0:
        st.warning("No profitable nonnegative CPA: the offer loses money even before advertising.")
    st.code(
        "gross_profit = selling_price − product_cost − shipping\n"
        "payment_fee = selling_price × fee_percent / 100\n"
        "estimated_net_profit = gross_profit − payment_fee − ad_cost\n"
        "break_even_CPA = gross_profit − payment_fee"
    )
    st.caption(
        "Deterministic calculations in USD. Payment fees round to cents "
        "before net-profit arithmetic. "
        "Taxes, returns, fixed payment fees and fixed overhead are excluded. "
        "The V1 table's gross margin remains product-only; V2 scoring uses estimated net margin."
    )
