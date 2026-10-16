"""Explicit catalog requests with compatible cache reuse and local candidate saves."""

import hashlib
import json
from datetime import timedelta

from src.agents.product_research_agent import ProductResearchAgent
from src.database.supply_repository import SupplyRepository
from src.discovery.models import DiscoveryResult
from src.discovery.repository import DiscoveryRepository
from src.research.models import utc_now
from src.schemas.product import Product, ResearchResult, SupplierIdentity
from src.supply.cj_provider import CJDropShippingProvider
from src.supply.models import ActionTelemetry, ProviderOutcome


class DiscoveryService:
    def __init__(self, repo, provider=None, clock=utc_now):
        self.storage = DiscoveryRepository(repo)
        self.provider = provider or CJDropShippingProvider()
        self.clock = clock

    def search(self, search, *, demo=False, force=False, max_requests=4):
        run = ActionTelemetry(action="discovery", started_at=self.clock())
        identity = [search.model_dump(mode="json"), self.provider.name, self.provider.cache_context]
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        cached = self.storage.get("search", key)
        if demo:
            outcome = ProviderOutcome(
                status="UNAVAILABLE", notice="Demo Mode disables CJ requests."
            )
        elif (
            cached
            and not force
            and timedelta(0)
            <= self.clock() - DiscoveryResult.model_validate(cached).searched_at
            < timedelta(
                hours=24 if cached["outcome"]["status"] in {"SUCCESS", "SUCCESS_EMPTY"} else 1
            )
        ):
            result = DiscoveryResult.model_validate(cached)
            result.cached = True
            return result
        else:
            self.provider.reset_action(run, max_requests=max_requests, max_seconds=30)
            try:
                outcome = self.provider.discover(search)
            except Exception:
                outcome = ProviderOutcome(
                    status="FAILED", notice="Catalog request failed; retry explicitly."
                )
        run.completed_at = self.clock()
        result = DiscoveryResult(
            search=search, outcome=outcome, telemetry=run, searched_at=self.clock()
        )
        if not demo:
            self.storage.put("search", key, result.model_dump(mode="json"))
        return result


def save_candidate(repo, item, destination):
    """Stable provider identity; repeat saves never overwrite later research or assumptions."""
    candidate = item.candidate
    product = Product(
        name=candidate.name[:120],
        category=(candidate.category or "Supplier candidates")[:80],
        source="external",
        supplier_identity=SupplierIdentity(
            provider=candidate.provider, product_id=candidate.product_id
        ),
    )
    existing = next((r for r in repo.list_saved() if r.product.id == product.id), None)
    if existing:
        return existing
    # If the shortlist entry was removed, keep durable target edits and existing settings.
    prior = next((p for p in repo.list_candidates() if p.id == product.id), None)
    product = prior or product
    result = ProductResearchAgent(force_demo=True).analyze(product)
    supply = SupplyRepository(repo)
    supply.enable()  # Existing backup-before-migration protocol runs before product writes.
    DiscoveryRepository(repo).enable()
    with repo._connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT payload FROM saved_products WHERE product_id=?", (product.id,)
        ).fetchone()
        if current:
            return ResearchResult.model_validate_json(current[0])
        conn.execute(
            "INSERT OR IGNORE INTO workspace_v5 VALUES('origin',?,?)",
            (product.id, item.model_dump_json()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO candidates(product_id,payload) VALUES(?,?)",
            (product.id, product.model_dump_json()),
        )
        conn.execute(
            "INSERT INTO saved_products(product_id,payload) VALUES(?,?)",
            (product.id, result.model_dump_json()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO supply_v4_settings VALUES(?,?,?)",
            (product.id, product.id, destination.model_dump_json()),
        )
    return result
