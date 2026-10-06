"""Evidence coverage and profitability turn qualitative judgements into a score."""

from datetime import timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from src.research.models import EvidenceScore, ResearchReport, utc_now
from src.schemas.product import ResearchResult
from src.services.economics import EconomicsInputs, calculate_economics
from src.services.scoring import WEIGHTS

if TYPE_CHECKING:
    from src.database.database import ProductRepository

DIMENSION_FIELDS = {
    "demand": "demand_evidence",
    "competition": "competition_evidence",
    "trend": "trend_evidence",
    "marketing": "marketing_angles",
}
NORMALIZED = {"weak": 3.0, "moderate": 6.0, "strong": 9.0}
CONFIDENCE_FACTORS = {"low": 0.5, "medium": 0.85, "high": 1.0}


def normalized_dimensions(report: ResearchReport) -> dict[str, float]:
    values = {}
    for name, field in DIMENSION_FIELDS.items():
        strength = getattr(report.dimensions, name) if getattr(report, field) else "unknown"
        values[name] = NORMALIZED.get(strength, 10.0 if name == "competition" else 0.0)
    return values


def confidence_for(report: ResearchReport) -> str:
    """Coverage heuristic, not a truth guarantee; automated web reports are capped at medium."""
    if report.mode == "demo" or report.researched_at < utc_now() - timedelta(days=7):
        return "low"
    used_ids = {sid for finding in report.findings for sid in finding.source_ids}
    # Collapse subdomains conservatively. Shared suffixes may undercount publishers.
    domains = {
        ".".join((urlsplit(s.url).hostname or "").split(".")[-2:])
        for s in report.sources
        if s.id in used_ids
    }
    coverage = all(
        getattr(report, DIMENSION_FIELDS[name]) and getattr(report.dimensions, name) != "unknown"
        for name in ("demand", "competition", "trend")
    )
    return "medium" if len(domains) >= 3 and coverage else "low"


def calculate_evidence_score(report: ResearchReport, inputs: EconomicsInputs) -> EvidenceScore:
    values = normalized_dimensions(report)
    economics = calculate_economics(inputs)
    margin = economics.estimated_net_margin_percent
    profit = max(0.0, min(10.0, margin / 10)) if margin is not None else 0.0
    weighted = {
        "Demand": values["demand"],
        "Profit margin": profit,
        "Trend": values["trend"],
        "Competition (inverted)": 10 - values["competition"],
        "Marketing": values["marketing"],
    }
    components = {k: round(v * WEIGHTS[k] * 10, 4) for k, v in weighted.items()}
    raw = sum(components.values())
    confidence = confidence_for(report)
    factor = CONFIDENCE_FACTORS[confidence]
    return EvidenceScore(
        total=round(raw * factor, 1),
        unadjusted_total=raw,
        confidence_level=confidence,
        confidence_factor=factor,
        components=components,
        profit_potential=round(profit, 2),
        normalized_dimensions=values,
        missing_dimensions=[
            name
            for name, field in DIMENSION_FIELDS.items()
            if not getattr(report, field) or getattr(report.dimensions, name) == "unknown"
        ],
    )


def decorate_result(
    result: ResearchResult, report: ResearchReport | None, inputs: EconomicsInputs | None = None
) -> ResearchResult:
    """Compose current evidence into V1 display/save types, leaving original snapshots untouched."""
    from src.research.providers.base import product_fingerprint
    from src.schemas.product import ScoreBreakdown
    from src.services.scoring import gross_margin, recommendation

    if (
        report is None
        or report.mode != "web"
        or report.status == "failed"
        or report.input_fingerprint != product_fingerprint(result.product)
    ):
        return result
    economics = inputs or EconomicsInputs(
        product_cost=result.product.cost, selling_price=result.product.selling_price
    )
    score = calculate_evidence_score(report, economics)
    product = result.product.model_copy(
        update={"cost": economics.product_cost, "selling_price": economics.selling_price}
    )
    assessment = result.assessment.model_copy(
        update={
            **score.normalized_dimensions,
            "explanation": report.research_summary,
            "marketing_angles": [f.claim for f in report.marketing_angles],
            "problems": [f.claim for f in report.common_customer_complaints],
            "risks": report.risks,
            "competition_reasoning": " ".join(f.claim for f in report.competition_evidence)
            or "Insufficient evidence",
            "uncertainty": "Source-linked web summaries and qualitative dimensions "
            "are AI judgements. "
            "Confidence reflects coverage, not proof. Validate the cited pages before acting.",
        }
    )
    return result.model_copy(
        update={
            "product": product,
            "assessment": assessment,
            "gross_margin": (
                gross_margin(economics.product_cost, economics.selling_price)
                if economics.product_cost is not None and economics.selling_price is not None
                else None
            ),
            "score": ScoreBreakdown(
                total=score.total,
                profit_potential=score.profit_potential,
                components=score.components,
                confidence_factor=score.confidence_factor,
                unadjusted_total=score.unadjusted_total,
            ),
            "recommendation": recommendation(score.total),
            "score_basis": "evidence",
            "confidence_level": score.confidence_level,
            "mode": "openai",
            "model": report.model or result.model,
            "notice": report.notice,
            "analyzed_at": report.researched_at,
        }
    )


def hydrate_results(
    results: list[ResearchResult], repository: "ProductRepository"
) -> list[ResearchResult]:
    return [
        decorate_result(
            r, repository.get_research(r.product.id), repository.get_economics(r.product.id)
        )
        for r in results
    ]
