from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.research_fixtures import report_fixture

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(autouse=True)
def local_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "v2-ui.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "")


def start():
    return AppTest.from_file(str(APP), default_timeout=20).run()


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_initial_no_research_and_keyless_research_state():
    app = start()
    assert any("No research performed" in x.value for x in app.info)
    button(app, "Research product").click().run()
    assert not app.exception
    assert any("Insufficient evidence" in x.value for x in app.warning)
    assert any("Demo Mode" in x.value for x in app.info)
    assert any("No sources" in x.value for x in app.info)
    fresh = start()
    assert any("Insufficient evidence" in x.value for x in fresh.warning)


def test_successful_research_citations_and_effective_score_persist(monkeypatch):
    from src.research.providers.web_research import WebResearchProvider

    def external_boundary(self, product, progress=None):
        if progress:
            progress("External fixture retrieved.")
        return report_fixture()

    monkeypatch.setattr(WebResearchProvider, "research", external_boundary)
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    app = start()
    app.sidebar.radio("nav").set_value("Settings").run()
    app.toggle("demo_mode").set_value(False).run()
    app.sidebar.radio("nav").set_value("Dashboard").run()
    button(app, "Research product").click().run()
    assert not app.exception
    assert any("Research completed" in x.value for x in app.success)
    assert any("https://publisher0.com/pet-hair" in x.value for x in app.markdown)
    assert "Evidence confidence" in app.dataframe[0].value.columns
    first_score = (
        app.dataframe[0]
        .value.loc[app.dataframe[0].value["Product name"] == "Pet Hair Remover", "Overall AI Score"]
        .iloc[0]
    )
    assert first_score < 75.4  # Unknown shipping/fees/ads cannot contribute margin points.
    fresh = start()
    # An evidence score can move the product down the ranking. Select it explicitly.
    ids = fresh.selectbox("details_dashboard").options
    pet_id = next(
        r.product.id for r in fresh.session_state["results"] if r.product.name == "Pet Hair Remover"
    )
    assert "Pet Hair Remover" in ids
    fresh.selectbox("details_dashboard").set_value(pet_id).run()
    assert any("Research completed" in x.value for x in fresh.success)
    assert any("https://publisher0.com/pet-hair" in x.value for x in fresh.markdown)


def test_economics_inputs_and_known_calculations_survive_new_session():
    app = start()
    app.number_input("econ_product_cost").set_value(10)
    app.number_input("econ_selling_price").set_value(40)
    app.number_input("econ_shipping_cost").set_value(5)
    app.number_input("econ_payment_fee_percent").set_value(3)
    app.number_input("econ_estimated_ad_cost_per_order").set_value(8)
    button(app, "Save economics assumptions").click().run()
    assert not app.exception
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Estimated net profit"] == "USD 15.80"
    assert metrics["Estimated net margin"] == "39.50%"
    assert metrics["Break-even CPA"] == "USD 23.80"
    fresh = start()
    assert fresh.number_input("econ_shipping_cost").value == 5
    assert fresh.number_input("econ_payment_fee_percent").value == 3
    assert fresh.number_input("econ_estimated_ad_cost_per_order").value == 8


def test_failed_refresh_displays_failure_and_preserves_prior_citations(monkeypatch):
    from src.research.providers.base import ResearchProviderError
    from src.research.providers.web_research import WebResearchProvider

    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setattr(WebResearchProvider, "research", lambda *args, **kwargs: report_fixture())
    app = start()
    app.sidebar.radio("nav").set_value("Settings").run()
    app.toggle("demo_mode").set_value(False).run()
    app.sidebar.radio("nav").set_value("Dashboard").run()
    button(app, "Research product").click().run()
    pet_id = next(
        r.product.id for r in app.session_state["results"] if r.product.name == "Pet Hair Remover"
    )
    app.selectbox("details_dashboard").set_value(pet_id).run()

    def fail(*args, **kwargs):
        raise ResearchProviderError("Unavailable")

    monkeypatch.setattr(WebResearchProvider, "research", fail)
    button(app, "Research product").click().run()
    assert not app.exception
    assert any("Research failed" in x.value for x in app.error)
    assert any("https://publisher0.com/pet-hair" in x.value for x in app.markdown)
