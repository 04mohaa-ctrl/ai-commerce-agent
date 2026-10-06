"""Optional native DataForSEO relative popularity; no search-volume inference."""

import os
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Protocol
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.schemas.product import Product

ENDPOINT = "https://api.dataforseo.com/v3/keywords_data/dataforseo_trends/explore/live"
UNAVAILABLE_NOTICE = "Measured demand data unavailable"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DemandObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    metric_name: str
    provider: str
    query: str
    value: float | None = Field(default=None, ge=0)
    unit: str
    period_start: date
    period_end: date
    collected_at: datetime
    source_url: str
    confidence: Literal["low", "medium", "high"] = "medium"
    notes: list[str] = Field(default_factory=list)
    location: str
    series_id: str
    missing: bool = False
    granularity: str = ""

    @field_validator("collected_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Collection time needs a timezone.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def valid_bin(self):
        if self.period_start > self.period_end:
            raise ValueError("Invalid observation period.")
        if self.value is None:
            self.missing = True
        if self.unit == "relative_popularity_index":
            if self.value is not None and self.value > 100:
                raise ValueError("Relative index is outside its scale.")
            if self.value == 0:
                self.missing = True
        return self


class DemandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    query: str
    location: str
    observations: list[DemandObservation] = Field(default_factory=list)
    status: Literal["completed", "unavailable", "failed"]
    notice: str = ""
    collected_at: datetime = Field(default_factory=utc_now)


class DemandTrendProvider(Protocol):
    name: str
    request_count: int

    def collect(self, product: Product) -> DemandResult: ...


class UnavailableDemandProvider:
    name = "unavailable"
    request_count = 0

    def collect(self, product: Product) -> DemandResult:
        return DemandResult(
            provider=self.name,
            query=product.name,
            location="United States (2840)",
            status="unavailable",
            notice=UNAVAILABLE_NOTICE,
        )


class DataForSEOTrendProvider:
    """One bounded native request, only when both process credentials are present."""

    name = "dataforseo_trends"
    endpoint = ENDPOINT

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
        location_code: int = 2840,
        location_name: str = "United States",
    ):
        self._login = os.environ.get("DATAFORSEO_LOGIN", "").strip()
        self._password = os.environ.get("DATAFORSEO_PASSWORD", "").strip()
        self.transport = transport
        self.clock = clock
        self.location_code = location_code
        self.location = f"{location_name} ({location_code})"
        self.request_count = 0

    @property
    def enabled(self) -> bool:
        return bool(self._login and self._password)

    def collect(self, product: Product) -> DemandResult:
        now = self.clock().astimezone(timezone.utc)
        base = dict(
            provider=self.name, query=product.name, location=self.location, collected_at=now
        )
        if not self.enabled:
            return DemandResult(**base, status="unavailable", notice=UNAVAILABLE_NOTICE)
        end = now.date() - timedelta(days=1)
        try:
            start = now.date().replace(year=now.year - 1)
        except ValueError:
            start = date(now.year - 1, 2, 28)
        request = {
            "keywords": [product.name],
            "location_code": self.location_code,
            "type": "web",
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
        }
        try:
            with httpx.Client(
                transport=self.transport, timeout=20, follow_redirects=False, trust_env=False
            ) as client:
                self.request_count += 1
                response = client.post(ENDPOINT, json=[request], auth=(self._login, self._password))
                response.raise_for_status()
                observations = self._parse(response.json(), request, now, start, end)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError):
            return DemandResult(
                **base,
                status="failed",
                notice="Measured demand request failed; check provider access.",
            )
        return DemandResult(
            **base,
            observations=observations,
            status="completed" if observations else "unavailable",
            notice="Provider-relative popularity, not monthly search volume. "
            "Zero means insufficient data."
            if observations
            else UNAVAILABLE_NOTICE,
        )

    def _parse(self, payload, request, now, start, end):
        if not isinstance(payload, dict) or payload.get("status_code") != 20000:
            raise ValueError("Invalid provider status")
        tasks = payload.get("tasks")
        if not isinstance(tasks, list) or len(tasks) != 1 or not isinstance(tasks[0], dict):
            raise ValueError("Invalid task")
        task = tasks[0]
        if task.get("status_code") != 20000:
            raise ValueError("Task failed")
        data = task.get("data", {})
        if not isinstance(data, dict) or any(data.get(k) != v for k, v in request.items()):
            raise ValueError("Task inputs mismatch")
        results = task.get("result")
        if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
            raise ValueError("Invalid results")
        result = results[0]
        if (
            result.get("keywords") != request["keywords"]
            or result.get("location_code") != self.location_code
        ):
            raise ValueError("Wrong query or geography")
        if result.get("type") not in {"trends", "web"}:
            raise ValueError("Wrong measurement type")
        items = result.get("items")
        if not isinstance(items, list):
            raise ValueError("Invalid graph")
        graphs = [
            item
            for item in items
            if isinstance(item, dict) and item.get("type") == "dataforseo_trends_graph"
        ]
        if len(graphs) != 1 or graphs[0].get("keywords") != request["keywords"]:
            raise ValueError("Missing matching graph")
        bins = graphs[0].get("data")
        if not isinstance(bins, list):
            raise ValueError("Invalid bins")
        identity = str(uuid4())
        observations = []
        for item in bins:
            if not isinstance(item, dict):
                raise ValueError("Invalid bin")
            first, last = date.fromisoformat(item["date_from"]), date.fromisoformat(item["date_to"])
            values = item.get("values")
            if (
                not start <= first <= last <= end
                or not isinstance(values, list)
                or len(values) != 1
                or isinstance(values[0], bool)
                or not isinstance(values[0], (int, float))
            ):
                raise ValueError("Invalid measurement")
            value = values[0]
            observations.append(
                DemandObservation(
                    metric_name="keyword_popularity",
                    provider=self.name,
                    query=request["keywords"][0],
                    value=value,
                    unit="relative_popularity_index",
                    period_start=first,
                    period_end=last,
                    collected_at=now,
                    source_url=ENDPOINT,
                    confidence="medium",
                    notes=["Provider-relative index; zero means insufficient data."],
                    location=self.location,
                    series_id=identity,
                    missing=value == 0,
                    granularity=f"{(last - first).days + 1} days",
                )
            )
        return observations
