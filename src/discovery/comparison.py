"""Saved V5 groups and explicit comparability over the existing V4 evidence export."""

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from src.discovery.queries import get_query_plan
from src.discovery.repository import DiscoveryRepository
from src.supply.comparison import comparison_document, comparison_rows
from src.supply.demand import DemandIntelligenceService
from src.supply.models import Destination, SupplyModel


class ComparisonGroup(SupplyModel):
    name: str = Field(min_length=1, max_length=100)
    product_ids: list[str] = Field(min_length=3, max_length=5)
    decision: Literal["Undecided", "Investigate", "Request samples later", "Hold", "Reject"] = (
        "Undecided"
    )
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("A group needs 3–5 distinct saved candidates.")
        return self


def save_group(repo, group):
    group = ComparisonGroup.model_validate(group.model_dump())
    saved = {r.product.id for r in repo.list_saved()}
    if not set(group.product_ids) <= saved:
        raise ValueError("Choose candidates that are still saved.")
    key = hashlib.sha256(group.name.casefold().encode()).hexdigest()
    DiscoveryRepository(repo).put("group", key, group.model_dump(mode="json"))


def _signature(item):
    destination = item["destination"]
    snapshot = item["financial"]["snapshot"]
    tax = snapshot["tax_assumptions"]
    fx = snapshot["price_conversion"]
    return {
        "geography": [destination[f] for f in ("country", "postal_code", "region")],
        "quantity": destination["quantity"],
        "currency": snapshot["currency"],
        "tax": [
            tax[f] for f in ("price_basis", "sales_vat_percent", "import_vat_recoverable_percent")
        ],
        "FX assumptions": {
            f: fx[f] for f in ("currency", "usd_per_currency", "rate_date", "source")
        }
        if fx
        else None,
    }


def next_actions(item):
    actions = []
    if not item["selection"]:
        actions.append(
            (
                "Specify variants: refresh supplier data, review match, then select a variant"
                " and warehouse."
            )
        )
    for field, label in (("supplier_cost_issue", "Product cost"), ("shipping_issue", "Freight")):
        issue = item["adoption_eligibility"][field]
        if issue:
            actions.append(f"{label}: {issue}")
    calculation = item["financial"]["calculation"]
    if calculation["missing_inputs"]:
        actions.append("Complete V4 economics: " + ", ".join(calculation["missing_inputs"]))
    actions.extend(calculation["reasons"])
    if not item["demand"] or not item["demand"]["current_eligible"]:
        actions.append(
            (
                "Research demand: review exact market queries; sparse or stale evidence is "
                "inconclusive."
            )
        )
    if not actions:
        actions.append(
            (
                "Investigate product quality and fit; review evidence and assumptions before "
                "deciding on samples."
            )
        )
    return list(dict.fromkeys(actions))


def comparison_workspace(results, repo, *, group=None, now=None):
    document = comparison_document(results, repo, now=now)
    document["schema"] = "ai-commerce-v5-comparison-1"
    document["group"] = group.model_dump(mode="json") if group else None
    storage = DiscoveryRepository(repo)
    for item, result in zip(document["products"], results, strict=True):
        item["discovery_origin"] = (
            origin.model_dump(mode="json")
            if (origin := storage.get_origin(result.product.id))
            else None
        )
        plan = get_query_plan(repo, result.product, item["destination"]["country"])
        item["query_plan"] = plan.model_dump(mode="json") if plan else None
        item["query_evidence"] = []
        service = DemandIntelligenceService(repo, **({"clock": lambda: now} if now else {}))
        for term in plan.terms if plan else []:
            snapshot = service.get_current(
                result.product, Destination.model_validate(item["destination"]), query=term.query
            )
            if snapshot:
                item["query_evidence"].append(snapshot.model_dump(mode="json"))
        item["next_actions"] = next_actions(item)
    signatures = [_signature(item) for item in document["products"]]
    issues = []
    for field in signatures[0] if signatures else {}:
        if len({json.dumps(s[field], sort_keys=True) for s in signatures}) > 1:
            issues.append(f"Different {field}: align assumptions before direct comparison.")
    for item in document["products"]:
        calc = item["financial"]["calculation"]
        if calc["missing_inputs"] or calc["reasons"]:
            issues.append(f"{item['product']['name']}: incomplete or ineligible economic scenario.")
    document["comparability"] = {
        "directly_comparable": len(signatures) >= 2 and not issues,
        "issues": issues,
        "scenario_signatures": signatures,
    }
    document["prioritization"] = {
        "winner": None,
        "basis": (
            "V4 scores retain their evidence gates; missing inputs are unknown. Resolve "
            "next actions before prioritizing. No guaranteed winner."
        ),
    }
    document["semantics"]["query_series"] = (
        "Separately normalized relative indices are not absolute demand. Never add or"
        " directly compare index magnitudes across queries or candidates. Additional "
        "queries are exploratory and do not replace the original product or its V4 "
        "score query."
    )
    return document


def workspace_rows(document):
    """Reuse V4 values while keeping scenario money separate from observed supplier USD."""
    rows = comparison_rows(document)
    for row, item in zip(rows, document["products"], strict=True):
        for key in list(row):
            if "USD" in key:
                row[key.replace("USD", "scenario currency")] = row.pop(key)
        row["Scenario currency"] = item["financial"]["snapshot"]["currency"]
        row["Evidence kind"] = (item["discovery_origin"] or {}).get(
            "evidence_kind", "legacy/manual"
        )
        selected = item["selection"]
        offer = selected["offer"] if selected else None
        variant, quote, stock = (
            (offer["variant"], offer["quote"], offer["stock"]) if offer else (None, None, None)
        )
        row["Observed variant cost"] = (
            f"{variant['currency']} {variant['unit_price']}"
            if variant and variant["unit_price"] is not None
            else None
        )
        row["Freight total"] = (
            f"{quote['currency']} {quote['total_cost']}"
            if quote and quote["total_cost"] is not None
            else None
        )
        row["Delivery estimate days"] = (
            f"{quote['delivery_min_days']}–{quote['delivery_max_days']}"
            if quote
            and quote["delivery_min_days"] is not None
            and quote["delivery_max_days"] is not None
            else None
        )
        row["Warehouse / storage"] = (
            f"{stock['warehouse_id']} / {stock['storage_id']}" if stock else None
        )
    return rows
