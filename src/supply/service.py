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
    normalize_limit_stage,
)


class SupplierIntelligenceService:
    def __init__(self, repo, provider=None):
        self.repo = repo if isinstance(repo, SupplyRepository) else SupplyRepository(repo)
        self.provider = provider or CJDropShippingProvider()

    def recheck_saved(self, product, destination):
        """Explicit local matching only; never refresh provider observations or choices."""
        report = self.repo.get_report(product.id)
        if report is None:
            return None
        report.offers = [
            offer.model_copy(update={"match": self.match_offer(product, offer, destination)})
            for offer in report.offers
        ]
        report.input_fingerprint = product_fingerprint(product)
        # Keep the collection destination/time, stages and provider telemetry intact.
        # Quote applicability is still checked against the current destination separately.
        self.repo.save_report(report)
        return report

    def match_offer(self, product, offer, destination):
        return match_supplier(
            product,
            offer.candidate,
            offer.variant,
            destination,
            requirements=self.repo.get_requirements(product.id),
        )

    def shipping_request_issue(self, product, destination, *, demo=False, require_provider=True):
        from src.supply.economics import fresh, selection_issue, stock_issue

        if demo:
            return "Demo Mode disables shipping requests."
        if require_provider and not getattr(self.provider, "configured", False):
            return "CJ credentials are missing. Configure CJ before requesting live freight."
        selection = self.repo.get_selection(product.id)
        if issue := selection_issue(selection, destination):
            return issue
        report = self.repo.get_report(product.id)
        if not report or report.input_fingerprint != product_fingerprint(product):
            return "Saved supplier inputs changed; recheck saved offers locally."
        current = next(
            (
                o
                for o in report.offers
                if o.candidate.id == selection.offer.candidate.id
                and o.variant.id == selection.offer.variant.id
                and o.stock
                and selection.offer.stock
                and o.stock.id == selection.offer.stock.id
            ),
            None,
        )
        if current is None:
            return "Selected variant or warehouse is historical; select a current observation."
        if (
            current.match != selection.offer.match
            or self.match_offer(product, current, destination) != current.match
        ):
            return "Target requirements changed; recheck and explicitly select a compatible offer."
        if issue := stock_issue(selection, destination, utc_now(), report.stages):
            return issue + " Refresh only the needed stock evidence before quoting."
        if not fresh(current.variant.observed_at, 24, utc_now()):
            return "Selected variant/parcel evidence is stale."
        if not current.stock.storage_id or not current.stock.country:
            return "Shipping requires an observed subwarehouse and origin country."
        return None

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
        if outcome.limit_source:
            stage["limit_source"] = outcome.limit_source
        if outcome.retry_blocked_by:
            stage["retry_blocked_by"] = outcome.retry_blocked_by
        stage = normalize_limit_stage(stage)
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
        run = ActionTelemetry(
            action=action, started_at=utc_now(), **({"action_id": action_id} if action_id else {})
        )
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
                match = match_supplier(
                    product,
                    candidate,
                    variant,
                    destination,
                    requirements=self.repo.get_requirements(product.id),
                )
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
                "shipping_state": "NOT_REQUESTED",
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
                    o.candidate.id,
                    o.variant.id,
                    o.stock.id if o.stock else None,
                )
                == (
                    selection.offer.candidate.id,
                    selection.offer.variant.id,
                    selection.offer.stock.id if selection.offer.stock else None,
                )
            ),
            None,
        )
        issue = self.shipping_request_issue(product, destination, demo=demo)
        if issue or current is None:
            run.stages.append(
                {
                    "component": "shipping",
                    "provider": self.provider.name,
                    "status": "UNAVAILABLE",
                    "pending": True,
                    "shipping_state": "BLOCKED",
                    "notice": issue or "Selected supplier observation is historical.",
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
        parsed_status = run.stages[-1]["status"]
        run.stages[-1]["shipping_state"] = (
            "SUCCESS"
            if applicable
            else "EMPTY"
            if parsed_status in {"SUCCESS", "SUCCESS_EMPTY"}
            else "FAILED"
        )
        if result.status == "SUCCESS" and quotes and not applicable:
            run.stages[-1].update(
                shipping_state="BLOCKED",
                partial=True,
                notice="Returned quotes do not match the selected variant/warehouse/destination.",
            )
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
        if parsed_status in {"SUCCESS", "SUCCESS_EMPTY"}:
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
            or not any(
                o.candidate.id == selection.offer.candidate.id
                and o.variant.id == selection.offer.variant.id
                and (o.stock.id if o.stock else None)
                == (selection.offer.stock.id if selection.offer.stock else None)
                and o.match == selection.offer.match
                for o in report.offers
            )
            or self.match_offer(
                product,
                selection.offer,
                self.repo.get_settings(product.id) or report.destination,
            )
            != selection.offer.match
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
        elif selection and not any(o.id == selection.offer.id for o in report.offers):
            stages.append(
                {
                    "component": "shipping",
                    "provider": selection.offer.variant.provider,
                    "status": "UNAVAILABLE",
                    "notice": "Choose a current quote explicitly; product cost stays independent.",
                }
            )
        return stages
