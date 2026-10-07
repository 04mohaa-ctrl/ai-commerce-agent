"""Fixed-weight V4 prioritization with explicit missingness and one confidence adjustment."""

import hashlib

from pydantic import BaseModel, ConfigDict, Field

from src.research.market_scoring import INDEPENDENT_CATEGORIES, TREND_POINTS
from src.supply.economics import (
    calculate_financial,
    component_issue,
    component_state,
    fresh,
    selection_issue,
    shipping_issue,
    stock_issue,
    supplier_cost_issue,
    utc_now,
)

SUPPLY_WEIGHTS = {
    "Product/variant match": 0.25,
    "Observed stock": 0.20,
    "Shipping feasibility": 0.20,
    "Cost completeness": 0.15,
    "Delivery-time suitability": 0.10,
    "Supplier-data freshness": 0.10,
}
OPPORTUNITY_WEIGHTS = {
    "Demand evidence": 0.18,
    "Numeric trend": 0.12,
    "Competition evidence": 0.12,
    "Return-adjusted profitability": 0.25,
    "Marketing evidence": 0.08,
    "Evidence quality": 0.10,
    "Supply feasibility": 0.15,
}


class ScoreDimension(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    raw_score: float | None = Field(default=None, ge=0, le=10)
    weight: float
    contribution: float
    evidence_ids: list[str] = Field(default_factory=list)
    availability: str
    reason: str


class RiskFlag(BaseModel):
    code: str
    explanation: str
    evidence_ids: list[str] = Field(default_factory=list)


class SupplyScore(BaseModel):
    version: str = "supply-v4"
    dimensions: dict[str, ScoreDimension]
    coverage: float
    raw_total: float | None
    final_score: float | None
    confidence: str
    confidence_factor: float = 1
    recommendation: str
    risks: list[RiskFlag]
    financial_revision: int
    provisional: bool


class OpportunityScore(SupplyScore):
    version: str = "market-v4"


def _dimension(raw, weight, ids=(), reason=""):
    return ScoreDimension(
        raw_score=raw,
        weight=weight,
        contribution=round((raw or 0) * weight * 10, 4),
        evidence_ids=list(dict.fromkeys(ids)),
        availability="AVAILABLE" if raw is not None else "UNAVAILABLE",
        reason=reason
        if raw is not None
        else "Missing-evidence penalty: " + (reason or "unavailable"),
    )


def _aggregate(dimensions):
    coverage = round(sum(d.weight * 100 for d in dimensions.values() if d.raw_score is not None), 6)
    total = round(sum(d.contribution for d in dimensions.values()), 4) if coverage >= 60 else None
    return coverage, total


def score_supply(selection, destination, financial, stages, now=None):
    now = now or utc_now()
    invalid = selection_issue(selection, destination) or component_issue("match", selection, stages)
    offer = selection.offer if selection else None
    finance = calculate_financial(financial, selection, destination, stages, now)
    complete = finance.economics is not None and finance.economics.complete
    ids = [offer.variant.id] if offer else []
    match = None if not offer else 3 if invalid else 10 if offer.match.outcome == "MATCH" else 7
    stock_problem = stock_issue(selection, destination, now, stages)
    stock = None if stock_problem else 10 if offer.stock.quantity >= destination.quantity else 0
    freight_problem = shipping_issue(selection, destination, financial.currency, now, stages)
    shipping = None if freight_problem else 10
    state = component_state("shipping", selection, stages)
    if (
        not invalid
        and state
        and state.get("status") == "SUCCESS_EMPTY"
        and not state.get("pending")
    ):
        shipping = 0
    delivery = None
    if not freight_problem and offer.quote.delivery_max_days is not None:
        delivery = 10 if offer.quote.delivery_max_days <= destination.max_delivery_days else 3
    cost_problem = supplier_cost_issue(selection, financial.currency, now, stages, destination)
    current = (
        not invalid
        and not stock_problem
        and not freight_problem
        and not cost_problem
        and fresh(offer.candidate.observed_at, 24, now)
        and not component_issue("search", selection, stages)
    )
    dimensions = {
        "Product/variant match": _dimension(
            match, 0.25, ids, invalid or "Explicit selected identity."
        ),
        "Observed stock": _dimension(
            stock,
            0.20,
            [offer.stock.id] if offer and offer.stock else [],
            stock_problem or "Observed quantity against requested quantity.",
        ),
        "Shipping feasibility": _dimension(
            shipping,
            0.20,
            [offer.quote.id] if offer and offer.quote else [],
            freight_problem or "Fresh quote bound to selected variant, warehouse and destination.",
        ),
        "Cost completeness": _dimension(
            10 if complete else None,
            0.15,
            [f"financial:{financial.revision}"],
            "All required assumptions known and compatible."
            if complete
            else "Incomplete or stale V4 financial inputs.",
        ),
        "Delivery-time suitability": _dimension(
            delivery,
            0.10,
            [offer.quote.id] if offer and offer.quote else [],
            f"Compared with declared maximum {destination.max_delivery_days} days."
            if delivery is not None
            else "Delivery estimate unavailable.",
        ),
        "Supplier-data freshness": _dimension(
            10 if current else None,
            0.10,
            ids,
            "All required selected supply components current."
            if current
            else "Required supply components are stale, pending or unavailable.",
        ),
    }
    coverage, total = _aggregate(dimensions)
    sufficient = (
        not invalid
        and stock is not None
        and shipping is not None
        and complete
        and total is not None
    )
    positive = current and stock == 10 and shipping == 10 and complete
    confidence = "high" if positive else "medium" if sufficient else "low"
    recommendation = (
        "INSUFFICIENT EVIDENCE"
        if not sufficient
        else "STRONG CANDIDATE"
        if positive and total >= 75
        else "WORTH INVESTIGATING"
        if positive and total >= 55
        else "WEAK CANDIDATE"
    )
    risks = []

    def risk(code, explanation, refs=()):
        risks.append(RiskFlag(code=code, explanation=explanation, evidence_ids=list(refs)))

    if invalid:
        risk("NO_COMPATIBLE_SUPPLIER", invalid, ids)
    if offer:
        risk(
            "SINGLE_PROVIDER",
            "One provider supplies these observations; warehouses are not independent suppliers.",
            ids,
        )
    if stock is None:
        risk("UNKNOWN_STOCK", stock_problem or "No current stock observation.", ids)
    elif stock == 0:
        risk(
            "INSUFFICIENT_STOCK",
            "Observed stock does not cover the requested quantity.",
            [offer.stock.id],
        )
    if freight_problem:
        risk(
            "UNAVAILABLE_FREIGHT",
            freight_problem,
            [offer.quote.id] if offer and offer.quote else [],
        )
    if (
        offer
        and offer.quote
        and (
            not fresh(offer.quote.observed_at, 6, now)
            or (offer.quote.expires_at and offer.quote.expires_at <= now)
        )
    ):
        risk(
            "STALE_QUOTE",
            "Selected quote has passed its freshness or expiry limit.",
            [offer.quote.id],
        )
    if delivery is None:
        risk("UNKNOWN_DELIVERY", "A current delivery estimate is unavailable.", ids)
    elif delivery == 3:
        risk(
            "SLOW_DELIVERY",
            f"Delivery estimate exceeds the declared {destination.max_delivery_days}-day maximum.",
            [offer.quote.id],
        )
    if not complete:
        risk(
            "INCOMPLETE_LANDED_COST",
            "Required V4 costs or assumptions are missing, incompatible or stale.",
            [f"financial:{financial.revision}"],
        )
    if (
        not freight_problem
        and not cost_problem
        and offer.quote.total_cost / offer.quote.quantity > offer.variant.unit_price
    ):
        risk(
            "HIGH_FREIGHT",
            "Observed per-unit freight exceeds the selected unit product cost.",
            [offer.quote.id, offer.variant.id],
        )
    return SupplyScore(
        dimensions=dimensions,
        coverage=coverage,
        raw_total=total,
        final_score=total,
        confidence=confidence,
        recommendation=recommendation,
        risks=risks,
        financial_revision=financial.revision,
        provisional=total is None,
    )


def _market_stage_failed(market, stages, component):
    relevant = []
    for stage in getattr(getattr(market, "telemetry", None), "stages", []):
        value = stage.model_dump() if hasattr(stage, "model_dump") else stage
        if value.get("stage") == component:
            relevant.append(value)
    relevant.extend(s for s in stages or [] if s.get("component", s.get("stage")) == component)
    if not relevant:
        return False
    value = relevant[-1]
    return (
        value.get("pending")
        or value.get("partial")
        or value.get("status") not in {"SUCCESS", "CACHED"}
    )


def score_opportunity(market, selection, destination, financial, stages, now=None):
    now = now or utc_now()
    supply = score_supply(selection, destination, financial, stages, now)
    finance = calculate_financial(financial, selection, destination, stages, now)
    econ = finance.economics
    values = {key: None for key in OPPORTUNITY_WEIGHTS}
    evidence = {key: [] for key in OPPORTUNITY_WEIGHTS}
    measured = False
    market_confidence = "low"
    if market is not None:
        web = market.web_evidence
        current_web = fresh(web.researched_at, 24 * 7, now) and not _market_stage_failed(
            market, stages, "web"
        )
        pages = {
            p.source_id: p
            for p in market.page_verifications
            if p.fetched and fresh(p.accessed_at, 24 * 7, now)
        }
        supported = {
            (sid, c.claim)
            for sid, p in pages.items()
            for c in p.claims
            if c.status == "VERIFIED_ON_PAGE"
        }
        independent = {
            (sid, claim)
            for sid, claim in supported
            if pages[sid].category in INDEPENDENT_CATEGORIES
        }

        def refs(field, independent_only=True):
            if not current_web:
                return []
            accepted = independent if independent_only else supported
            return list(
                dict.fromkeys(
                    sid
                    for f in getattr(web, field)
                    for sid in f.source_ids
                    if (sid, f.claim) in accepted
                )
            )

        demand_ids = refs("demand_evidence")
        if demand_ids:
            count = len({pages[sid].publisher for sid in demand_ids})
            values["Demand evidence"] = min(9, count * 3)
            evidence["Demand evidence"] = demand_ids
        demand = market.demand
        expected_location = {
            "US": "2840",
            "GB": "2826",
            "SE": "2752",
            "DE": "2276",
            "FR": "2250",
        }.get(destination.country)
        geography = expected_location and expected_location in demand.location
        measured = (
            demand.status == "completed"
            and bool(demand.observations)
            and geography
            and all(fresh(o.collected_at, 24 * 7, now) for o in demand.observations)
            and market.trend.classification in TREND_POINTS
            and not _market_stage_failed(market, stages, "demand")
        )
        if measured:
            values["Numeric trend"] = TREND_POINTS[market.trend.classification]
            evidence["Numeric trend"] = [
                str(getattr(o, "id", getattr(o, "series_id", "")))
                or hashlib.sha256(str(o).encode()).hexdigest()[:20]
                for o in demand.observations
            ]
        strength = {"weak": 3, "moderate": 6, "strong": 9}
        for name, field, dimension, invert, indep in (
            ("Competition evidence", "competition_evidence", "competition", True, True),
            ("Marketing evidence", "marketing_angles", "marketing", False, False),
        ):
            ids = refs(field, indep)
            raw = strength.get(getattr(web.dimensions, dimension))
            if ids and raw is not None:
                values[name] = 10 - raw if invert else raw
                evidence[name] = ids
        used = (
            {
                (sid, f.claim)
                for f in web.findings
                for sid in f.source_ids
                if (sid, f.claim) in independent
            }
            if current_web
            else set()
        )
        domains = {pages[sid].publisher for sid, _ in used}
        price_count = max(
            (
                g.count
                for g in market.price_summaries
                if g.minimum is not None
                and g.currency == financial.currency
                and g.observed_at
                and all(fresh(d, 24 * 7, now) for d in g.observed_at)
            ),
            default=0,
        )
        if used or measured or price_count >= 2:
            values["Evidence quality"] = float(
                min(len(domains), 3)
                + min(len(used), 3)
                + (2 if measured else 0)
                + (1 if price_count >= 2 else 0)
                + int(econ is not None and econ.complete)
            )
            evidence["Evidence quality"] = list(dict.fromkeys(sid for sid, _ in used))
        market_confidence = market.score.confidence
        # Recheck time-sensitive gates without mutating or reusing V3's adjusted score.
        if not current_web or not pages:
            market_confidence = "low"
        elif market_confidence == "high" and not (
            measured
            and price_count >= 3
            and len(domains) >= 3
            and len(used) >= 4
            and sum(
                fresh(pages[sid].updated_at or pages[sid].published_at, 24 * 365, now)
                for sid, _ in used
            )
            / max(len(used), 1)
            >= 0.75
        ):
            market_confidence = "medium"
    if econ is not None and econ.complete:
        values["Return-adjusted profitability"] = max(
            0, min(10, econ.estimated_net_margin_percent / 5)
        )
        evidence["Return-adjusted profitability"] = [f"financial:{financial.revision}"]
    if supply.raw_total is not None and not selection_issue(selection, destination):
        values["Supply feasibility"] = supply.raw_total / 10
        evidence["Supply feasibility"] = [selection.offer.variant.id]
    dimensions = {
        key: _dimension(
            values[key],
            weight,
            evidence[key],
            "Accepted raw evidence and V4 eligibility gates."
            if values[key] is not None
            else "Required current evidence is unavailable.",
        )
        for key, weight in OPPORTUNITY_WEIGHTS.items()
    }
    coverage, raw = _aggregate(dimensions)
    high = (
        market_confidence == "high"
        and measured
        and supply.confidence == "high"
        and econ is not None
        and econ.complete
    )
    confidence = "high" if high else "medium" if market_confidence in {"medium", "high"} else "low"
    factor = {"low": 0.5, "medium": 0.85, "high": 1.0}[confidence]
    final = round(raw * factor, 1) if raw is not None else None
    sufficient = (
        raw is not None
        and values["Demand evidence"] is not None
        and values["Return-adjusted profitability"] is not None
        and not selection_issue(selection, destination)
        and supply.recommendation != "INSUFFICIENT EVIDENCE"
    )
    recommendation = (
        "INSUFFICIENT EVIDENCE"
        if not sufficient
        else "STRONG CANDIDATE"
        if final >= 75 and high
        else "WORTH INVESTIGATING"
        if final >= 55 and confidence in {"medium", "high"}
        else "WEAK CANDIDATE"
    )
    risks = list(supply.risks)
    if values["Demand evidence"] is None:
        risks.append(
            RiskFlag(
                code="MISSING_DEMAND",
                explanation="Independent supported current demand evidence is unavailable.",
            )
        )
    if not measured:
        risks.append(
            RiskFlag(
                code="MISSING_MEASURED_TREND",
                explanation="Fresh measured trend for the selected geography is unavailable.",
            )
        )
    return OpportunityScore(
        dimensions=dimensions,
        coverage=coverage,
        raw_total=raw,
        final_score=final,
        confidence=confidence,
        confidence_factor=factor,
        recommendation=recommendation,
        risks=risks,
        financial_revision=financial.revision,
        provisional=raw is None,
    )
