"""Combine sources, analyze candidates and apply shared view filters."""

from collections.abc import Sequence

from src.agents.product_research_agent import ProductResearchAgent
from src.database.database import ProductRepository
from src.schemas.product import Product, ResearchResult
from src.sources.local import LocalProductSource, ProductSource, matches_query

SORT_KEYS = {
    "AI Score": lambda r: r.score.total,
    "Margin": lambda r: r.gross_margin,
    "Demand": lambda r: r.assessment.demand,
    "Competition": lambda r: r.assessment.competition,
    "Trend": lambda r: r.assessment.trend,
}


def filter_results(
    results: Sequence[ResearchResult],
    *,
    categories: list[str] | None = None,
    min_score: float = 0,
    min_margin: float | None = None,
    recommendations: list[str] | None = None,
    sort_by: str = "AI Score",
    descending: bool = True,
) -> list[ResearchResult]:
    """Filter without mutating input and sort numbers, with deterministic tie order."""
    if sort_by not in SORT_KEYS:
        raise ValueError("Unknown sort field.")
    rows = [
        r
        for r in results
        if (not categories or r.product.category in categories)
        and r.score.total >= min_score
        and (min_margin is None or r.gross_margin >= min_margin)
        and (not recommendations or r.recommendation in recommendations)
    ]
    rows.sort(key=lambda r: (r.product.name.casefold(), r.product.id))
    return sorted(rows, key=SORT_KEYS[sort_by], reverse=descending)


class ResearchService:
    def __init__(
        self,
        repository: ProductRepository,
        agent: ProductResearchAgent,
        sources: Sequence[ProductSource] | None = None,
    ):
        self.repository = repository
        self.agent = agent
        self.sources = list(sources) if sources is not None else [LocalProductSource()]

    def candidates(self, query: str = "") -> list[Product]:
        products = {p.id: p for source in self.sources for p in source.search(query)}
        for p in self.repository.list_candidates():
            # A manual replacement shadows its original for every query, even
            # when only the original's obsolete description/tags would match.
            products.pop(p.id, None)
            if matches_query(p, query):
                products[p.id] = p
        return list(products.values())

    def research(self, query: str, limit: int = 20) -> list[ResearchResult]:
        if limit <= 0:
            return []
        results = [self.agent.analyze(p) for p in self.candidates(query)[:limit]]
        return filter_results(results)
