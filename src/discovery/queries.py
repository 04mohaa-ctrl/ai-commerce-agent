"""Reviewed exact queries; series remain independent and never replace product identity."""

import time
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from src.discovery.repository import DiscoveryRepository
from src.supply.demand import DemandIntelligenceService, _query
from src.supply.models import Country, SupplyModel


class QueryTerm(SupplyModel):
    query: str
    language: Literal["sv", "en", "other"]

    @field_validator("query")
    @classmethod
    def visible(cls, value):
        return _query(value)


class QueryPlan(SupplyModel):
    country: Country
    terms: list[QueryTerm] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique(self):
        if len({t.query for t in self.terms}) != len(self.terms):
            raise ValueError("Choose distinct exact queries.")
        return self


def suggestions(product):
    """Small local vocabulary, explicitly suggestions rather than an automatic translation."""
    pairs = {
        "laptop stand": [("laptopställ", "sv"), ("laptop stand", "en")],
        "lunch box": [("matlåda", "sv"), ("lunch box", "en")],
        "pet brush": [("pälsborste", "sv"), ("pet brush", "en")],
        "hair remover": [("pälsborttagare", "sv"), ("pet hair remover", "en")],
        "travel bag": [("resväska", "sv"), ("travel bag", "en")],
        "desk lamp": [("skrivbordslampa", "sv"), ("desk lamp", "en")],
    }
    return [
        QueryTerm(query=q, language=lang)
        for name, pairs_ in pairs.items()
        if name in product.name.casefold()
        for q, lang in pairs_
        if q != product.name
    ]


def save_query_plan(repo, product, plan):
    plan = QueryPlan.model_validate(plan.model_dump())
    DiscoveryRepository(repo).put(
        "queries", product.id + ":" + plan.country, plan.model_dump(mode="json")
    )


def get_query_plan(repo, product, country):
    payload = DiscoveryRepository(repo).get("queries", product.id + ":" + country)
    return QueryPlan.model_validate(payload) if payload else None


def run_queries(
    repo,
    product,
    destination,
    plan,
    *,
    demand=None,
    max_requests=5,
    max_seconds=120,
    monotonic=time.monotonic,
    demo=False,
    batch_id=None,
):
    plan = QueryPlan.model_validate(plan.model_dump())
    if plan.country != destination.country:
        raise ValueError("Query plan market differs from the selected market.")
    if type(max_requests) is not int or not 1 <= max_requests <= 5:
        raise ValueError("Demand batch supports 1–5 local requests.")
    if type(max_seconds) not in (float, int) or not 0 < max_seconds <= 120:
        raise ValueError("Demand batch supports at most 120 seconds.")
    demand = demand or DemandIntelligenceService(repo)
    deadline, used = monotonic() + max_seconds, 0
    batch_id = batch_id or str(uuid4())
    outcomes = []
    storage = DiscoveryRepository(repo)
    for index, term in enumerate(plan.terms):
        if used >= max_requests or monotonic() + 21 >= deadline:
            row = {
                "query": term.query,
                "status": "NOT_STARTED",
                "notice": "Local request/time budget reached. "
                "Review and run remaining queries explicitly.",
            }
        else:
            snapshot = demand.refresh(
                product, destination, query=term.query, demo=demo, action_id=f"{batch_id}:{index}"
            )
            count = sum(snapshot.telemetry.requests.values()) if snapshot else 0
            used += count
            row = {
                "query": term.query,
                "status": snapshot.outcome.status if snapshot else "NOT_STARTED",
                "requests": count,
                "notice": snapshot.outcome.notice
                if snapshot
                else "Action already claimed; inspect saved evidence.",
            }
        outcomes.append(row)
        # Successful query snapshots are already durable in V4; persist batch progress too.
        storage.put(
            "query_batch",
            batch_id,
            {
                "product_id": product.id,
                "country": plan.country,
                "outcomes": outcomes,
                "requests": used,
            },
        )
    return outcomes
