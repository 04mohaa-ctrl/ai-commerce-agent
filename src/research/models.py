"""Source-linked observations and qualitative assessments, never LLM-set totals."""

import hashlib
import ipaddress
from datetime import datetime, timezone
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Confidence = Literal["low", "medium", "high"]
Strength = Literal["weak", "moderate", "strong", "unknown"]
ResearchStatus = Literal["completed", "insufficient", "failed"]
Text = Annotated[str, Field(min_length=1, max_length=4000)]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_url(value: str) -> str:
    """Normalize identity while retaining functional query parameters."""
    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not host
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Source must be a public HTTP(S) URL without credentials.")
    if (
        host == "localhost"
        or host.endswith((".localhost", ".local", ".internal"))
        or "." not in host
    ):
        raise ValueError("Local source URLs are not supported.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Nonpublic source URLs are not supported.")
    port = parsed.port
    netloc = host if port in (None, 80 if parsed.scheme == "http" else 443) else f"{host}:{port}"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid"}
    )
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", urlencode(query), ""))


class ResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Source(ResearchModel):
    title: Text
    url: Text
    accessed_at: datetime
    source_type: Literal["web", "retail_listing", "review", "article"] = "web"
    what_claim_it_supports: Text

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return canonical_url(value)

    @field_validator("accessed_at")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Source access time must include its timezone.")
        return value.astimezone(timezone.utc)

    @property
    def id(self) -> str:
        return hashlib.sha256(self.url.encode()).hexdigest()[:20]


class EvidenceFinding(ResearchModel):
    claim: Text
    supporting_excerpt: Text
    source_ids: list[str] = Field(min_length=1)


class ExtractedFinding(ResearchModel):
    """Untrusted model output; must be validated against actual citation contexts."""

    claim: Text
    supporting_excerpt: Text
    source_urls: list[str] = Field(min_length=1)


class QualitativeDimensions(ResearchModel):
    demand: Strength = "unknown"
    competition: Strength = "unknown"
    trend: Strength = "unknown"
    marketing: Strength = "unknown"


class WebResearchExtraction(ResearchModel):
    research_summary: Text
    dimensions: QualitativeDimensions
    demand_evidence: list[ExtractedFinding]
    competition_evidence: list[ExtractedFinding]
    trend_evidence: list[ExtractedFinding]
    marketing_angles: list[ExtractedFinding]
    common_customer_complaints: list[ExtractedFinding]
    risks: list[str]


class PriceObservation(ResearchModel):
    product_title: Text
    price: Annotated[float, Field(gt=0, le=1_000_000)]
    currency: Literal["USD"] = "USD"
    source_id: str
    method: Literal["listing_jsonld"] = "listing_jsonld"


class ObservedPriceRange(ResearchModel):
    minimum: Annotated[float, Field(gt=0)]
    maximum: Annotated[float, Field(gt=0)]
    currency: Literal["USD"] = "USD"
    sample_size: Annotated[int, Field(ge=1)]
    source_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_prices(self) -> "ObservedPriceRange":
        if self.minimum > self.maximum:
            raise ValueError("Observed price range is reversed.")
        return self


class ResearchReport(ResearchModel):
    product_name: Text
    research_summary: str = "Insufficient evidence"
    observed_price_range: ObservedPriceRange | None = None
    price_observations: list[PriceObservation] = Field(default_factory=list)
    demand_evidence: list[EvidenceFinding] = Field(default_factory=list)
    competition_evidence: list[EvidenceFinding] = Field(default_factory=list)
    trend_evidence: list[EvidenceFinding] = Field(default_factory=list)
    marketing_angles: list[EvidenceFinding] = Field(default_factory=list)
    common_customer_complaints: list[EvidenceFinding] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    dimensions: QualitativeDimensions = Field(default_factory=QualitativeDimensions)
    confidence_level: Confidence = "low"
    status: ResearchStatus = "insufficient"
    mode: Literal["demo", "web"] = "web"
    notice: str = ""
    researched_at: datetime = Field(default_factory=utc_now)
    provider: str = "openai-web-search"
    model: str = ""
    input_fingerprint: str = ""

    @field_validator("researched_at")
    @classmethod
    def research_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Research time must include its timezone.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def resolve_sources(self) -> "ResearchReport":
        unique = {}
        for source in self.sources:
            if source.id in unique:
                prior = unique[source.id]
                if source.what_claim_it_supports not in prior.what_claim_it_supports:
                    prior.what_claim_it_supports = (
                        prior.what_claim_it_supports + "\n" + source.what_claim_it_supports
                    )[:4000]
            else:
                unique[source.id] = source.model_copy(deep=True)
        self.sources = list(unique.values())
        ids = {source.id for source in self.sources}
        for finding in self.findings:
            if not set(finding.source_ids).issubset(ids):
                raise ValueError("Finding references an unknown source.")
        if any(p.source_id not in ids for p in self.price_observations):
            raise ValueError("Price observation references an unknown source.")
        if self.observed_price_range and not set(self.observed_price_range.source_ids).issubset(
            ids
        ):
            raise ValueError("Observed range references an unknown source.")
        return self

    @property
    def findings(self) -> list[EvidenceFinding]:
        return [
            *self.demand_evidence,
            *self.competition_evidence,
            *self.trend_evidence,
            *self.marketing_angles,
            *self.common_customer_complaints,
        ]


class EvidenceScore(ResearchModel):
    total: Annotated[float, Field(ge=0, le=100)]
    unadjusted_total: float
    confidence_level: Confidence
    confidence_factor: float
    components: dict[str, float]
    profit_potential: Annotated[float, Field(ge=0, le=10)]
    normalized_dimensions: dict[str, float]
    missing_dimensions: list[str]


class ResearchAttempt(ResearchModel):
    status: Literal["researching", "completed", "insufficient", "failed"]
    attempted_at: datetime = Field(default_factory=utc_now)
    notice: str = ""
