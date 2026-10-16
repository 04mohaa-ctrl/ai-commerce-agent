"""Create a NEW synthetic acceptance DB. Never reads .env or calls providers."""

import argparse
from datetime import timedelta
from pathlib import Path

from src.agents.product_research_agent import ProductResearchAgent
from src.database.database import ProductRepository
from src.database.supply_repository import SupplyRepository
from src.discovery.comparison import ComparisonGroup, save_group
from src.discovery.models import CatalogItem
from src.discovery.queries import QueryPlan, QueryTerm, save_query_plan
from src.discovery.service import save_candidate
from src.research.models import utc_now
from src.research.providers.base import product_fingerprint
from src.research.providers.demand_trend import DemandObservation, DemandResult
from src.supply.demand import DemandIntelligenceService, DemandSnapshot
from src.supply.matching import match_supplier
from src.supply.models import (
    ActionTelemetry,
    Destination,
    ProviderOutcome,
    ShippingQuote,
    StockObservation,
    SupplierOffer,
    SupplierProductCandidate,
    SupplierRequirements,
    SupplierVariant,
    SupplyIntelligenceReport,
)


def seed(path):
    path = Path(path)
    if path.exists():
        raise FileExistsError("Acceptance seeding requires a new database path.")
    repo = ProductRepository(path)
    ext = SupplyRepository(repo)
    now = utc_now()
    destination = Destination(country="SE")
    products = []
    entries = [
        ("Laptop stand", "Color: Black; Count: 1", "Laptop side phone mount Silver", "laptopställ"),
        ("Pet brush", "Color: Black; Count: 1", "Pet brush Black 2 pack", "pälsborste"),
        ("Lunch box", "Color: Black; Capacity: 1000ml", "Lunch box Black 500ml", "matlåda"),
    ]
    for index, (name, description, wrong_name, swedish) in enumerate(entries, 1):
        observed = now if index < 3 else now - timedelta(days=8)
        candidate = SupplierProductCandidate(
            provider="cj", product_id=f"SYNTHETIC-{index}", name=name, observed_at=observed
        )
        result = save_candidate(
            repo,
            CatalogItem(
                candidate=candidate, catalog_price="5.00", currency="USD", evidence_kind="SYNTHETIC"
            ),
            destination,
        )
        product = result.product.model_copy(update={"description": description})
        repo.add_candidate(product)
        repo.save(ProductResearchAgent(force_demo=True).analyze(product))
        products.append(product)
        requirements = SupplierRequirements(color="black")
        ext.save_requirements(product.id, requirements)
        offers = []
        for number, variant_name in enumerate(
            [f"{name} Black " + ("1000ml" if index == 3 else "1 pack"), wrong_name]
        ):
            variant = SupplierVariant(
                provider="cj",
                product_id=candidate.product_id,
                variant_id=f"SYNTHETIC-V{index}-{number}",
                name=variant_name,
                attributes={"variant_key": variant_name},
                unit_price=5 + index,
                currency="USD",
                observed_at=observed,
            )
            stock = StockObservation(
                provider="cj",
                product_id=candidate.product_id,
                variant_id=variant.variant_id,
                warehouse_id="SYNTHETIC-AREA",
                storage_id="SYNTHETIC-STORAGE",
                country="CN",
                quantity=70,
                cj_quantity=20 if index == 1 else 0,
                factory_quantity=50 if index == 1 else 70,
                observed_at=observed,
            )
            quote = (
                ShippingQuote(
                    provider="cj",
                    product_id=candidate.product_id,
                    variant_id=variant.variant_id,
                    variant_snapshot=variant.id,
                    warehouse_id=stock.warehouse_id,
                    storage_id=stock.storage_id,
                    origin="CN",
                    destination=destination,
                    quantity=1,
                    method="SYNTHETIC parcel",
                    total_cost="9.25",
                    currency="USD",
                    delivery_min_days=7,
                    delivery_max_days=12,
                    observed_at=observed,
                )
                if index == 1 and number == 0
                else None
            )
            offers.append(
                SupplierOffer(
                    candidate=candidate,
                    variant=variant,
                    stock=stock,
                    quote=quote,
                    match=match_supplier(
                        product, candidate, variant, destination, requirements=requirements
                    ),
                )
            )
        ext.save_report(
            SupplyIntelligenceReport(
                product_id=product.id,
                input_fingerprint=product_fingerprint(product),
                destination=destination,
                offers=offers,
                researched_at=observed,
                stages=[
                    {
                        "provider": "cj",
                        "component": component,
                        "status": "SUCCESS",
                        "observed_at": observed.isoformat(),
                        "notice": "SYNTHETIC fixture; no API request",
                    }
                    for component in ("details", "variants", "stock", "shipping")
                ],
            )
        )
        plan = QueryPlan(
            country="SE",
            terms=[QueryTerm(query=name, language="en"), QueryTerm(query=swedish, language="sv")],
        )
        save_query_plan(repo, product, plan)
        for term in plan.terms:
            observations = [
                DemandObservation(
                    metric_name="keyword_popularity",
                    provider="synthetic-fixture",
                    query=term.query,
                    location="Sweden (2752)",
                    value=40 if bin_ in {2, 8, 40} else None,
                    unit="relative_popularity_index",
                    period_start=now.date() - timedelta(days=364 - bin_ * 7),
                    period_end=now.date() - timedelta(days=358 - bin_ * 7),
                    collected_at=observed,
                    source_url="https://example.com/synthetic-demand",
                    series_id=f"synthetic-{index}-{term.language}",
                )
                for bin_ in range(52)
            ]
            demand = DemandResult(
                provider="synthetic-fixture",
                query=term.query,
                location="Sweden (2752)",
                observations=observations,
                status="completed",
                collected_at=observed,
            )
            snapshot = DemandSnapshot(
                product_id=product.id,
                input_fingerprint=product_fingerprint(product),
                country="SE",
                query=term.query,
                provider="synthetic-fixture",
                location=demand.location,
                request_context="synthetic-offline",
                period_start=observations[0].period_start,
                period_end=observations[-1].period_end,
                outcome=ProviderOutcome(
                    status="SUCCESS",
                    observed_at=observed,
                    notice="SYNTHETIC sparse data; not real demand",
                ),
                demand=demand,
                telemetry=ActionTelemetry(action="synthetic_fixture"),
            )
            key = DemandIntelligenceService._current_key(product, destination, term.query)
            ext.save_cache(
                key, ProviderOutcome(status="SUCCESS", records=[snapshot.model_dump(mode="json")])
            )
    save_group(
        repo,
        ComparisonGroup(
            name="Synthetic Swedish shortlist",
            product_ids=[p.id for p in products],
            notes=(
                "Synthetic acceptance data only. Validate identities, stock types, "
                "sparse/stale demand and unknown economics."
            ),
        ),
    )
    return repo


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    seed(parser.parse_args().database)
    print("Created synthetic acceptance database; zero provider calls.")
