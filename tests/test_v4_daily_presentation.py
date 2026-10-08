"""Read-only presentation must preserve exact evidence and honest missingness."""

from datetime import timedelta

from tests.test_supply_economics import NOW, selection, updated_selection


def test_saved_shipping_method_restored_and_stale_success_visible():
    from src.ui.supplier_shipping import quote_cohort, saved_method, shipping_state

    chosen = selection()
    other = updated_selection(chosen, "quote", method="other")
    assert saved_method([other.offer, chosen.offer], chosen, None) == chosen.offer.id
    assert saved_method([other.offer, chosen.offer], chosen, other.offer.id) == other.offer.id
    stage = {"status": "SUCCESS", "shipping_state": "SUCCESS"}
    assert shipping_state(stage, [chosen.offer], NOW) == "SUCCESS"
    assert shipping_state(stage, [chosen.offer], NOW + timedelta(hours=7)) == "STALE"
    assert shipping_state({"status": "FAILED"}, [chosen.offer], NOW) == "FAILED"
    assert quote_cohort([other.offer, chosen.offer], chosen) == [other.offer, chosen.offer]
    changed = updated_selection(chosen, "candidate", observed_at=NOW + timedelta(seconds=1))
    assert quote_cohort([changed.offer], chosen) == []


def test_catalog_displays_one_offer_per_variant_and_exact_stock_with_saved_method():
    from src.ui.supplier_shipping import catalog_offers

    chosen = selection()
    other = updated_selection(chosen, "quote", method="other")
    assert catalog_offers([other.offer, chosen.offer], chosen) == [chosen.offer]
    assert catalog_offers([other.offer, chosen.offer], None) == [other.offer]
    another = chosen.offer.model_copy(
        update={
            "stock": chosen.offer.stock.model_copy(update={"storage_id": "s2"}),
            "quote": chosen.offer.quote.model_copy(update={"storage_id": "s2"}),
        }
    )
    assert catalog_offers([other.offer, chosen.offer, another], chosen) == [chosen.offer, another]


def test_missing_inputs_explain_result_dependencies():
    from src.supply.economics import FinancialSnapshot, calculate_financial
    from src.ui.supplier_financial import blocked_results

    result = calculate_financial(FinancialSnapshot(), now=NOW)
    blocked = blocked_results(result.missing_inputs)
    assert "Import VAT per unit (USD)" in blocked["Landed cost / unit"]
    assert "Selling-price VAT basis" in blocked["Net profit / order"]
    assert "Ad cost per order (USD)" not in blocked["Break-even CPA / order"]


def test_comparison_export_uses_current_v4_and_does_not_write_or_dispatch(tmp_path, monkeypatch):
    import httpx

    from src.supply.comparison import comparison_document
    from src.supply.economics import FinancialSnapshot
    from tests.test_supply_workflow import seed

    product, ext, _ = seed(tmp_path / "export.db")
    ext.save_financial(product.id, FinancialSnapshot())
    before = ext.path.read_bytes()
    monkeypatch.setattr(
        httpx.Client, "send", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))
    )
    doc = comparison_document(ext.repository.list_saved(), ext.repository, now=NOW)
    row = doc["products"][0]
    assert row["product"]["id"] == product.id
    assert row["financial"]["calculation"]["economics"]["estimated_net_profit"] is None
    assert row["financial"]["snapshot"]["tax_assumptions"]["price_basis"] == "UNKNOWN"
    assert row["selection"] is None
    assert row["supply_score"]["recommendation"] == "INSUFFICIENT EVIDENCE"
    assert row["requirements"]["color"] is None
    assert row["supplier_observations"]["offers"][0]["stock"]["cj_quantity"] == 0
    assert ext.path.read_bytes() == before


def test_tax_fx_forms_save_exact_product_and_survive_new_session(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from tests.test_supply_requirements import button
    from tests.test_supply_workflow import APP, seed

    product, ext, _ = seed(tmp_path / "forms.db")
    monkeypatch.setenv("DATABASE_PATH", str(ext.path))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio("nav").set_value("Saved Products").run()
    assert not app.exception
    assert app.selectbox(f"v4_tax_{product.id}_price_basis").value == "UNKNOWN"
    app.selectbox(f"v4_tax_{product.id}_price_basis").set_value("VAT_INCLUSIVE")
    app.number_input(f"v4_tax_{product.id}_sales_vat_percent").set_value(25)
    app.number_input(f"v4_tax_{product.id}_import_vat_per_unit").set_value(0)
    button(app, "Save V4 tax assumptions").click().run()
    assert not app.exception
    snapshot = ext.get_financial(product.id)
    assert snapshot.tax_assumptions.price_basis == "VAT_INCLUSIVE"
    assert snapshot.tax_assumptions.import_vat_per_unit == 0
    reopened = AppTest.from_file(str(APP), default_timeout=30).run()
    reopened.sidebar.radio("nav").set_value("Saved Products").run()
    assert not reopened.exception
    assert reopened.number_input(f"v4_tax_{product.id}_sales_vat_percent").value == 25
    assert reopened.number_input(f"v4_tax_{product.id}_import_vat_per_unit").value == 0
