"""Read .env without modifying process environment or exposing credentials."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    model: str = "gpt-4o-mini"
    database_path: Path = PROJECT_ROOT / "data" / "commerce.db"


def load_settings(env_path: Path | None = None) -> Settings:
    values = dotenv_values(env_path or PROJECT_ROOT / ".env")

    def value(name: str, default: str) -> str:
        return (os.environ.get(name, values.get(name) or default) or "").strip()

    path = Path(value("DATABASE_PATH", "data/commerce.db") or "data/commerce.db").expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return Settings(
        api_key=value("OPENAI_API_KEY", ""),
        model=value("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
        database_path=path.resolve(),
    )
