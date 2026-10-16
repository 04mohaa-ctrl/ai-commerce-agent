"""Read .env without modifying process environment or exposing credentials."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def offline_mode() -> bool:
    return os.environ.get("COMMERCE_OFFLINE", "").strip() == "1"


def local_binding_allowed(address: str) -> bool:
    return address in {"127.0.0.1", "localhost", "::1"}


def configure_provider_environment(env_path: Path | None = None) -> None:
    """Startup only: make optional dotenv credentials available to provider adapters.

    Existing values, including explicitly empty values, always take precedence.
    Do not load unrelated dotenv variables or emit credentials.
    """
    if offline_mode():
        return
    values = dotenv_values(env_path or PROJECT_ROOT / ".env")
    for name in ("CJ_API_KEY", "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD"):
        if name not in os.environ and values.get(name) is not None:
            os.environ[name] = values[name]


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    model: str = "gpt-4o-mini"
    database_path: Path = PROJECT_ROOT / "data" / "commerce.db"
    research_model: str = "gpt-4.1-mini"


def load_settings(env_path: Path | None = None) -> Settings:
    values = dotenv_values(env_path or PROJECT_ROOT / ".env")

    def value(name: str, default: str) -> str:
        return (os.environ.get(name, values.get(name) or default) or "").strip()

    path = Path(value("DATABASE_PATH", "data/commerce.db") or "data/commerce.db").expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return Settings(
        api_key="" if offline_mode() else value("OPENAI_API_KEY", ""),
        model=value("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
        database_path=path.resolve(),
        research_model=value("OPENAI_RESEARCH_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini",
    )
