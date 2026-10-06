"""Actual request accounting for one explicit research run; no estimated dollar costs."""

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field

from src.research.models import ResearchModel, utc_now


class ProviderAttempt(ResearchModel):
    stage: str
    provider: str
    status: Literal["SUCCESS", "PARTIAL", "UNAVAILABLE", "FAILED", "CACHED", "DISABLED"]
    collected_at: datetime = Field(default_factory=utc_now)
    notice: str = ""
    retained: bool = False


class RunTelemetry(ResearchModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    model: str = ""
    openai_model_requests: int = Field(default=0, ge=0)
    web_search_calls: int | None = Field(default=0, ge=0)
    page_fetch_count: int = Field(default=0, ge=0)
    page_request_count: int = Field(default=0, ge=0)
    demand_requests: int = Field(default=0, ge=0)
    providers_used: list[str] = Field(default_factory=list)
    cache_hits: list[str] = Field(default_factory=list)
    stages: list[ProviderAttempt] = Field(default_factory=list)

    def record(self, event: str, count: int = 1) -> None:
        if event == "openai_request":
            self.openai_model_requests += count
            if "OpenAI Responses" not in self.providers_used:
                self.providers_used.append("OpenAI Responses")
        elif event == "web_search":
            if self.web_search_calls is not None:
                self.web_search_calls += count
        elif event == "web_search_unknown":
            self.web_search_calls = None
