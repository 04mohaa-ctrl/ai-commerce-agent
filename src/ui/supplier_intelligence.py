"""Read-only rendering; providers run only behind explicit research actions."""

import os

import streamlit as st
from pydantic import ValidationError

from src.database.market_repository import MarketIntelligenceRepository
from src.database.supply_repository import SupplyRepository
from src.research.providers.base import product_fingerprint
from src.services.market_economics import MarketEconomicsInputs
from src.supply.economics import (
    FinancialSnapshot,
    apply_shipping_cost,
    apply_supplier_cost,
    calculate_financial,
    save_manual_inputs,
    selection_issue,
    shipping_issue,
    supplier_cost_issue,
    utc_now,
)
from src.supply.models import Destination, SupplierSelection, normalize_limit_stage
from src.supply.scoring import score_opportunity, score_supply
from src.supply.service import SupplierIntelligenceService
from src.ui.market_economics import LABELS
from src.ui.supplier_financial import FIELD_LABELS, HELP, blocked_results, render_tax_and_fx
from src.ui.supplier_requirements import WORKFLOW_REVISION, render_supplier_requirements
from src.ui.supplier_shipping import catalog_offers, render_shipping_flow

COUNTRIES = {
    "US": "United States",
    "GB": "United Kingdom",
    "SE": "Sweden",
    "DE": "Germany",
    "FR": "France",
}


def optional_provider_configured():
    from src.config import offline_mode

    if offline_mode():
        return False
    return bool(
        os.getenv("CJ_API_KEY", "").strip()
        or (
            os.getenv("DATAFORSEO_LOGIN", "").strip()
            and os.getenv("DATAFORSEO_PASSWORD", "").strip()
        )
    )


def research_destination(product, repo):
    return SupplyRepository(repo).get_settings(product.id) or Destination(
        country=st.session_state.get("v4_target_country", "US"),
        quantity=int(st.session_state.get("v4_target_quantity", 1)),
        max_delivery_days=int(st.session_state.get("v4_target_delivery", 14)),
    )


def render_target_inputs():
    st.caption(
        "Customer target market and order quantity for supplier and demand research; "
        "no personal address."
    )
    cols = st.columns(3)
    cols[0].selectbox(
        "Customer target market",
        list(COUNTRIES),
        format_func=COUNTRIES.get,
        key="v4_target_country",
    )
    cols[1].number_input(
        "Units per order", min_value=1, max_value=1000, value=1, step=1, key="v4_target_quantity"
    )
    cols[2].number_input(
        "Maximum delivery days",
        min_value=1,
        max_value=365,
        value=14,
        step=1,
        key="v4_target_delivery",
    )


def _score_view(score):
    st.markdown(f"**{score.version} · {score.recommendation}**")
    # Preserve stored V4 aggregates and gates; supply presentation uses the approved /10 scale.
    divisor, scale = (10, 10) if score.version == "supply-v4" else (1, 100)
    score_text = (
        f"{score.final_score / divisor:g}"
        if score.final_score is not None
        else "Unavailable / provisional"
    )
    raw_text = f"{score.raw_total / divisor:g}" if score.raw_total is not None else "Unavailable"
    st.write(
        f"Score: {score_text} / {scale}"
        f" · Evidence coverage {score.coverage:g}% · Confidence {score.confidence}"
    )
    st.caption(
        f"Raw total {raw_text} / {scale} "
        f"× confidence factor {score.confidence_factor:g}; "
        f"financial revision {score.financial_revision}."
    )
    st.dataframe(
        [
            {
                "Dimension": name,
                "Raw /10": d.raw_score,
                "Availability": d.availability,
                "Weight %": d.weight * 100,
                f"Contribution /{scale}": round(d.contribution / divisor, 4),
                "Evidence IDs": ", ".join(d.evidence_ids),
                "Explanation": d.reason,
            }
            for name, d in score.dimensions.items()
        ],
        hide_index=True,
        width="stretch",
    )
    for risk in score.risks:
        st.warning(
            f"{risk.code}: {risk.explanation} · "
            f"Evidence: {', '.join(risk.evidence_ids) or 'Unavailable'}"
        )


def _stage_view(stage):
    stage = normalize_limit_stage(stage)
    status = stage["status"]
    source = stage.get("limit_source")
    if status == "BUDGET_EXHAUSTED":
        status = (
            "Local action time budget exhausted"
            if source == "LOCAL_TIME_BUDGET"
            else "Local request budget exhausted"
            if source == "LOCAL_REQUEST_BUDGET"
            else "Local action budget exhausted"
        )
    elif status == "RATE_LIMITED":
        status = (
            "Provider rate/quota limited"
            if source in {"PROVIDER_RATE_LIMIT", "PROVIDER_QUOTA_LIMIT"}
            else "Rate limited (origin unavailable)"
        )
    st.write(
        f"{stage['component']}: {status}"
        + (" · historical evidence retained" if stage.get("retained") else "")
        + (" · pending" if stage.get("pending") else "")
    )
    if stage.get("notice"):
        st.caption(stage["notice"])


def _telemetry_view(action):
    payload = action.model_dump(mode="json")
    payload["stages"] = [normalize_limit_stage(stage) for stage in payload["stages"]]
    st.json(payload)


def _financial(product, repo, extension, service, destination):
    market = MarketIntelligenceRepository(repo)
    stored_snapshot = extension.get_financial(product.id)
    snapshot = stored_snapshot or FinancialSnapshot(
        inputs=(
            market.get_economics(product.id)
            or MarketEconomicsInputs(
                unit_product_cost=product.cost, selling_price=product.selling_price
            )
        ).model_copy(deep=True)
    )
    selection = extension.get_selection(product.id)
    stages = service.current_stages(product)
    st.markdown("**V4 ECONOMICS · separate financial snapshot (USD)**")
    st.caption(
        "Initial inputs are copies of V3 assumptions. Observations apply only on your explicit "
        "action. Blank is unknown; zero is an explicit estimate. Costs are USD per unit; "
        "fixed payment fees, return loss, ads and profit are per order. "
        "FX requires an explicit rate."
    )
    now = utc_now()
    cost_issue = supplier_cost_issue(selection, snapshot.currency, now, stages, destination)
    quote_issue = shipping_issue(selection, destination, snapshot.currency, now, stages)
    if selection:
        v, q = selection.offer.variant, selection.offer.quote
        st.write(
            f"Selected cost: {v.currency or 'Unknown currency'} "
            f"{v.unit_price if v.unit_price is not None else 'Unknown'} · variant {v.variant_id} "
            f"· {v.observed_at.isoformat()}"
        )
        if q:
            st.write(
                f"Shipping quote total: {q.currency or 'Unknown currency'} "
                f"{q.total_cost if q.total_cost is not None else 'Unknown'} for {q.quantity} units "
                f"· {q.method} · {q.observed_at.isoformat()}"
            )
    cols = st.columns(2)
    if cols[0].button(
        "Apply observed supplier cost", key=f"v4_apply_cost_{product.id}", disabled=bool(cost_issue)
    ):
        extension.save_financial(
            product.id, apply_supplier_cost(snapshot, selection, destination, stages=stages)
        )
        st.rerun()
    if cols[1].button(
        "Apply current shipping quote",
        key=f"v4_apply_quote_{product.id}",
        disabled=bool(quote_issue),
    ):
        extension.save_financial(
            product.id, apply_shipping_cost(snapshot, selection, destination, stages=stages)
        )
        st.rerun()
    st.caption(f"Supplier cost: {cost_issue or 'eligible'} · Shipping: {quote_issue or 'eligible'}")
    owner = (
        (product.id, snapshot.revision, snapshot.updated_at.isoformat())
        if stored_snapshot
        else (product.id, "unsaved")
    )
    if st.session_state.get("_v4_financial_owner") != owner:
        for field in LABELS:
            st.session_state[f"v4_econ_{product.id}_{field}"] = getattr(snapshot.inputs, field)
        st.session_state["_v4_financial_owner"] = owner
    for field in LABELS:
        key = f"v4_econ_{product.id}_{field}"
        if key not in st.session_state:
            st.session_state[key] = getattr(snapshot.inputs, field)
    with st.form(f"v4_economics_{product.id}"):
        values, columns = {}, st.columns(2)
        for i, (field, label) in enumerate(LABELS.items()):
            values[field] = columns[i % 2].number_input(
                FIELD_LABELS.get(field, label).replace("V3", "V4"),
                key=f"v4_econ_{product.id}_{field}",
                value=None,
                min_value=0.01 if field == "selling_price" else 0.0,
                max_value=100.0 if field.endswith("_percent") else 1_000_000.0,
                step=0.1 if field.endswith("_percent") else 0.5,
                help=HELP.get(field),
            )
        save = st.form_submit_button("Save V4 economics assumptions")
    if save:
        try:
            extension.save_financial(
                product.id, save_manual_inputs(snapshot, MarketEconomicsInputs(**values))
            )
        except ValidationError:
            st.error("Use finite nonnegative costs, positive selling price and percentages 0–100.")
        else:
            st.rerun()
    render_tax_and_fx(product, extension, snapshot, saved=stored_snapshot is not None)
    finance = calculate_financial(snapshot, selection, destination, stages)
    st.metric("Known compatible unit cost subtotal", f"USD {finance.known_cost_subtotal:.2f}")
    st.caption("A subtotal is not complete landed cost or profit.")
    result = finance.economics
    st.caption(
        f"Landed cost / order: USD {finance.landed_cost_per_order:.2f}"
        if finance.landed_cost_per_order is not None
        else "Landed cost / order: Unknown"
    )
    st.caption(
        "Adopted freight keeps the exact quote total per order; the displayed unit "
        "allocation is rounded and may not multiply back to that total."
    )
    for col, (label, field) in zip(
        st.columns(3),
        [
            ("V4 landed cost / unit", "landed_cost"),
            ("V4 net profit / order", "estimated_net_profit"),
            ("V4 break-even CPA / order", "break_even_ad_cost"),
        ],
    ):
        value = getattr(result, field) if result else None
        col.metric(label, f"USD {value:.2f}" if value is not None else "Unknown")
    st.caption(
        f"Units per order: {destination.quantity}. Revenue excludes output VAT. "
        "Net profit is estimated order contribution after ads, before overhead and income tax. "
        "Break-even CPA is the maximum ad spend per order for zero contribution. "
        "Separate customer delivery charges, special tax schemes and mixed-currency costs "
        "are not represented; incorporate applicable costs explicitly before relying on a result."
    )
    for label, missing in blocked_results(finance.missing_inputs).items():
        if missing:
            st.info(f"{label} blocked by: " + "; ".join(missing))
    for reason in finance.reasons:
        st.warning("Current results blocked: " + reason)
    with st.expander("Financial provenance and calculations"):
        st.json(snapshot.model_dump(mode="json"))
        st.code(
            "landed/unit = product + freight + duty + customs + packaging + handling "
            "+ other + unrecoverable import VAT\n"
            "revenue/order = price excluding output VAT × units\n"
            "payment/order = customer charge including output VAT × units × fee% /100 + fixed fee\n"
            "returns = return rate% /100 × loss per return\n"
            "net/order = revenue − landed/unit × units − payment − returns − ads\n"
            "break-even CPA/order = revenue − landed/unit × units − payment − returns"
        )
    _score_view(score_supply(selection, destination, snapshot, stages))
    from src.supply.demand import current_market_overlay

    current_market = current_market_overlay(product, repo, destination)
    _score_view(score_opportunity(current_market, selection, destination, snapshot, stages))


def render_supplier_intelligence(product, repo):
    extension = SupplyRepository(repo)
    service = SupplierIntelligenceService(extension)
    destination = research_destination(product, repo)
    report = extension.get_report(product.id)
    if report and report.input_fingerprint != product_fingerprint(product):
        st.warning(
            "Stored supplier observations describe different product inputs. "
            "Research explicitly before selecting or applying them."
        )
        report = None
    st.markdown("**SUPPLIER INTELLIGENCE · optional read-only CJ observations**")
    st.caption(f"Workflow {WORKFLOW_REVISION} · Product ID {product.id}")
    render_supplier_requirements(product, repo, destination, "offers")
    if not service.provider.configured:
        st.info("Live supplier data unavailable. CJ credentials are not configured.")
    else:
        st.caption(
            "CJ credentials configured. Configuration does not establish connectivity "
            "or supplier quality."
        )
    st.caption(
        f"Query: {product.name} · Customer market: "
        f"{COUNTRIES.get(destination.country, destination.country)} "
        f"· Quantity {destination.quantity} "
        f"· Maximum delivery {destination.max_delivery_days} days. "
        "Country-only freight; postal/region quoting unsupported."
    )
    with st.form(f"v4_destination_{product.id}"):
        cols = st.columns(3)
        country = cols[0].selectbox(
            "Target customer country",
            list(COUNTRIES),
            index=list(COUNTRIES).index(destination.country),
            key=f"v4_country_{product.id}",
            format_func=COUNTRIES.get,
        )
        quantity = cols[1].number_input(
            "Quote quantity",
            value=destination.quantity,
            min_value=1,
            max_value=1000,
            step=1,
            key=f"v4_qty_{product.id}",
        )
        days = cols[2].number_input(
            "Acceptable delivery days",
            value=destination.max_delivery_days,
            min_value=1,
            max_value=365,
            step=1,
            key=f"v4_days_{product.id}",
        )
        save = st.form_submit_button("Save target market")
    if save:
        extension.save_settings(
            product.id, Destination(country=country, quantity=quantity, max_delivery_days=days)
        )
        st.rerun()
    demo = st.session_state.get("use_demo", True)
    if demo:
        st.info("Demo Mode: external supplier and demand requests are disabled.")
    actions = st.columns(3)
    st.caption(
        "Explicit per-candidate actions: supplier refresh ≤12 HTTP attempts /90 seconds; "
        "shipping ≤4 attempts /90 seconds; original-name demand ≤1 request /20 seconds. "
        "CJ quota points are provider limits, separate from local request caps and money. "
        "Charges depend on your provider account; no dollar price is established here. "
        "Supplier/freight and cost adoption remain separate."
    )
    if actions[0].button("Refresh supplier data", key=f"v4_supplier_{product.id}", disabled=demo):
        with st.spinner("Refreshing bounded supplier observations…"):
            service.research(product, destination, force=True)
        st.rerun()
    shipping_block = service.shipping_request_issue(product, destination, demo=demo)
    if actions[1].button(
        "Refresh shipping", key=f"v4_shipping_{product.id}", disabled=bool(shipping_block)
    ):
        service.refresh_shipping(product, destination)
        st.rerun()
    if actions[2].button("Refresh demand", key=f"v4_demand_{product.id}", disabled=demo):
        from src.supply.demand import DemandIntelligenceService

        DemandIntelligenceService(extension).refresh(product, destination, force=True)
        st.rerun()
    if report:
        st.caption(
            f"Supplier run {report.researched_at.isoformat()} "
            "· Observations retain original collection times."
        )
        with st.expander("Supplier request details"):
            for stage in report.stages:
                _stage_view(stage)
        if report.destination != destination:
            st.warning(
                "Supplier observations were collected for different target settings. "
                "Refresh explicitly; historical selection remains unchanged."
            )
        if not report.offers:
            st.info(
                "No current supplier offers. Empty results do not establish stock, price or demand."
            )
    else:
        st.info("No supplier research performed. Research product or refresh explicitly.")
    selected = extension.get_selection(product.id)
    if selected:
        st.write(
            f"Selected snapshot: {selected.offer.variant.variant_id} · warehouse "
            f"{selected.offer.stock.warehouse_id if selected.offer.stock else 'Unknown'} "
            f"· selected {selected.selected_at.isoformat()}"
        )
        if report and not any(o.id == selected.offer.id for o in report.offers):
            same_supplier = any(
                o.candidate.id == selected.offer.candidate.id
                and o.variant.id == selected.offer.variant.id
                and (o.stock.id if o.stock else None)
                == (selected.offer.stock.id if selected.offer.stock else None)
                and o.match == selected.offer.match
                for o in report.offers
            )
            if same_supplier:
                st.info(
                    "Shipping changed for the selected variant. Choose a method below and "
                    "Select shipping quote; product cost stays independent."
                )
            else:
                st.warning(
                    "Selected supplier observation is historical. Review and select an updated "
                    "offer explicitly; adopted costs are preserved."
                )
        if st.button("Clear supplier selection", key=f"v4_clear_{product.id}"):
            extension.save_selection(product.id, None)
            st.rerun()
    for offer in catalog_offers(report.offers, selected) if report else []:
        # Recheck even pre-fix classifications before offering a selection control.
        offer = offer.model_copy(update={"match": service.match_offer(product, offer, destination)})
        key = f"v4_{product.id}_{offer.id}"
        with st.container(border=True):
            st.markdown(f"**{offer.candidate.name} · {offer.match.outcome}**")
            st.write(
                f"Provider {offer.variant.provider} · product {offer.variant.product_id} "
                f"· variant {offer.variant.variant_id} · {offer.variant.name}"
            )
            st.write(dict(offer.variant.attributes))
            price = offer.variant.unit_price if offer.variant.unit_price is not None else "Unknown"
            st.caption(
                f"Variant price {offer.variant.currency or 'Unknown'} "
                f"{price} "
                f"· collected {offer.variant.observed_at.isoformat()}"
            )
            if offer.candidate.source_url:
                st.link_button("Open source listing", offer.candidate.source_url)
            st.write("Match reasons: " + "; ".join(offer.match.reasons))
            st.write(
                "Contradictions: " + ("; ".join(offer.match.contradictions) or "None observed")
            )
            st.write(
                "Missing attributes: "
                + (", ".join(offer.match.missing_attributes) or "None required")
            )
            stock, quote = offer.stock, offer.quote
            if stock:
                factory = (
                    stock.factory_quantity if stock.factory_quantity is not None else "Unknown"
                )
                st.write(
                    f"Stock {stock.quantity if stock.quantity is not None else 'Unknown'} · "
                    f"CJ {stock.cj_quantity if stock.cj_quantity is not None else 'Unknown'} · "
                    f"factory {factory}"
                    f" · warehouse {stock.warehouse_id} / storage {stock.storage_id} "
                    f"· origin {stock.country} · {stock.observed_at.isoformat()}"
                )
            else:
                st.write("Stock and warehouse: Unknown")
            if quote:
                low = quote.delivery_min_days if quote.delivery_min_days is not None else "Unknown"
                high = quote.delivery_max_days if quote.delivery_max_days is not None else "Unknown"
                tracking = quote.tracking if quote.tracking is not None else "Unknown"
                st.write(
                    f"{quote.method} · Total {quote.currency} {quote.total_cost} "
                    f"for {quote.quantity} units · destination {quote.destination.country} · "
                    f"delivery {low}–{high} days · tracking {tracking} "
                    f"· {quote.observed_at.isoformat()}"
                )
                if quote.total_cost is not None:
                    st.caption(
                        f"Derived freight per unit: {quote.currency} "
                        f"{quote.total_cost / quote.quantity:.2f}. Delivery is an estimate."
                    )
            else:
                st.write(
                    "Applicable freight / delivery / tracking: Unknown. "
                    "Select explicitly and refresh shipping."
                )
            confirm = False
            if offer.match.outcome == "LIKELY_MATCH":
                confirm = st.checkbox(
                    "I confirm these observed variant attributes match the intended product",
                    key=key + "_confirm",
                )
            selection = (
                SupplierSelection(
                    offer=offer,
                    confirmed_attributes=dict(offer.variant.attributes) if confirm else {},
                )
                if offer.match.outcome != "NO_MATCH"
                else None
            )
            issue = (
                selection_issue(selection, destination)
                if selection
                else "Supplier product identity is incompatible."
            )
            eligible = issue is None
            st.caption(f"Selection: {issue or 'eligible; selecting does not adopt costs.'}")
            if st.button("Select this offer", key=key + "_select", disabled=not eligible):
                extension.save_selection(product.id, selection)
                # Persist the locally displayed classification before subsequent freight/adoption.
                service.recheck_saved(product, destination)
                st.session_state["supplier_focus_product"] = product.id
                st.rerun()
            label = st.selectbox("Shortlist role", ["Preferred", "Backup"], key=key + "_label")
            notes = st.text_input("Local shortlist notes", key=key + "_notes", max_chars=1000)
            if st.button("Save to shortlist", key=key + "_shortlist"):
                extension.save_shortlist(product.id, offer, label, notes)
                st.rerun()
    with st.expander("Local supplier shortlist"):
        st.caption(
            "Preferred/Backup are saved review notes and observation snapshots. "
            "They do not select an offer, establish compatibility or adopt costs."
        )
        for row in extension.get_shortlist(product.id):
            st.write(f"{row['label']} · {row['offer']['variant']['variant_id']} · {row['notes']}")
    from src.supply.demand import DemandIntelligenceService

    render_shipping_flow(product, destination, extension, service, demo)

    demand = DemandIntelligenceService(extension).get_current(product, destination)
    st.markdown("**MEASURED DEMAND · relative search-interest / popularity**")
    if demand:
        st.write(demand.outcome.notice or "Measured demand data unavailable")
        st.write(
            f"Latest demand attempt: {demand.outcome.status} · "
            f"{demand.outcome.observed_at.isoformat()}"
        )
        if demand.outcome.status == "FAILED":
            st.caption(
                f"Failure category: {demand.outcome.failure_kind or 'UNKNOWN HISTORICAL'} · "
                f"HTTP status: {demand.outcome.http_status or 'not retained'} · "
                f"Provider status: {demand.outcome.provider_status or 'not retained'} · "
                f"Requests in latest action: {sum(demand.telemetry.requests.values())} · "
                f"Cache hits: {', '.join(demand.telemetry.cache_hits) or 'none'}"
            )
            st.warning(
                demand.outcome.notice + " "
                "Older failures may lack HTTP/provider/timeout detail; cause cannot be inferred. "
                "Resolve access, timeout or response issues before refreshing demand only. "
                "No demand value or score is inferred from failure."
            )
        bins = demand.demand.observations
        usable = sum(not o.missing and o.value is not None for o in bins)
        st.caption(
            f"Usable demand observations: {usable} / {len(bins)}. "
            "Missing/zero index values are insufficient data, not zero demand."
        )
        if bins and usable < len(bins):
            st.info(
                "Sparse observations may be insufficient for trend scoring. "
                "Evidence and coverage gates still apply."
            )
        st.caption(
            f"Provider {demand.provider} · query {demand.query} · {demand.location} · "
            f"{demand.period_start}–{demand.period_end} · "
            f"collected {demand.demand.collected_at.isoformat()}"
        )
        st.write(
            f"Current eligibility: {demand.current_eligible} · "
            f"Deterministic trend: {demand.trend.classification}"
        )
        if demand.retained:
            st.warning("Previous measured observations are historical; latest attempt unavailable.")
        with st.expander("Raw relative search-interest observations"):
            st.write([o.model_dump(mode="json") for o in demand.demand.observations])
    else:
        st.write("Measured demand data unavailable")
    _financial(product, repo, extension, service, destination)
    with st.expander("V4 request telemetry · latest explicit action"):
        if report:
            st.caption("Latest supplier action: actual dispatched attempts, caches and outcomes.")
            _telemetry_view(report.telemetry)
        action = extension.get_latest_action(product.id)
        if action:
            _telemetry_view(action)
        else:
            st.write(
                "No V4 requests. Navigation, selection, shortlist and economics saves "
                "make no provider calls."
            )
        market_run = MarketIntelligenceRepository(repo).latest_run(product.id)
        if market_run:
            st.caption(
                "Latest shared web/market action: OpenAI, web search, page fetch and demand counts."
            )
            st.json(market_run.model_dump(mode="json"))
    st.caption(
        "Prices, stock and freight may change. Catalog presence does not verify quality or demand. "
        "Relative interest is not sales; a retail median is not an achievable-price guarantee. "
        "Scores prioritize investigation and are not probabilities of success."
    )
