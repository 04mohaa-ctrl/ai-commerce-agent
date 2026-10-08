"""Explicit V4 scenario inputs and result-specific unknowns; no provider access."""

from datetime import date

import streamlit as st
from pydantic import ValidationError

from src.services.landed_cost import LANDED_COST_FIELDS
from src.supply.economics import save_customer_price, save_tax_assumptions
from src.supply.financial_scenario import PriceConversion, TaxAssumptions
from src.ui.market_economics import LABELS

PRICE_BASES = {
    "UNKNOWN": "Unspecified — choose a basis",
    "VAT_INCLUSIVE": "Selling price includes output VAT",
    "VAT_EXCLUSIVE": "Selling price excludes output VAT",
    "NO_VAT": "Explicit scenario: no output VAT charged",
}
FIELD_LABELS = {
    **LABELS,
    "selling_price": "Selling price per unit (USD)",
    "estimated_ad_cost_per_order": "Ad cost per order (USD)",
    "price_basis": "Selling-price VAT basis",
    "sales_vat_percent": "Output VAT assumption (%)",
    "import_vat_per_unit": "Import VAT per unit (USD)",
    "import_vat_recoverable_percent": "Recoverable import VAT assumption (%)",
}
HELP = {
    "selling_price": "Per unit. Declare whether this price includes output VAT in the tax form.",
    "unit_product_cost": "Per unit in USD. Observed CJ costs apply only with "
    "the separate adoption button.",
    "international_shipping_per_unit": "Per unit in USD; adopting freight divides "
    "the quote total by its quantity.",
    "import_duty_per_unit": "Per unit. Enter duties separately from import VAT.",
    "customs_fee_per_unit": "Per unit. Exclude charges already included in freight or handling.",
    "packaging_per_unit": "Per unit. Blank is unknown; enter zero only as your explicit estimate.",
    "handling_per_unit": "Per unit. Exclude charges already included elsewhere.",
    "other_variable_cost_per_unit": "Per unit; exclude recoverable import VAT "
    "and costs entered elsewhere.",
    "payment_fee_percent": "Percent of the full amount charged to the customer, "
    "including output VAT.",
    "payment_fixed_fee": "USD per order, charged once regardless of units per order.",
    "return_rate_percent": "Probability that an order is returned, percent 0–100.",
    "estimated_loss_per_return": "Incremental USD loss per returned order: net refund, "
    "nonrecoverable fees, return freight and recovery value. Exclude costs already "
    "charged in normal order economics.",
    "estimated_ad_cost_per_order": "USD per order, charged once regardless of units per order.",
}


def blocked_results(missing):
    landed = set(LANDED_COST_FIELDS) | {"import_vat_per_unit", "import_vat_recoverable_percent"}
    revenue = {"selling_price", "price_basis", "sales_vat_percent"}
    cpa = (
        landed
        | revenue
        | {
            "payment_fee_percent",
            "payment_fixed_fee",
            "return_rate_percent",
            "estimated_loss_per_return",
        }
    )
    return {
        label: [FIELD_LABELS.get(f, f).replace("V3", "V4") for f in missing if f in fields]
        for label, fields in {
            "Landed cost / unit": landed,
            "Break-even CPA / order": cpa,
            "Net profit / order": cpa | {"estimated_ad_cost_per_order"},
        }.items()
    }


def render_tax_and_fx(product, extension, snapshot, saved=True):
    tax = snapshot.tax_assumptions
    st.markdown("**Tax assumptions · explicitly declared scenario**")
    st.caption(
        "No tax treatment or rate is inferred from Sweden or your business. "
        "Use your applicable assumptions. Import duty and import VAT are separate. "
        "Only unrecoverable import VAT contributes to landed cost; recoverable VAT "
        "may still require cash funding. These calculations do not determine tax liability."
    )

    def shown(value):
        return value if value is not None else "Unknown"

    st.write(
        f"Saved price basis: {PRICE_BASES[tax.price_basis]} · "
        f"Output VAT: {shown(tax.sales_vat_percent)}% · "
        f"Import VAT / unit: USD {shown(tax.import_vat_per_unit)} · "
        f"Recoverable: {shown(tax.import_vat_recoverable_percent)}%"
    )
    owner = (
        (product.id, snapshot.revision, snapshot.updated_at.isoformat())
        if saved
        else (product.id, "unsaved")
    )
    if st.session_state.get("_v4_tax_owner") != owner:
        for field, value in tax.model_dump().items():
            st.session_state[f"v4_tax_{product.id}_{field}"] = value
        st.session_state["_v4_tax_owner"] = owner
    with st.form(f"v4_tax_form_{product.id}"):
        basis = st.selectbox(
            "Selling-price VAT basis",
            list(PRICE_BASES),
            format_func=PRICE_BASES.get,
            key=f"v4_tax_{product.id}_price_basis",
        )
        rate = st.number_input(
            "Output VAT assumption (%)",
            min_value=0.0,
            max_value=100.0,
            value=None,
            key=f"v4_tax_{product.id}_sales_vat_percent",
        )
        vat = st.number_input(
            "Import VAT per unit (USD)",
            min_value=0.0,
            max_value=1_000_000.0,
            value=None,
            key=f"v4_tax_{product.id}_import_vat_per_unit",
        )
        recovery = st.number_input(
            "Recoverable import VAT assumption (%)",
            min_value=0.0,
            max_value=100.0,
            value=None,
            key=f"v4_tax_{product.id}_import_vat_recoverable_percent",
            help="Required for positive import VAT; 0 means none recoverable, "
            "100 means all recoverable. No recovery assumption is needed "
            "when import VAT is explicitly zero.",
        )
        save = st.form_submit_button("Save V4 tax assumptions")
    if save:
        try:
            new = save_tax_assumptions(
                snapshot,
                TaxAssumptions(
                    price_basis=basis,
                    sales_vat_percent=rate,
                    import_vat_per_unit=vat,
                    import_vat_recoverable_percent=recovery,
                ),
            )
            extension.save_financial(product.id, new)
        except ValidationError:
            st.error("Use finite nonnegative amounts and percentages 0–100.")
        else:
            st.rerun()
    with st.expander("Convert a customer price to USD · explicit manual FX"):
        st.caption(
            "The cost ledger remains USD. Enter USD directly above, or record an explicit "
            "rate here. No FX service is called. Rate is USD for one source-currency unit. "
            "Changing the USD selling price later removes the old conversion link."
        )
        if snapshot.price_conversion:
            st.json(snapshot.price_conversion.model_dump(mode="json"))
        with st.form(f"v4_fx_form_{product.id}"):
            price = st.number_input(
                "Customer price per unit in source currency", min_value=0.01, value=None
            )
            currency = st.selectbox("Customer price currency", ["SEK", "EUR", "GBP"])
            fx = st.number_input(
                "USD per source-currency unit", min_value=0.000001, value=None, format="%.6f"
            )
            day = st.date_input("Exchange-rate date", value=date.today(), max_value=date.today())
            source = st.text_input(
                "Public rate source / explicit estimate",
                max_chars=200,
                help="Record a public source or label your estimate; never enter credentials.",
            )
            convert = st.form_submit_button("Save converted USD selling price")
        if convert:
            try:
                conversion = PriceConversion(
                    customer_price=price,
                    currency=currency,
                    usd_per_currency=fx,
                    rate_date=day,
                    source=source,
                )
                extension.save_financial(product.id, save_customer_price(snapshot, conversion))
            except (ValidationError, ValueError):
                st.error(
                    "Enter a positive price and exchange rate, a date "
                    "and a public source or estimate."
                )
            else:
                st.rerun()
