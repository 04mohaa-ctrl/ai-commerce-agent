"""Actual Streamlit workflow, isolated DB and strict offline boundary."""

from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from src.database.database import ProductRepository
from tests.test_v5_comparison import saved

APP = Path(__file__).resolve().parents[1] / "app.py"


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_discovery_save_compare_queries_restart_no_network(tmp_path, monkeypatch):
    path = tmp_path / "ui.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.setenv("COMMERCE_OFFLINE", "1")
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live request")),
    )
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio("nav").set_value("Discover").run()
    assert not app.exception
    button(app, "Load synthetic discovery examples (offline)").click().run()
    assert len([b for b in app.button if b.label == "Save candidate"]) == 3
    for _ in range(3):
        next(b for b in app.button if b.label == "Save candidate" and not b.disabled).click().run()
    assert len(ProductRepository(path).list_saved()) == 3
    app.sidebar.radio("nav").set_value("Compare").run()
    app.text_input("v5_group_name").set_value("Acceptance shortlist")
    app.multiselect("v5_group_members").set_value(
        [r.product.id for r in ProductRepository(path).list_saved()]
    )
    button(app, "Save comparison group").click().run()
    assert not app.exception
    assert any("incomplete" in w.value for w in app.warning)
    app.sidebar.radio("nav").set_value("Candidates").run()
    assert not app.exception
    next(t for t in app.text_area if t.label.startswith("Chosen additional queries")).set_value(
        "sv: laptopställ\nen: laptop support stand"
    )
    button(app, "Save reviewed query plan").click().run()
    assert any("reviewed" in s.value for s in app.success)
    fresh = AppTest.from_file(str(APP), default_timeout=30).run()
    fresh.sidebar.radio("nav").set_value("Compare").run()
    assert fresh.selectbox("v5_saved_group").value == "Acceptance shortlist"
    fresh.sidebar.radio("nav").set_value("Candidates").run()
    fresh.sidebar.radio("nav").set_value("Compare").run()
    assert fresh.text_input("v5_group_name").value == "Acceptance shortlist"
    assert len(fresh.multiselect("v5_group_members").value) == 3
    assert not fresh.exception


def test_group_missing_member_explained(tmp_path, monkeypatch):
    from src.discovery.comparison import ComparisonGroup, save_group

    repo = ProductRepository(tmp_path / "missing.db")
    rows = saved(repo)
    save_group(repo, ComparisonGroup(name="Group", product_ids=[r.product.id for r in rows]))
    repo.remove_saved(rows[0].product.id)
    monkeypatch.setenv("DATABASE_PATH", str(repo.path))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio("nav").set_value("Compare").run()
    assert any("no longer saved" in w.value for w in app.warning)
    assert not app.exception


def test_switching_groups_loads_correct_members_and_notes(tmp_path, monkeypatch):
    from src.discovery.comparison import ComparisonGroup, save_group

    repo = ProductRepository(tmp_path / "switch.db")
    rows = saved(repo, count=5)
    for name, members, note in [
        ("Alpha", rows[:3], "First assumptions"),
        ("Beta", rows[2:], "Second assumptions"),
    ]:
        save_group(
            repo,
            ComparisonGroup(name=name, product_ids=[r.product.id for r in members], notes=note),
        )
    monkeypatch.setenv("DATABASE_PATH", str(repo.path))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio("nav").set_value("Compare").run()
    app.selectbox("v5_saved_group").set_value("Alpha").run()
    assert app.text_input("v5_group_name").value == "Alpha"
    app.selectbox("v5_saved_group").set_value("Beta").run()
    assert app.text_input("v5_group_name").value == "Beta"
    assert app.multiselect("v5_group_members").value == [r.product.id for r in rows[2:]]
    assert (
        next(t for t in app.text_area if t.label.startswith("Decision reasons")).value
        == "Second assumptions"
    )
    app.sidebar.radio("nav").set_value("Candidates").run()
    app.sidebar.radio("nav").set_value("Compare").run()
    selected = app.selectbox("v5_saved_group").value
    expected = rows[:3] if selected == "Alpha" else rows[2:]
    assert app.text_input("v5_group_name").value == selected
    assert app.multiselect("v5_group_members").value == [r.product.id for r in expected]
    assert next(t for t in app.text_area if t.label.startswith("Decision reasons")).value == (
        "First assumptions" if selected == "Alpha" else "Second assumptions"
    )


def test_candidate_query_editor_is_scoped_to_product(tmp_path, monkeypatch):
    repo = ProductRepository(tmp_path / "query-scope.db")
    rows = saved(repo)
    monkeypatch.setenv("DATABASE_PATH", str(repo.path))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio("nav").set_value("Candidates").run()
    app.selectbox("v5_candidate").set_value(rows[0].product.id).run()
    next(t for t in app.text_area if t.label.startswith("Chosen additional")).set_value(
        "sv: laptopställ"
    )
    button(app, "Save reviewed query plan").click().run()
    app.selectbox("v5_candidate").set_value(rows[1].product.id).run()
    assert next(t for t in app.text_area if t.label.startswith("Chosen additional")).value == ""
