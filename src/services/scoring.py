"""Deterministic scoring. The analyst cannot set totals or recommendations."""

import math

from src.schemas.product import Assessment, Product, ResearchResult, ScoreBreakdown

WEIGHTS = {
    "Demand": 0.25,
    "Profit margin": 0.25,
    "Trend": 0.20,
    "Competition (inverted)": 0.15,
    "Marketing": 0.15,
}


def gross_margin(cost: float, selling_price: float) -> float:
    """Product-only gross margin; excludes ads, freight, fees, taxes and returns."""
    if not math.isfinite(cost) or not math.isfinite(selling_price):
        raise ValueError("Prices must be finite.")
    if cost < 0 or selling_price <= 0:
        raise ValueError("Cost must be non-negative and selling price positive.")
    return (selling_price - cost) / selling_price * 100


def score_breakdown(assessment: Assessment, margin: float) -> ScoreBreakdown:
    """Return weighted points out of 100, including inverted competition."""
    if not math.isfinite(margin):
        raise ValueError("Margin must be finite.")
    profit = max(0.0, min(10.0, margin / 10))
    values = {
        "Demand": assessment.demand,
        "Profit margin": profit,
        "Trend": assessment.trend,
        "Competition (inverted)": 10 - assessment.competition,
        "Marketing": assessment.marketing,
    }
    components = {name: round(value * WEIGHTS[name] * 10, 4) for name, value in values.items()}
    return ScoreBreakdown(
        total=round(sum(components.values()), 1),
        profit_potential=round(profit, 2),
        components=components,
    )


def recommendation(score: float) -> str:
    if score >= 75:
        return "Strong candidate"
    if score >= 55:
        return "Worth investigating"
    return "Weak candidate"


def build_result(
    product: Product,
    assessment: Assessment,
    mode: str = "demo",
    notice: str = "",
    model: str = "deterministic-demo-v1",
) -> ResearchResult:
    """Calculate derived values from inputs and validated analyst judgement."""
    margin = gross_margin(product.cost, product.selling_price)
    score = score_breakdown(assessment, margin)
    return ResearchResult(
        product=product,
        assessment=assessment,
        gross_margin=margin,
        score=score,
        recommendation=recommendation(score.total),
        mode=mode,
        notice=notice,
        model=model,
    )
