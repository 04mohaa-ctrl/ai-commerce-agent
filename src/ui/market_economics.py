"""Explicit V3 assumptions and nullable calculations alongside legacy V2 economics."""

import streamlit as st
from pydantic import ValidationError

from src.database.market_repository import MarketIntelligenceRepository
from src.services.market_economics import MarketEconomicsInputs, calculate_market_economics

LABELS = {
    "unit_product_cost": "Unit product cost (USD)",
    "international_shipping_per_unit": "International shipping per unit (USD)",
    "import_duty_per_unit": "Import duty per unit (USD)",
    "customs_fee_per_unit": "Customs fee per unit (USD)",
    "packaging_per_unit": "Packaging per unit (USD)",
    "handling_per_unit": "Handling per unit (USD)",
    "other_variable_cost_per_unit": "Other variable cost per unit (USD)",
    "selling_price": "V3 selling price (USD)",
    "payment_fee_percent": "V3 payment fee (%)",
    "payment_fixed_fee": "Fixed payment fee (USD)",
    "return_rate_percent": "Return rate assumption (%)",
    "estimated_loss_per_return": "Estimated loss per return (USD)",
    "estimated_ad_cost_per_order": "V3 estimated ad cost per order (USD)",
}


def render_market_economics(product, repo):
    st.divider()
    st.markdown("**V3 ECONOMICS · ESTIMATED landed cost and returns**")
    extension = MarketIntelligenceRepository(repo)
    legacy = repo.get_economics(product.id)
    inputs = extension.get_economics(product.id) or MarketEconomicsInputs(
        unit_product_cost=legacy.product_cost if legacy else product.cost,
        selling_price=legacy.selling_price if legacy else product.selling_price,
        payment_fee_percent=legacy.payment_fee_percent if legacy else None,
        estimated_ad_cost_per_order=legacy.estimated_ad_cost_per_order if legacy else None,
    )
    if st.session_state.get("_market_economics_owner") != product.id:
        for field in LABELS:
            st.session_state[f"market_econ_{field}"] = getattr(inputs, field)
        st.session_state["_market_economics_owner"] = product.id
    for field in LABELS:
        if f"market_econ_{field}" not in st.session_state:
            st.session_state[f"market_econ_{field}"] = getattr(inputs, field)
    st.caption(
        "Leave unknown landed costs, fixed fees and returns blank. Enter zero explicitly. "
        "Legacy shipping is not automatically treated as international freight."
    )
    with st.form("market_economics_form"):
        cols, values = st.columns(2), {}
        for index, (field, label) in enumerate(LABELS.items()):
            values[field] = cols[index % 2].number_input(
                label,
                key=f"market_econ_{field}",
                value=None,
                min_value=0.01 if field == "selling_price" else 0.0,
                max_value=100.0 if field.endswith("_percent") else 1_000_000.0,
                step=0.1 if field.endswith("_percent") else 0.5,
            )
        save = st.form_submit_button("Save V3 economics assumptions")
    if save:
        try:
            inputs = MarketEconomicsInputs(**values)
            extension.save_economics(product.id, inputs)
        except ValidationError:
            st.error("Use finite nonnegative costs, positive selling price and percentages 0–100.")
        else:
            st.session_state["flash"] = (
                "V3 economics saved; market score recalculated without requests."
            )
            st.rerun()
    result = calculate_market_economics(inputs)
    rows = [
        (label, getattr(result, field))
        for label, field in [
            ("V3 revenue per order", "revenue_per_order"),
            ("V3 landed cost", "landed_cost"),
            ("V3 gross profit before marketing", "gross_profit_before_marketing"),
            ("V3 payment cost", "payment_cost"),
            ("V3 expected return cost", "expected_return_cost"),
            ("V3 contribution before ads", "contribution_before_ads"),
            ("V3 estimated ad cost", "estimated_ad_cost"),
            ("V3 estimated net profit", "estimated_net_profit"),
            ("V3 break-even CPA", "break_even_ad_cost"),
        ]
    ]
    for offset in range(0, len(rows), 3):
        for col, (label, value) in zip(st.columns(3), rows[offset : offset + 3]):
            col.metric(label, f"USD {value:.2f}" if value is not None else "Unknown")
    margin = result.estimated_net_margin_percent
    st.metric("V3 estimated net margin", f"{margin:.2f}%" if margin is not None else "Unknown")
    if result.missing_inputs:
        st.info(
            "Unknown V3 assumptions: "
            + ", ".join(f.replace("_", " ") for f in result.missing_inputs)
            + ". Dependent outputs stay unavailable."
        )
    if result.break_even_ad_cost is not None and result.break_even_ad_cost < 0:
        st.warning("Loss before advertising: no profitable nonnegative CPA.")
    st.code(
        "landed = unit + international shipping + duty + customs + packaging + handling + other\n"
        "payment = selling price × fee % / 100 + fixed fee\n"
        "expected returns = return rate % / 100 × loss per return\n"
        "contribution = selling price − landed − payment − expected returns\n"
        "net = contribution − ads; net margin = net / selling price × 100\n"
        "break-even CPA = contribution"
    )
    st.caption(
        "Decimal arithmetic, half-up cents. Return loss is a manual assumption: include "
        "refund/logistics/recovery losses once. Sales tax and fixed overhead remain excluded."
    )
