"""Domain types. Evidence comes from sources, never from the analyst."""

import hashlib
import unicodedata
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Score = Annotated[float, Field(ge=0, le=10)]
Money = Annotated[float, Field(ge=0, le=1_000_000)]
PositiveMoney = Annotated[float, Field(ge=0.01, le=1_000_000)]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Evidence(DomainModel):
    """Source-supplied fact with a reference; V1 local sources supply none."""

    fact: str = Field(min_length=1)
    source: str = Field(min_length=1)


class ScoreHints(DomainModel):
    """Estimated input assumptions, not measured market statistics."""

    demand: Score = 5
    competition: Score = 5
    trend: Score = 5
    marketing: Score = 5


class Product(DomainModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    cost: Money | None = None
    selling_price: PositiveMoney | None = None
    description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list)
    source: Literal["demo", "manual", "external"] = "manual"
    hints: ScoreHints = Field(default_factory=ScoreHints)
    evidence: list[Evidence] = Field(default_factory=list)

    @field_validator("name", "category")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).split())

    @property
    def id(self) -> str:
        """Canonical identity remains stable when estimates change."""
        identity = f"{self.name.casefold()}\0{self.category.casefold()}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


class Assessment(DomainModel):
    """Structured analyst judgement; contains no verified-data claims."""

    demand: Score
    competition: Score
    trend: Score
    marketing: Score
    overview: str = ""
    target_customer: str = ""
    purchase_motivation: str = ""
    marketing_angles: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    competition_reasoning: str = ""
    suggested_price_min: PositiveMoney | None = 1
    suggested_price_max: PositiveMoney | None = 1
    explanation: str = ""
    risks: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    uncertainty: str = "No verified market data is available."

    @model_validator(mode="after")
    def validate_price_range(self) -> "Assessment":
        if (self.suggested_price_min is None) != (self.suggested_price_max is None):
            raise ValueError("Suggested price bounds must both be known or both unknown.")
        if (
            self.suggested_price_min is not None
            and self.suggested_price_min > self.suggested_price_max
        ):
            raise ValueError("Suggested minimum price cannot exceed maximum price.")
        return self


class ScoreBreakdown(DomainModel):
    total: Annotated[float, Field(ge=0, le=100)]
    profit_potential: Score
    components: dict[str, float]
    confidence_factor: float = 1.0
    unadjusted_total: float | None = None


class ResearchResult(DomainModel):
    product: Product
    assessment: Assessment
    gross_margin: float | None
    score: ScoreBreakdown
    recommendation: Literal["Strong candidate", "Worth investigating", "Weak candidate"]
    mode: Literal["demo", "openai"]
    notice: str = ""
    model: str = "deterministic-demo-v1"
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    score_basis: Literal["estimate", "evidence"] = "estimate"
    confidence_level: Literal["low", "medium", "high"] = "low"
