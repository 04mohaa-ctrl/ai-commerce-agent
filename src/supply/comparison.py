"""Read-only V4 comparison/export of current eligibility and immutable observations."""

from src.database.market_repository import MarketIntelligenceRepository
from src.database.supply_repository import SupplyRepository
from src.services.market_economics import MarketEconomicsInputs
from src.supply.demand import DemandIntelligenceService, current_market_overlay
from src.supply.economics import (
    FinancialSnapshot,
    calculate_financial,
    shipping_issue,
    supplier_cost_issue,
    utc_now,
)
from src.supply.models import Destination
from src.supply.scoring import score_opportunity, score_supply
from src.supply.service import SupplierIntelligenceService


def comparison_document(results, repo, now=None):
    now = now or utc_now()
    extension = SupplyRepository(repo)
    service = SupplierIntelligenceService(extension)
    products = []
    for result in results:
        product = result.product
        destination = extension.get_settings(product.id) or Destination()
        selected = extension.get_selection(product.id)
        stored = extension.get_financial(product.id)
        snapshot = stored or FinancialSnapshot(
            inputs=(
                MarketIntelligenceRepository(repo).get_economics(product.id)
                or MarketEconomicsInputs(
                    unit_product_cost=product.cost, selling_price=product.selling_price
                )
            )
        )
        stages = service.current_stages(product)
        finance = calculate_financial(snapshot, selected, destination, stages, now)
        supply = score_supply(selected, destination, snapshot, stages, now)
        market = current_market_overlay(product, repo, destination)
        opportunity = score_opportunity(market, selected, destination, snapshot, stages, now)
        demand = DemandIntelligenceService(extension, clock=lambda: now).get_current(
            product, destination
        )
        report = extension.get_report(product.id)
        products.append(
            {
                "product": {"id": product.id, **product.model_dump(mode="json")},
                "destination": destination.model_dump(mode="json"),
                "requirements": extension.get_requirements(product.id).model_dump(mode="json"),
                "selection": selected.model_dump(mode="json") if selected else None,
                "adoption_eligibility": {
                    "supplier_cost_issue": supplier_cost_issue(
                        selected, snapshot.currency, now, stages, destination
                    ),
                    "shipping_issue": shipping_issue(
                        selected, destination, snapshot.currency, now, stages
                    ),
                },
                "supplier_observations": report.model_dump(mode="json") if report else None,
                "current_supplier_stages": stages,
                "shortlist": extension.get_shortlist(product.id),
                "financial": {
                    "saved": stored is not None,
                    "snapshot": snapshot.model_dump(mode="json"),
                    "calculation": finance.model_dump(mode="json"),
                },
                "demand": demand.model_dump(mode="json") if demand else None,
                "supply_score": supply.model_dump(mode="json"),
                "opportunity_score": opportunity.model_dump(mode="json"),
                "legacy_analysis": {
                    "mode": result.mode,
                    "score_basis": result.score_basis,
                    "analyzed_at": result.analyzed_at.isoformat(),
                    "score": result.score.model_dump(mode="json"),
                },
            }
        )
    return {
        "schema": "ai-commerce-v4-comparison-1",
        "exported_at": now.isoformat(),
        "semantics": {
            "currency": "USD unless the observation explicitly states otherwise",
            "unknown": "null is unknown; numeric zero is explicit",
            "units": "landed cost per unit; profit, fees, returns, ads and CPA per order",
            "evidence": "supplier observations are historical until current gates pass; "
            "manual assumptions are not provider evidence",
            "limitations": "estimates before overhead and income tax; "
            "no tax determination or automatic FX",
        },
        "products": products,
    }


def comparison_rows(document):
    rows = []
    for item in document["products"]:
        calc = item["financial"]["calculation"]
        econ = calc["economics"] or {}
        selected = item["selection"]
        offer = selected["offer"] if selected else None
        stock = offer["stock"] if offer else None
        quote = offer["quote"] if offer else None
        demand = item["demand"]
        rows.append(
            {
                "Product": item["product"]["name"],
                "Market": item["destination"]["country"],
                "Units/order": item["destination"]["quantity"],
                "Selected variant": offer["variant"]["variant_id"] if offer else None,
                "CJ stock": stock["cj_quantity"] if stock else None,
                "Factory stock": stock["factory_quantity"] if stock else None,
                "Freight method": quote["method"] if quote else None,
                "Supplier adoption": item["adoption_eligibility"]["supplier_cost_issue"]
                or "Eligible",
                "Freight adoption": item["adoption_eligibility"]["shipping_issue"] or "Eligible",
                "Landed USD/unit": econ.get("landed_cost"),
                "Landed USD/order": calc["landed_cost_per_order"],
                "Net USD/order": econ.get("estimated_net_profit"),
                "Break-even CPA USD/order": econ.get("break_even_ad_cost"),
                "Missing assumptions": "; ".join(calc["missing_inputs"]),
                "Current financial issues": "; ".join(calc["reasons"]),
                "Demand attempt": demand["outcome"]["status"] if demand else "NOT_REQUESTED",
                "Demand current": demand["current_eligible"] if demand else False,
                "Trend": demand["trend"]["classification"] if demand else "INSUFFICIENT_DATA",
                "Supply score /10": item["supply_score"]["final_score"] / 10
                if item["supply_score"]["final_score"] is not None
                else None,
                "Opportunity score /100": item["opportunity_score"]["final_score"],
                "Opportunity recommendation": item["opportunity_score"]["recommendation"],
            }
        )
    return rows
