"""Explicit supplier actions with independent caches and honest current/history states."""

import hashlib
import json
import time
from datetime import timedelta

from pydantic import ValidationError

from src.database.supply_repository import SupplyRepository
from src.research.models import utc_now
from src.research.providers.base import product_fingerprint
from src.supply.cj_provider import CJDropShippingProvider
from src.supply.matching import candidate_viable, match_supplier
from src.supply.models import (
    ActionTelemetry,
    ProviderOutcome,
    ShippingQuote,
    StockObservation,
    SupplierOffer,
    SupplierProductCandidate,
    SupplierVariant,
    SupplyIntelligenceReport,
)


class SupplierIntelligenceService:
    def __init__(self, repo, provider=None):
        self.repo = repo if isinstance(repo, SupplyRepository) else SupplyRepository(repo)
        self.provider = provider or CJDropShippingProvider()

    def _component(self, product, destination, component, parameters, call, force, run):
        identity = [
            "supply-v4",
            product_fingerprint(product),
            self.provider.name,
            getattr(self.provider, "cache_context", "unavailable"),
            component,
            destination.model_dump(mode="json"),
            parameters,
        ]
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        outcome = self.repo.get_cache(key)
        cached = False
        if outcome is not None and not force:
            hours = 6 if component in {"stock", "shipping"} else 24
            if outcome.status not in {"SUCCESS", "SUCCESS_EMPTY"}:
                hours = 1
            age = utc_now() - outcome.observed_at
            cached = timedelta(0) <= age < timedelta(hours=hours)
            if cached and component == "shipping":
                expiries = [r.get("expires_at") for r in outcome.records if r.get("expires_at")]
                from datetime import datetime

                cached = all(utc_now() < datetime.fromisoformat(value) for value in expiries)
        if not cached:
            try:
                outcome = call()
            except Exception:
                outcome = ProviderOutcome(
                    status="FAILED",
                    notice="Supplier component unavailable; no raw error payload retained.",
                )
            self.repo.save_cache(key, outcome)
        else:
            run.cache_hits.append(component)
        stage = {
            "component": component,
            "provider": self.provider.name,
            "status": outcome.status,
            "observed_at": outcome.observed_at.isoformat(),
            "partial": outcome.partial,
            "rejected": outcome.rejected,
            "cached": cached,
            "notice": outcome.notice,
            **parameters,
        }
        run.stages.append(stage)
        return outcome

    @staticmethod
    def _records(outcome, model, run):
        records = []
        for payload in outcome.records:
            try:
                records.append(model.model_validate(payload))
            except (ValidationError, ValueError, TypeError):
                run.stages[-1]["partial"] = True
                run.stages[-1]["rejected"] += 1
        if outcome.records and not records:
            run.stages[-1]["status"] = "FAILED"
            run.stages[-1]["notice"] = "Returned supplier records could not be validated."
        return records

    def _start(self, product, action, action_id=None, max_requests=12):
        run = ActionTelemetry(action=action, **({"action_id": action_id} if action_id else {}))
        if not self.repo.claim_action(run.action_id, product.id):
            return None
        self.provider.reset_action(run, max_requests=max_requests, max_seconds=90)
        return run

    def _finish(self, report, run, started):
        run.completed_at = utc_now()
        run.elapsed_seconds = max(0, time.monotonic() - started)
        report.telemetry = run
        report.stages = list(run.stages)
        self.repo.save_report(report)
        self.repo.save_action(report.product_id, run)
        return report

    def research(self, product, destination, *, force=False, demo=False, action_id=None):
        prior = self.repo.get_report(product.id)
        fingerprint = product_fingerprint(product)
        if prior and (prior.input_fingerprint != fingerprint or prior.destination != destination):
            prior = None
        run = self._start(product, "supplier", action_id)
        if run is None:
            return self.repo.get_report(product.id)
        started = time.monotonic()
        report = SupplyIntelligenceReport(
            product_id=product.id, input_fingerprint=fingerprint, destination=destination
        )
        if demo:
            run.stages.append(
                {
                    "component": "search",
                    "provider": self.provider.name,
                    "status": "UNAVAILABLE",
                    "notice": "Demo Mode disables external supplier requests.",
                }
            )
            report.offers = prior.offers if prior else []
            return self._finish(report, run, started)
        search = self._component(
            product,
            destination,
            "search",
            {"query": product.name},
            lambda: self.provider.search(product.name, page=1, size=10),
            force,
            run,
        )
        candidates = self._records(search, SupplierProductCandidate, run)
        if search.status not in {"SUCCESS", "SUCCESS_EMPTY"} or (search.records and not candidates):
            report.offers = prior.offers if prior else []
            run.stages[-1]["retained"] = bool(report.offers)
            return self._finish(report, run, started)
        # One conservative page; at most three products / two variants each.
        unique = {c.product_id: c for c in candidates if candidate_viable(product, c)}
        for candidate in list(unique.values())[:3]:
            details = self._component(
                product,
                destination,
                "details",
                {"product_id": candidate.product_id},
                lambda c=candidate: self.provider.details(c.product_id),
                force,
                run,
            )
            detail_records = self._records(details, SupplierProductCandidate, run)
            if detail_records:
                candidate = next(
                    (c for c in detail_records if c.product_id == candidate.product_id), candidate
                )
            variants = self._component(
                product,
                destination,
                "variants",
                {"product_id": candidate.product_id},
                lambda c=candidate: self.provider.variants(c.product_id),
                force,
                run,
            )
            variant_records = self._records(variants, SupplierVariant, run)
            if variants.status not in {"SUCCESS", "SUCCESS_EMPTY"}:
                if prior:
                    report.offers.extend(
                        o for o in prior.offers if o.candidate.product_id == candidate.product_id
                    )
                    run.stages[-1]["retained"] = True
                continue
            seen = set()
            enriched = 0
            for variant in variant_records:
                if (
                    variant.variant_id in seen
                    or variant.product_id != candidate.product_id
                    or variant.provider != candidate.provider
                ):
                    continue
                seen.add(variant.variant_id)
                match = match_supplier(product, candidate, variant, destination)
                if match.outcome == "NO_MATCH":
                    report.offers.append(
                        SupplierOffer(candidate=candidate, variant=variant, match=match)
                    )
                    continue
                if enriched >= 2:
                    break
                enriched += 1
                stock_result = self._component(
                    product,
                    destination,
                    "stock",
                    {"product_id": variant.product_id, "variant_id": variant.variant_id},
                    lambda v=variant: self.provider.stock(v.variant_id, product_id=v.product_id),
                    force,
                    run,
                )
                stocks = self._records(stock_result, StockObservation, run)
                stocks = [
                    s
                    for s in stocks
                    if (s.provider, s.product_id, s.variant_id)
                    == (variant.provider, variant.product_id, variant.variant_id)
                ]
                if stock_result.status not in {"SUCCESS", "SUCCESS_EMPTY"} and prior:
                    stocks = [
                        o.stock
                        for o in prior.offers
                        if o.variant.variant_id == variant.variant_id and o.stock
                    ]
                    run.stages[-1]["retained"] = bool(stocks)
                for stock in stocks or [None]:
                    report.offers.append(
                        SupplierOffer(
                            candidate=candidate, variant=variant, stock=stock, match=match
                        )
                    )
        run.stages.append(
            {
                "component": "shipping",
                "provider": self.provider.name,
                "status": "UNAVAILABLE",
                "pending": True,
                "notice": "Select an offer explicitly, then Refresh shipping.",
            }
        )
        return self._finish(report, run, started)

    def refresh_shipping(self, product, destination, *, demo=False, action_id=None):
        report = self.repo.get_report(product.id)
        if report is None:
            return None
        run = self._start(product, "shipping", action_id, max_requests=4)
        if run is None:
            return report
        started = time.monotonic()
        run.stages = [s for s in report.stages if s.get("component") != "shipping"]
        selection = self.repo.get_selection(product.id)
        current = next(
            (
                o
                for o in report.offers
                if selection
                and (
                    o.variant.provider,
                    o.variant.variant_id,
                    o.stock.storage_id if o.stock else None,
                )
                == (
                    selection.offer.variant.provider,
                    selection.offer.variant.variant_id,
                    selection.offer.stock.storage_id if selection.offer.stock else None,
                )
            ),
            None,
        )
        from src.supply.economics import selection_issue

        if (
            demo
            or report.input_fingerprint != product_fingerprint(product)
            or current is None
            or current.stock is None
            or selection_issue(selection, destination)
        ):
            run.stages.append(
                {
                    "component": "shipping",
                    "provider": self.provider.name,
                    "status": "UNAVAILABLE",
                    "pending": True,
                    "notice": "A current compatible selected variant and warehouse are required; "
                    "Demo Mode makes no requests.",
                }
            )
            return self._finish(report, run, started)
        params = {
            "product_id": current.variant.product_id,
            "variant_id": current.variant.variant_id,
            "warehouse_id": current.stock.warehouse_id,
            "storage_id": current.stock.storage_id,
            "variant_snapshot": current.variant.id,
            "stock_snapshot": current.stock.id,
        }
        result = self._component(
            product,
            destination,
            "shipping",
            params,
            lambda: self.provider.shipping(current.variant, current.stock, destination),
            True,
            run,
        )
        quotes = self._records(result, ShippingQuote, run)
        applicable = [
            q
            for q in quotes
            if q.destination == destination
            and q.variant_id == current.variant.variant_id
            and q.storage_id == current.stock.storage_id
            and q.warehouse_id == current.stock.warehouse_id
            and q.provider == current.variant.provider
            and q.product_id == current.variant.product_id
        ]
        # A refreshed warehouse cohort may contain multiple shipping methods.
        # Replace all of them together; successful empty invalidates every old quote.
        others = [
            o
            for o in report.offers
            if (
                o.variant.provider,
                o.variant.product_id,
                o.variant.variant_id,
                o.stock.warehouse_id if o.stock else None,
                o.stock.storage_id if o.stock else None,
            )
            != (
                current.variant.provider,
                current.variant.product_id,
                current.variant.variant_id,
                current.stock.warehouse_id,
                current.stock.storage_id,
            )
        ]
        if result.status in {"SUCCESS", "SUCCESS_EMPTY"}:
            report.offers = others + (
                [current.model_copy(update={"quote": q}) for q in applicable]
                if applicable
                else [current.model_copy(update={"quote": None})]
            )
        else:
            run.stages[-1]["retained"] = current.quote is not None
        report.destination = destination
        return self._finish(report, run, started)

    def current_stages(self, product):
        report = self.repo.get_report(product.id)
        stages = list(report.stages) if report else []
        selection = self.repo.get_selection(product.id)
        changed_inputs = report and report.input_fingerprint != product_fingerprint(product)
        if selection and (
            changed_inputs
            or not report
            or not any(o.id == selection.offer.id for o in report.offers)
        ):
            for component in ("match", "search", "details", "variants", "stock", "shipping"):
                stages.append(
                    {
                        "component": component,
                        "provider": selection.offer.variant.provider,
                        "status": "UNAVAILABLE",
                        "notice": "Selected snapshot is historical or describes changed inputs; "
                        "adopt updated observations explicitly.",
                    }
                )
        return stages
