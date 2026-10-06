"""Versioned deterministic prioritization from attributable evidence, not an LLM score."""

from datetime import timedelta

from pydantic import Field

from src.research.models import ResearchModel, utc_now

MARKET_WEIGHTS = {
    "Demand evidence": 0.20,
    "Numeric trend": 0.15,
    "Competition evidence": 0.15,
    "Return-adjusted profitability": 0.25,
    "Marketing evidence": 0.10,
    "Evidence quality": 0.15,
}
INDEPENDENT_CATEGORIES = {"NEWS_EDITORIAL", "RESEARCH_REPORT", "FORUM"}
TREND_POINTS = {
    "STRONGLY_GROWING": 9.0,
    "GROWING": 7.0,
    "STABLE": 5.0,
    "DECLINING": 2.0,
    "STRONGLY_DECLINING": 0.0,
}


class MarketScore(ResearchModel):
    version: str = "market-v3"
    dimensions: dict[str, float]
    weights: dict[str, float] = Field(default_factory=lambda: dict(MARKET_WEIGHTS))
    contributions: dict[str, float]
    raw_score: float
    confidence_factor: float
    final_score: float
    confidence: str
    positives: list[str]
    missing: list[str]
    recommendation: str
    independent_domains: int = 0
    supported_claims: int = 0
    seller_sources: int = 0
    dated_fresh_fraction: float = 0


def score_market_report(web, pages, demand, trend, prices, economics, now=None) -> MarketScore:
    now = now or utc_now()
    eligible = {
        p.source_id: p
        for p in pages
        if p.category in INDEPENDENT_CATEGORIES and getattr(p, "fetched", True)
    }
    supported = {
        (p.source_id, c.claim)
        for p in pages
        for c in p.claims
        if c.status == "VERIFIED_ON_PAGE" and getattr(p, "fetched", True)
    }
    independent = supported & {
        (sid, f.claim) for f in web.findings for sid in f.source_ids if sid in eligible
    }
    domains = {eligible[sid].publisher for sid, _ in independent}
    demand_domains = {
        eligible[sid].publisher
        for f in web.demand_evidence
        for sid in f.source_ids
        if (sid, f.claim) in independent
    }

    def coverage(field, independent_only):
        return any(
            (sid, f.claim) in (independent if independent_only else supported)
            for f in getattr(web, field)
            for sid in f.source_ids
        )

    def dated(sid):
        page = eligible[sid]
        date = page.updated_at or page.published_at
        return date is not None and timedelta(0) <= now - date <= timedelta(days=365)

    fraction = sum(dated(sid) for sid, _ in independent) / max(len(independent), 1)
    measured = (
        demand.status == "completed"
        and bool(demand.observations)
        and trend.classification in TREND_POINTS
        and all(
            timedelta(0) <= now - o.collected_at <= timedelta(days=7) for o in demand.observations
        )
    )
    counts = []
    for group in prices:
        dates = group.observed_at if isinstance(group.observed_at, list) else [group.observed_at]
        if (
            group.minimum is not None
            and dates
            and all(timedelta(0) <= now - d <= timedelta(days=7) for d in dates)
        ):
            counts.append(group.count)
    # One compatible cohort; do not earn coverage by pooling currencies or variants.
    price_count = max(counts, default=0)
    complete = economics.complete
    current_pages = all(
        timedelta(0) <= now - p.accessed_at <= timedelta(days=7)
        for p in pages
        if getattr(p, "fetched", True)
    )
    confidence = "low"
    if (
        len(domains) >= 3
        and len(independent) >= 4
        and fraction >= 0.75
        and measured
        and price_count >= 3
        and complete
    ):
        confidence = "high"
    elif (
        len(domains) >= 2
        and len(independent) >= 2
        and fraction >= 0.5
        and (measured or price_count >= 2)
    ):
        confidence = "medium"
    if now - web.researched_at > timedelta(days=7):
        confidence = {"high": "medium", "medium": "low", "low": "low"}[confidence]
    if not current_pages:
        confidence = {"high": "medium", "medium": "low", "low": "low"}[confidence]
    demand_value = {0: 0.0, 1: 3.0, 2: 6.0}.get(len(demand_domains), 9.0)
    margin = economics.estimated_net_margin_percent
    profit = round(max(0.0, min(10.0, margin / 5)), 4) if margin is not None else 0.0
    strength = {"weak": 3.0, "moderate": 6.0, "strong": 9.0}
    competition = (
        10 - strength.get(web.dimensions.competition, 10.0)
        if coverage("competition_evidence", True)
        else 0.0
    )
    marketing = (
        strength.get(web.dimensions.marketing, 0.0) if coverage("marketing_angles", False) else 0.0
    )
    quality = (
        min(len(domains), 3)
        + min(len(independent), 3)
        + (2 if measured else 0)
        + (1 if price_count >= 2 else 0)
        + int(complete)
    )
    dimensions = {
        "Demand evidence": demand_value,
        "Numeric trend": TREND_POINTS.get(trend.classification, 0.0) if measured else 0.0,
        "Competition evidence": competition,
        "Return-adjusted profitability": profit,
        "Marketing evidence": marketing,
        "Evidence quality": float(quality),
    }
    contributions = {k: round(v * MARKET_WEIGHTS[k] * 10, 4) for k, v in dimensions.items()}
    raw = round(sum(contributions.values()), 4)
    factor = {"low": 0.50, "medium": 0.85, "high": 1.0}[confidence]
    final = round(raw * factor, 1)
    recommendation = (
        "INSUFFICIENT EVIDENCE"
        if not demand_domains or margin is None
        else "STRONG CANDIDATE"
        if final >= 75 and confidence == "high"
        else "WORTH INVESTIGATING"
        if final >= 55 and confidence != "low"
        else "WEAK CANDIDATE"
    )
    positives, missing = [], []
    for present, good, bad in (
        (
            len(domains) >= 2,
            f"{len(domains)} eligible independent publisher domains",
            "Fewer than two eligible independent publisher domains",
        ),
        (
            len(independent) >= 2,
            f"{len(independent)} independent claims supported on source pages",
            "Too few independent claims supported on source pages",
        ),
        (
            fraction >= 0.5,
            f"{fraction:.0%} of scored claims have known current publication metadata",
            "Missing or stale publication metadata",
        ),
        (
            measured,
            "Fresh measured relative search-interest series",
            "Measured trend unavailable or stale",
        ),
        (
            price_count >= 2,
            f"{price_count} current compatible listing prices",
            "Insufficient compatible current price observations",
        ),
        (
            complete,
            "Complete explicitly entered V3 economics",
            "V3 landed/fee/return economics incomplete",
        ),
    ):
        (positives if present else missing).append(good if present else bad)
    if now - web.researched_at > timedelta(days=7):
        missing.append("Web evidence is over seven days old")
    if not current_pages:
        missing.append("Retained page support is stale or has an invalid access timestamp")
    return MarketScore(
        dimensions=dimensions,
        contributions=contributions,
        raw_score=raw,
        confidence_factor=factor,
        final_score=final,
        confidence=confidence,
        positives=positives,
        missing=missing,
        recommendation=recommendation,
        independent_domains=len(domains),
        supported_claims=len(independent),
        seller_sources=sum(p.category in {"SELLER", "MARKETPLACE", "MANUFACTURER"} for p in pages),
        dated_fresh_fraction=fraction,
    )
