"""Normal startup loads only absent optional provider variables, without printing them."""

import os
import runpy
from pathlib import Path

import src.config as config

LOAD = getattr(config, "configure_provider_environment", None)


def test_provider_environment_preserves_absent_empty_and_existing_values(
    tmp_path, monkeypatch, capsys
):
    assert callable(LOAD), "Normal app launch must configure optional providers from dotenv"
    env = tmp_path / ".env"
    env.write_text(
        "CJ_API_KEY=private-cj\nDATAFORSEO_LOGIN=private-login\nDATAFORSEO_PASSWORD=private-pass\nUNRELATED_SECRET=private-other\n"
    )
    monkeypatch.delenv("CJ_API_KEY", raising=False)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "existing")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "")
    monkeypatch.delenv("UNRELATED_SECRET", raising=False)
    LOAD(env)
    assert os.getenv("CJ_API_KEY") == "private-cj"
    assert os.getenv("DATAFORSEO_LOGIN") == "existing"
    assert os.getenv("DATAFORSEO_PASSWORD") == ""
    assert "UNRELATED_SECRET" not in os.environ
    assert "private" not in capsys.readouterr().out


def test_normal_streamlit_entrypoint_configures_before_rendering(tmp_path, monkeypatch):
    assert callable(LOAD)
    env = tmp_path / ".env"
    env.write_text(
        "CJ_API_KEY=private-cj\nDATAFORSEO_LOGIN=private-login\nDATAFORSEO_PASSWORD=private-pass\n"
    )
    for key in ("CJ_API_KEY", "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config, "configure_provider_environment", lambda: LOAD(env))
    seen = []
    monkeypatch.setattr(
        "src.ui.dashboard.main",
        lambda: seen.append(
            all(os.getenv(key) for key in ("CJ_API_KEY", "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD"))
        ),
    )
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "app.py"))
    assert seen == [True]
