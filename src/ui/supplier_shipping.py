"""Shipping request state and explicit selection of exact saved freight observations."""

import streamlit as st

from src.supply.economics import component_state, fresh, shipping_issue, utc_now
from src.supply.models import SupplierSelection


def catalog_offers(offers, selected):
    """Freight methods have their own chooser; keep exact variant/warehouse cards."""
    grouped = {}
    for offer in offers:
        key = (offer.candidate.id, offer.variant.id, offer.stock.id if offer.stock else None)
        if key not in grouped or (selected and offer.id == selected.offer.id):
            grouped[key] = offer
    return list(grouped.values())


def quote_cohort(offers, selected):
    if not selected:
        return []
    return [
        o
        for o in offers
        if o.quote
        and o.candidate.id == selected.offer.candidate.id
        and o.variant.id == selected.offer.variant.id
        and o.stock
        and selected.offer.stock
        and o.stock.id == selected.offer.stock.id
        and o.match == selected.offer.match
    ]


def saved_method(offers, selected, session_value):
    ids = [o.id for o in offers]
    if session_value in ids:
        return session_value
    if selected and selected.offer.id in ids:
        return selected.offer.id
    return ids[0] if ids else None


def shipping_state(stage, offers, now):
    stage = stage or {}
    status = stage.get("status")
    state = stage.get("shipping_state") or {
        "SUCCESS_EMPTY": "EMPTY",
        "SUCCESS": "SUCCESS",
        "FAILED": "FAILED",
    }.get(status, "NOT_REQUESTED" if not stage or stage.get("pending") else "BLOCKED")
    if (
        state == "SUCCESS"
        and offers
        and all(
            not fresh(o.quote.observed_at, 6, now)
            or (o.quote.expires_at is not None and now >= o.quote.expires_at)
            for o in offers
        )
    ):
        return "STALE"
    return state


def render_shipping_flow(product, destination, extension, service, demo):
    st.markdown("**Shipping for the selected CJ offer**")
    issue = service.shipping_request_issue(product, destination, demo=demo)
    report = extension.get_report(product.id)
    selected = extension.get_selection(product.id)
    stage = component_state("shipping", selected, report.stages if report else [])
    if not stage and report:
        stage = next((s for s in reversed(report.stages) if s.get("component") == "shipping"), None)
    cohort = quote_cohort(report.offers, selected) if report else []
    state = shipping_state(stage, cohort, utc_now())
    st.write(f"Shipping request: {state.replace('_', ' ').lower()}")
    if issue:
        st.info("Shipping blocked: " + issue)
    elif state in {"NOT_REQUESTED", "BLOCKED"}:
        st.info("Selected variant and warehouse are ready. Refresh shipping requests freight only.")
    if state == "FAILED":
        st.warning(
            "Freight request failed. "
            + (stage or {}).get("notice", "")
            + " Review provider access or the indicated limit; retry shipping only when resolved."
        )
    if state == "EMPTY":
        st.info(
            "The freight response returned no applicable methods. No cost or delivery is inferred."
        )
    if state == "STALE":
        st.warning(
            "Saved freight is stale. Refresh shipping only to obtain a current quote; "
            "historical costs and observations are retained."
        )
    if not selected or not report:
        return
    if not cohort:
        return
    lookup = {o.id: o for o in cohort}
    key = f"shipping_method_{product.id}"
    st.session_state[key] = saved_method(cohort, selected, st.session_state.get(key))
    chosen_id = st.selectbox(
        "Shipping method for selected variant",
        list(lookup),
        key=key,
        format_func=lambda oid: (
            f"{lookup[oid].quote.method} · {lookup[oid].quote.currency} "
            f"{lookup[oid].quote.total_cost} / order"
        ),
    )
    offer = lookup[chosen_id]
    quote = offer.quote
    low = quote.delivery_min_days if quote.delivery_min_days is not None else "Unknown"
    expiry = quote.expires_at.isoformat() if quote.expires_at else "6 hours after collection"
    st.write(
        f"Delivery estimate: {low}"
        f"–{quote.delivery_max_days if quote.delivery_max_days is not None else 'Unknown'} days · "
        f"Tracking: {quote.tracking if quote.tracking is not None else 'Unknown'}"
    )
    if (
        quote.delivery_max_days is not None
        and quote.delivery_max_days > destination.max_delivery_days
    ):
        st.warning("This delivery estimate exceeds your maximum delivery assumption.")
    st.caption(f"Collected {quote.observed_at.isoformat()} · Expires {expiry}")
    st.write(
        {
            "CJ shipping cost / order": str(quote.total_cost)
            if quote.total_cost is not None
            else None,
            "CJ taxes fee": str(quote.taxes_fee) if quote.taxes_fee is not None else None,
            "CJ clearance operation fee": str(quote.clearance_operation_fee)
            if quote.clearance_operation_fee is not None
            else None,
            "CJ total postage fee": str(quote.total_postage_fee)
            if quote.total_postage_fee is not None
            else None,
            "Currency": quote.currency,
        }
    )
    st.caption(
        "Adoption uses CJ shipping cost (logisticPrice). Other returned fee fields are "
        "shown separately and are not automatically added. Review any difference and "
        "enter additional costs explicitly without counting a fee twice."
    )
    proposed = SupplierSelection(
        offer=offer, confirmed_attributes=dict(selected.confirmed_attributes)
    )
    quote_issue = service.shipping_request_issue(
        product, destination, require_provider=False
    ) or shipping_issue(proposed, destination, "USD", utc_now(), report.stages)
    st.caption(
        f"Quote for product {offer.variant.product_id} · variant {offer.variant.variant_id} · "
        f"warehouse {offer.stock.warehouse_id} · storage {offer.stock.storage_id}. "
        "Selecting this quote preserves product-cost adoption and does not adopt freight."
    )
    if quote_issue:
        st.warning("Quote selection blocked: " + quote_issue)
    if st.button(
        "Select shipping quote", key=f"choose_quote_{product.id}", disabled=bool(quote_issue)
    ):
        extension.save_selection(product.id, proposed)
        st.session_state["supplier_focus_product"] = product.id
        st.rerun()
