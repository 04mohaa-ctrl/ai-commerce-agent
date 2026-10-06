"""V3 sidecar report; no rewriting of V1/V2 saved score snapshots."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from src.research.market_scoring import MarketScore
from src.research.models import ResearchModel, ResearchReport, utc_now
from src.research.providers.demand_trend import DemandResult
from src.research.providers.retail_prices import MarketPriceObservation, PriceSummary
from src.research.telemetry import RunTelemetry
from src.research.trends import TrendResult
from src.research.verification import PageVerification
from src.services.market_economics import MarketEconomicsInputs, MarketEconomicsResult


class MarketIntelligenceReport(ResearchModel):
    schema_version: Literal[3] = 3
    product_id: str
    product_name: str
    input_fingerprint: str
    researched_at: datetime = Field(default_factory=utc_now)
    web_evidence: ResearchReport
    page_verifications: list[PageVerification] = Field(default_factory=list)
    demand: DemandResult
    trend: TrendResult
    price_observations: list[MarketPriceObservation] = Field(default_factory=list)
    price_summaries: list[PriceSummary] = Field(default_factory=list)
    economics_inputs: MarketEconomicsInputs
    economics_result: MarketEconomicsResult
    score: MarketScore
    telemetry: RunTelemetry = Field(default_factory=RunTelemetry)
    risk_flags: list[str] = Field(default_factory=list)
