from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(autouse=True)
def local_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "v3-ui.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)


def start():
    return AppTest.from_file(str(APP), default_timeout=30).run()


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_new_product_v3_sections_keyless_and_unknown_inputs():
    app = start()
    app.sidebar.radio("nav").set_value("Research").run()
    app.text_input("research_query").set_value("Electric heated lunch box")
    button(app, "Find / Analyze Products").click().run()
    button(app, "Research this product").click().run()
    assert not app.exception
    assert "Market Intelligence" in [t.label for t in app.tabs]
    assert any("Measured demand data unavailable" in item.value for item in app.info)
    assert app.number_input("market_econ_import_duty_per_unit").value is None
    assert app.number_input("market_econ_payment_fixed_fee").value is None
    assert any("No external requests" in item.value for item in app.caption)


def test_manual_v3_economics_persists_and_legacy_outputs_are_preserved():
    app = start()
    values = {
        "selling_price": 40,
        "unit_product_cost": 10,
        "international_shipping_per_unit": 5,
        "import_duty_per_unit": 0,
        "customs_fee_per_unit": 0,
        "packaging_per_unit": 0,
        "handling_per_unit": 0,
        "other_variable_cost_per_unit": 0,
        "payment_fee_percent": 3,
        "payment_fixed_fee": 0.3,
        "return_rate_percent": 8,
        "estimated_loss_per_return": 12,
        "estimated_ad_cost_per_order": 8,
    }
    for field, value in values.items():
        app.number_input("market_econ_" + field).set_value(value)
    button(app, "Save V3 economics assumptions").click().run()
    assert not app.exception
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["V3 estimated net profit"] == "USD 14.54"
    assert metrics["V3 break-even CPA"] == "USD 22.54"
    fresh = start()
    assert fresh.number_input("market_econ_return_rate_percent").value == 8
    assert fresh.number_input("market_econ_payment_fixed_fee").value == 0.3
    assert fresh.number_input("econ_shipping_cost").value is None


def test_supported_page_wording_and_run_telemetry_survive_navigation(monkeypatch):
    from src.research.providers.page_verification import PageVerificationProvider
    from src.research.providers.web_research import WebResearchProvider
    from tests.research_fixtures import report_fixture
    from tests.test_market_pipeline import FixturePages

    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret")
    monkeypatch.setattr(WebResearchProvider, "research", lambda *args, **kwargs: report_fixture())
    pages = FixturePages()
    monkeypatch.setattr(
        PageVerificationProvider,
        "verify",
        lambda self, source, claims: pages.verify(source, claims),
    )
    app = start()
    app.sidebar.radio("nav").set_value("Settings").run()
    app.toggle("demo_mode").set_value(False).run()
    app.sidebar.radio("nav").set_value("Dashboard").run()
    button(app, "Research product").click().run()
    assert not app.exception
    markdown = " ".join(x.value for x in app.markdown)
    assert "Supported on source page" in markdown
    assert "objective truth" in " ".join(x.value for x in app.caption)
    assert any("OpenAI model requests" in x.value for x in app.markdown)
    before = pages.source_fetch_count
    app.sidebar.radio("nav").set_value("Saved Products").run()
    app.sidebar.radio("nav").set_value("Dashboard").run()
    assert pages.source_fetch_count == before
    assert not app.exception
