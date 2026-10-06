from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(autouse=True)
def local_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "")


def start():
    return AppTest.from_file(str(APP), default_timeout=20).run()


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_dashboard_shows_demo_scores_and_complete_product_details():
    app = start()
    assert not app.exception
    assert app.metric[0].value == "12"
    assert len(app.dataframe[0].value) == 12
    assert "Overall AI Score" in app.dataframe[0].value.columns
    assert any("Product details" in s.value for s in app.subheader)
    assert any("Verified data" in s.value for s in app.markdown)
    assert any("AI judgement" in s.value for s in app.markdown)


def test_research_filters_products_and_empty_search_is_recoverable():
    app = start()
    app.sidebar.radio("nav").set_value("Research").run()
    app.text_input("research_query").set_value("pet accessories")
    button(app, "Find / Analyze Products").click().run()
    assert not app.exception
    table = app.dataframe[0].value
    assert len(table) == 2
    assert set(table["Category"]) == {"Pet products"}
    app.text_input("research_query").set_value("unobtainium")
    button(app, "Find / Analyze Products").click().run()
    assert not app.exception
    assert any("No products match" in x.value for x in app.info)
    app.text_input("research_query").set_value("")
    button(app, "Find / Analyze Products").click().run()
    assert len(app.dataframe[0].value) == 12


def test_save_duplicate_fresh_session_persistence_and_remove():
    app = start()
    button(app, "Save product").click().run()
    assert not app.exception
    assert app.metric[1].value == "1"
    button(app, "Update saved analysis").click().run()
    assert app.metric[1].value == "1"
    fresh = start()
    fresh.sidebar.radio("nav").set_value("Saved Products").run()
    assert not fresh.exception
    assert len(fresh.dataframe[0].value) == 1
    button(fresh, "Remove saved product").click().run()
    assert not fresh.exception
    again = start()
    again.sidebar.radio("nav").set_value("Saved Products").run()
    assert again.metric[1].value == "0"
    assert any("No saved products" in x.value for x in again.info)


def test_manual_entry_persists_and_invalid_entry_does_not_crash():
    app = start()
    app.sidebar.radio("nav").set_value("Research").run()
    button(app, "Add and analyze product").click().run()
    assert not app.exception
    assert app.error
    app.text_input("manual_name").set_value("Test travel pouch")
    app.selectbox("manual_category").set_value("Travel")
    app.number_input("manual_cost").set_value(4)
    app.number_input("manual_price").set_value(19)
    button(app, "Add and analyze product").click().run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 1
    assert app.dataframe[0].value.iloc[0]["Product name"] == "Test travel pouch"
    fresh = start()
    fresh.sidebar.radio("nav").set_value("Research").run()
    fresh.text_input("research_query").set_value("Test travel pouch")
    button(fresh, "Find / Analyze Products").click().run()
    assert len(fresh.dataframe[0].value) == 1


def test_settings_without_api_key_keeps_demo_working():
    app = start()
    app.sidebar.radio("nav").set_value("Settings").run()
    assert not app.exception
    assert app.toggle("demo_mode").value is True
    assert app.toggle("demo_mode").disabled is True
    assert any("not configured" in x.value for x in app.info)


def test_live_mode_selection_survives_navigation_and_reruns(monkeypatch):
    from src.agents.product_research_agent import ProductResearchAgent
    from src.schemas.product import Assessment

    def offline_sdk_boundary(self, client, product):
        return Assessment(demand=8, competition=4, trend=7, marketing=9)

    monkeypatch.setattr(ProductResearchAgent, "_request", offline_sdk_boundary)
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    app = start()
    app.sidebar.radio("nav").set_value("Settings").run()
    app.toggle("demo_mode").set_value(False).run()
    app.sidebar.radio("nav").set_value("Research").run()
    app.run()
    assert any(x.value == "OpenAI mode" for x in app.sidebar.markdown)
    app.text_input("research_query").set_value("pet accessories")
    button(app, "Find / Analyze Products").click().run()
    assert not app.exception
    assert set(app.dataframe[0].value["Analysis mode"]) == {"OpenAI"}
    app.sidebar.radio("nav").set_value("Settings").run()
    assert app.toggle("demo_mode").value is False


def test_database_startup_failure_is_user_facing(tmp_path, monkeypatch):
    bad_path = tmp_path / "invalid.db"
    bad_path.write_text("not sqlite")
    monkeypatch.setenv("DATABASE_PATH", str(bad_path))
    app = start()
    assert not app.exception
    assert app.error
