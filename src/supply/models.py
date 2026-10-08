"""Sanitized supplier snapshots with immutable, content-bound observation identities."""

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from src.research.models import canonical_url, utc_now


def _plain_identity(value):
    if any(ord(char) < 32 for char in value):
        raise ValueError("Supplier identities cannot contain control characters.")
    return value


Identity = Annotated[
    str, Field(strict=True, min_length=1, max_length=300), AfterValidator(_plain_identity)
]
Currency = Annotated[str, Field(strict=True, pattern=r"^[A-Z]{3}$")]
Country = Annotated[str, Field(strict=True, pattern=r"^[A-Z]{2}$")]
Count = Annotated[int, Field(strict=True, ge=0)]
PositiveCount = Annotated[int, Field(strict=True, gt=0)]
Money = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
OutcomeStatus = Literal[
    "SUCCESS",
    "SUCCESS_EMPTY",
    "UNAVAILABLE",
    "UNSUPPORTED",
    "RATE_LIMITED",
    "BUDGET_EXHAUSTED",
    "FAILED",
]
LocalLimit = Literal["LOCAL_REQUEST_BUDGET", "LOCAL_TIME_BUDGET"]
LimitSource = Literal[
    "LOCAL_REQUEST_BUDGET",
    "LOCAL_TIME_BUDGET",
    "LOCAL_ACTION_BUDGET",
    "PROVIDER_RATE_LIMIT",
    "PROVIDER_QUOTA_LIMIT",
]
MatchOutcome = Literal["MATCH", "LIKELY_MATCH", "AMBIGUOUS", "NO_MATCH"]


def normalize_limit_stage(stage):
    """Read-only interpretation of known pre-fix CJ notices; never infer an unknown origin."""
    stage = dict(stage)
    if (
        stage.get("provider") != "cj"
        or stage.get("status") != "RATE_LIMITED"
        or stage.get("limit_source")
    ):
        return stage
    notice = stage.get("notice", "")
    local = {
        "CJ action research budget exhausted.": "LOCAL_ACTION_BUDGET",
        "CJ action deadline reached before dispatch.": "LOCAL_TIME_BUDGET",
        "CJ action deadline reached.": "LOCAL_TIME_BUDGET",
    }
    if notice in local:
        stage.update(status="BUDGET_EXHAUSTED", limit_source=local[notice])
    elif notice == "CJ rate limit reached.":
        stage["limit_source"] = "PROVIDER_RATE_LIMIT"
    elif notice in {f"CJ rate or quota limit ({code})." for code in (1600200, 1600201, 16900500)}:
        stage["limit_source"] = "PROVIDER_QUOTA_LIMIT"
    return stage


class FrozenDict(dict):
    """Keep validated attribute mappings immutable without changing JSON representation."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("Observation attributes are immutable.")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable

    def __deepcopy__(self, memo):
        return FrozenDict(self)


class FrozenList(list):
    """Keep identity explanations immutable after observation construction."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("Observation explanations are immutable.")

    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = _immutable
    reverse = sort = __iadd__ = __imul__ = _immutable

    def __deepcopy__(self, memo):
        return FrozenList(self)


def _safe_data(value):
    """Reject secret-bearing generic payloads rather than silently persisting them."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized == "token" or any(
                word in normalized
                for word in (
                    "apikey",
                    "accesstoken",
                    "refreshtoken",
                    "authorization",
                    "password",
                    "credential",
                    "secret",
                    "cookie",
                )
            ):
                raise ValueError("Sensitive provider fields cannot be serialized.")
            _safe_data(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _safe_data(item)
    elif isinstance(value, float) and (value != value or value in (float("inf"), -float("inf"))):
        raise ValueError("Nonfinite provider data cannot be serialized.")
    return value


class SupplyModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
        validate_assignment=True,
        validate_default=True,
    )

    @field_validator(
        "observed_at",
        "expires_at",
        "selected_at",
        "started_at",
        "completed_at",
        "researched_at",
        check_fields=False,
    )
    @classmethod
    def utc_timestamps(cls, value):
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Supplier timestamps require a timezone.")
        return value.astimezone(timezone.utc)

    @field_validator(
        "unit_price",
        "total_cost",
        "taxes_fee",
        "clearance_operation_fee",
        "total_postage_fee",
        "weight_g",
        check_fields=False,
        mode="before",
    )
    @classmethod
    def decimal_values(cls, value):
        if isinstance(value, bool):
            raise ValueError("Boolean is not a measured numeric value.")
        return value

    @field_validator("records", "stages", check_fields=False)
    @classmethod
    def sanitized_records(cls, value):
        return _safe_data(value)


class SupplierRequirements(SupplyModel):
    """User target preferences, separate from immutable supplier observations."""

    color: str | None = Field(default=None, max_length=40)

    @field_validator("color", mode="before")
    @classmethod
    def plain_color(cls, value):
        if value is None or value == "":
            return None
        if not isinstance(value, str) or any(ord(c) < 32 for c in value) or ";" in value:
            raise ValueError("Enter a plain color name.")
        return " ".join(value.casefold().split()) or None

    @property
    def attributes(self):
        return {"color": self.color} if self.color else {}


class Destination(SupplyModel):
    model_config = ConfigDict(frozen=True)
    country: Country = "US"
    quantity: PositiveCount = 1
    max_delivery_days: PositiveCount = 14
    postal_code: str = Field(default="", max_length=20)
    region: str = Field(default="", max_length=80)

    @field_validator("postal_code", "region", mode="before")
    @classmethod
    def no_control_characters(cls, value):
        if not isinstance(value, str) or any(ord(char) < 32 for char in value):
            raise ValueError("Destination fields require plain text.")
        return value


class Observation(SupplyModel):
    model_config = ConfigDict(frozen=True)
    id: str = ""

    @model_validator(mode="after")
    def bind_identity(self):
        payload = self.model_dump(mode="json", exclude={"id"})
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        identity = hashlib.sha256((type(self).__name__ + "\0" + serialized).encode()).hexdigest()
        if self.id and self.id != identity:
            raise ValueError("Observation ID does not match its immutable content.")
        object.__setattr__(self, "id", identity)
        return self

    def model_copy(self, *, update=None, deep=False):
        """Updated snapshots are new validated observations, never stale-ID aliases."""
        payload = self.model_dump(mode="python", exclude={"id"})
        payload.update(update or {})
        return type(self).model_validate(payload)


class SupplierProductCandidate(Observation):
    provider: Identity
    product_id: Identity
    name: Identity
    source_url: str | None = None
    category: str | None = None
    brand: str | None = None
    image_url: str | None = None
    observed_at: datetime = Field(default_factory=utc_now)

    @field_validator("source_url", "image_url")
    @classmethod
    def safe_link(cls, value):
        if value is None:
            return None
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() != "https" or any(ord(char) < 32 for char in value):
            raise ValueError("Supplier links require public HTTPS.")
        _safe_data(dict(parse_qsl(parsed.query, keep_blank_values=True)))
        return canonical_url(value)


class SupplierVariant(Observation):
    provider: Identity
    product_id: Identity
    variant_id: Identity
    name: Identity
    sku: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    unit_price: Money | None = None
    currency: Currency | None = None
    weight_g: Annotated[Decimal, Field(gt=0, allow_inf_nan=False)] | None = None
    dimensions_mm: tuple[Money, Money, Money] | None = None
    observed_at: datetime = Field(default_factory=utc_now)

    @field_validator("attributes")
    @classmethod
    def freeze_attributes(cls, value):
        return FrozenDict(_safe_data(value))

    @field_validator("dimensions_mm", mode="before")
    @classmethod
    def positive_dimensions(cls, value):
        if value is not None and isinstance(value, (list, tuple)):
            if any(isinstance(item, bool) for item in value):
                raise ValueError("Boolean is not a measured parcel dimension.")
        return value

    @field_validator("dimensions_mm")
    @classmethod
    def nonzero_dimensions(cls, value):
        if value is not None and any(item <= 0 for item in value):
            raise ValueError("Parcel dimensions must be positive measured lengths.")
        return value

    @model_validator(mode="after")
    def price_currency(self):
        if self.unit_price is not None and self.currency is None:
            raise ValueError("Known unit price requires its native currency.")
        return self


class StockObservation(Observation):
    provider: Identity
    product_id: Identity
    variant_id: Identity
    warehouse_id: Identity | None = None
    storage_id: Identity | None = None
    country: Country | None = None
    quantity: Count | None = None
    cj_quantity: Count | None = None
    factory_quantity: Count | None = None
    observed_at: datetime = Field(default_factory=utc_now)


class ShippingQuote(Observation):
    provider: Identity
    product_id: Identity
    variant_id: Identity
    variant_snapshot: Identity | None = None
    warehouse_id: Identity | None = None
    storage_id: Identity | None = None
    origin: Country
    destination: Destination
    quantity: PositiveCount
    method: Identity
    total_cost: Money | None = None
    currency: Currency | None = None
    taxes_fee: Money | None = None
    clearance_operation_fee: Money | None = None
    total_postage_fee: Money | None = None
    delivery_min_days: Count | None = None
    delivery_max_days: Count | None = None
    tracking: Annotated[bool, Field(strict=True)] | None = None
    observed_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def quote_semantics(self):
        if self.quantity != self.destination.quantity:
            raise ValueError("Quote and destination quantities must agree.")
        if (
            any(
                value is not None
                for value in (
                    self.total_cost,
                    self.taxes_fee,
                    self.clearance_operation_fee,
                    self.total_postage_fee,
                )
            )
            and self.currency is None
        ):
            raise ValueError("Known quote money requires its native currency.")
        if self.expires_at is not None and self.expires_at <= self.observed_at:
            raise ValueError("Quote expiry must follow observation time.")
        if self.delivery_min_days is not None and self.delivery_max_days is not None:
            if self.delivery_min_days > self.delivery_max_days:
                raise ValueError("Delivery estimate is reversed.")
        return self


class SupplierMatch(SupplyModel):
    model_config = ConfigDict(frozen=True)
    outcome: MatchOutcome
    reasons: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    missing_attributes: list[str] = Field(default_factory=list)

    @field_validator("reasons", "contradictions", "missing_attributes")
    @classmethod
    def freeze_explanations(cls, value):
        return FrozenList(value)


class SupplierOffer(Observation):
    candidate: SupplierProductCandidate
    variant: SupplierVariant
    stock: StockObservation | None = None
    quote: ShippingQuote | None = None
    match: SupplierMatch

    @model_validator(mode="after")
    def consistent_identity(self):
        for record in (self.variant, self.stock, self.quote):
            if record is None:
                continue
            if (record.provider, record.product_id) != (
                self.candidate.provider,
                self.candidate.product_id,
            ):
                raise ValueError("Offer observations refer to different supplier products.")
            if record.variant_id != self.variant.variant_id:
                raise ValueError("Offer observations refer to different variants.")
        if self.stock is not None and self.quote is not None:
            for field in ("warehouse_id", "storage_id"):
                if getattr(self.stock, field) != getattr(self.quote, field):
                    raise ValueError("Stock and freight warehouse identities disagree.")
            if self.stock.country is not None and self.stock.country != self.quote.origin:
                raise ValueError("Stock country and freight origin disagree.")
        return self


class SupplierSelection(Observation):
    offer: SupplierOffer
    confirmed_attributes: dict[str, str] = Field(default_factory=dict)
    selected_at: datetime = Field(default_factory=utc_now)

    @field_validator("confirmed_attributes")
    @classmethod
    def freeze_confirmation(cls, value):
        return FrozenDict(_safe_data(value))

    @model_validator(mode="after")
    def selectable(self):
        if self.offer.match.outcome == "NO_MATCH":
            raise ValueError("Contradicted supplier identity cannot be selected.")
        return self


class ProviderOutcome(SupplyModel):
    status: OutcomeStatus
    records: list[dict] = Field(default_factory=list)
    partial: Annotated[bool, Field(strict=True)] = False
    rejected: Count = 0
    notice: str = ""
    limit_source: LimitSource | None = None
    retry_blocked_by: LocalLimit | None = None
    observed_at: datetime = Field(default_factory=utc_now)
    failure_kind: (
        Literal[
            "CONFIGURATION",
            "HTTP_REJECTION",
            "PROVIDER_REJECTION",
            "TIMEOUT",
            "TRANSPORT",
            "INVALID_RESPONSE",
            "UNKNOWN",
            "LOCAL_BUDGET",
        ]
        | None
    ) = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    provider_status: int | None = None

    @model_validator(mode="after")
    def empty_semantics(self):
        if self.status == "SUCCESS_EMPTY" and (self.records or self.partial or self.rejected):
            raise ValueError("Successful empty outcome cannot contain data or parse failures.")
        return self


class ActionTelemetry(SupplyModel):
    action_id: Identity = Field(default_factory=lambda: str(uuid4()))
    action: Identity = "research"
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    requests: dict[str, Count] = Field(default_factory=dict)
    cache_hits: list[str] = Field(default_factory=list)
    retries: Count = 0
    stages: list[dict] = Field(default_factory=list)
    elapsed_seconds: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def ordered_action(self):
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("Action completion must follow its start.")
        return self


class SupplyIntelligenceReport(SupplyModel):
    schema_version: Literal[4] = 4
    product_id: Identity
    input_fingerprint: Identity
    destination: Destination = Field(default_factory=Destination)
    offers: list[SupplierOffer] = Field(default_factory=list)
    stages: list[dict] = Field(default_factory=list)
    telemetry: ActionTelemetry = Field(default_factory=ActionTelemetry)
    researched_at: datetime = Field(default_factory=utc_now)
