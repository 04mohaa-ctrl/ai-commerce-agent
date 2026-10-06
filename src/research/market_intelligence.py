"""Compose V3 into the shared V2 research action; provider failures remain independent."""

import hashlib
import json
import time
from datetime import timedelta

from src.database.market_repository import MarketIntelligenceRepository
from src.research.market_models import MarketIntelligenceReport
from src.research.market_scoring import score_market_report
from src.research.models import ResearchReport, utc_now
from src.research.providers.base import product_fingerprint
from src.research.providers.demand_trend import DataForSEOTrendProvider, DemandResult
from src.research.providers.page_verification import PageVerificationProvider
from src.research.providers.retail_prices import (
    MarketPriceObservation,
    extract_market_prices,
    summarize_prices,
)
from src.research.telemetry import ProviderAttempt, RunTelemetry
from src.research.trends import calculate_trend
from src.research.verification import ClaimVerification, PageVerification, publisher_domain
from src.services.market_economics import MarketEconomicsInputs, calculate_market_economics


class MarketIntelligenceService:
    def __init__(
        self, repo, page_provider=None, demand_provider=None, price_loader=extract_market_prices
    ):
        self.repo = (
            repo
            if isinstance(repo, MarketIntelligenceRepository)
            else MarketIntelligenceRepository(repo)
        )
        self.page_provider = page_provider or PageVerificationProvider()
        self.demand_provider = demand_provider or DataForSEOTrendProvider()
        self.price_loader = price_loader

    def research_product(
        self, product, evidence_service, *, force=False, refresh_web=False, progress=None
    ):
        run = RunTelemetry(model=evidence_service.model)
        fingerprint = product_fingerprint(product)
        prior = self.repo.get_report(product.id)
        if prior and prior.input_fingerprint != fingerprint:
            prior = None

        def update(message):
            if progress:
                progress(message)

        def stage(name, provider, status, notice="", retained=False):
            run.stages.append(
                ProviderAttempt(
                    stage=name, provider=provider, status=status, notice=notice, retained=retained
                )
            )
            if status == "CACHED":
                run.cache_hits.append(name)

        if evidence_service.force_demo or not evidence_service.api_key:
            result = evidence_service.research_product(product, force=True, progress=progress)
            for name in ("web", "page verification", "demand", "prices"):
                stage(
                    name, "", "DISABLED", "Demo Mode or missing OpenAI key; no external requests."
                )
            run.completed_at = utc_now()
            self.repo.save_run(product.id, run)
            return result

        cached = evidence_service.repository.get_research(product.id)
        failure_key = f"web-failure-v3:{fingerprint}"
        failed_attempt = self.repo.get_cache(failure_key)
        cached_failure = (
            not (force or refresh_web)
            and failed_attempt
            and utc_now() - failed_attempt.collected_at < timedelta(hours=1)
        )
        if (
            cached_failure
            and cached
            and cached.status != "failed"
            and cached.mode == "web"
            and cached.input_fingerprint == fingerprint
            and cached.researched_at > failed_attempt.collected_at
        ):
            cached_failure = False
        use_cached = (
            not (force or refresh_web)
            and cached
            and cached.mode == "web"
            and cached.status != "failed"
            and cached.input_fingerprint == fingerprint
            and utc_now() - cached.researched_at < timedelta(days=1)
        )
        if cached_failure:
            result = ResearchReport.model_validate(failed_attempt.payload)
            stage(
                "web",
                result.provider,
                "CACHED",
                "Cached failed web attempt; automatic retries suppressed for one hour.",
            )
        elif use_cached:
            result = cached
            stage("web", cached.provider, "CACHED")
            update("Using cached web evidence…")
        else:
            provider = evidence_service.provider
            old_callback = getattr(provider, "telemetry", None)
            old_prices = getattr(provider, "price_loader", None)
            # Reuse existing search/classification; all V3 page/price reads use safe HTTP.
            if hasattr(provider, "telemetry"):
                provider.telemetry = run.record
            if hasattr(provider, "price_loader"):
                provider.price_loader = lambda *args: []
            try:
                result = evidence_service.research_product(product, force=True, progress=progress)
            finally:
                if hasattr(provider, "telemetry"):
                    provider.telemetry = old_callback
                if hasattr(provider, "price_loader"):
                    provider.price_loader = old_prices
            stage(
                "web",
                result.provider,
                "FAILED"
                if result.status == "failed"
                else "SUCCESS"
                if result.status == "completed"
                else "PARTIAL"
                if result.sources
                else "UNAVAILABLE",
                result.notice,
            )
            if result.status == "failed":
                self.repo.save_cache(failure_key, result.model_dump(mode="json"), utc_now())
        stored = evidence_service.repository.get_research(product.id)
        web = stored if stored and stored.input_fingerprint == fingerprint else result
        if (
            result.status in {"failed", "insufficient"}
            and web.sources
            and web.researched_at != result.researched_at
        ):
            run.stages[-1].retained = True

        pages, prices = [], []
        page_start = getattr(self.page_provider, "request_count", 0)
        fetch_start = getattr(self.page_provider, "source_fetch_count", 0)
        started = time.monotonic()
        update("Verifying source pages…")
        for source in web.sources[:6]:
            claims = list(dict.fromkeys(f.claim for f in web.findings if source.id in f.source_ids))
            if not claims:
                claims = [source.what_claim_it_supports]
            claim_hash = hashlib.sha256(json.dumps(claims).encode()).hexdigest()
            key = f"page-v3:{fingerprint}:{source.id}:{claim_hash}"
            cached_page = self.repo.get_cache(key)
            page, observed = None, []
            if cached_page:
                successful = cached_page.payload.get("verification", {}).get("fetched", False)
                ttl = timedelta(days=1) if successful else timedelta(hours=1)
                if not force and utc_now() - cached_page.collected_at < ttl:
                    page = PageVerification.model_validate(cached_page.payload["verification"])
                    observed = [
                        MarketPriceObservation.model_validate(p)
                        for p in cached_page.payload.get("prices", [])
                    ]
                    run.cache_hits.append(f"page:{source.id}")
            if page is None:
                try:
                    remaining = 60 - (time.monotonic() - started)
                    if remaining <= 0:
                        raise TimeoutError
                    fetcher = getattr(self.page_provider, "fetcher", None)
                    old_timeout = getattr(fetcher, "total_timeout", None)
                    if old_timeout is not None:
                        fetcher.total_timeout = min(old_timeout, remaining)
                    try:
                        fetched = self.page_provider.verify(source, claims)
                    finally:
                        if old_timeout is not None:
                            fetcher.total_timeout = old_timeout
                    page = fetched.verification
                    if fetched.html and page.fetched:
                        # Observation time is the actual page access, not the web-search time.
                        listing_source = source.model_copy(
                            update={"url": page.canonical_url, "accessed_at": page.accessed_at}
                        )
                        try:
                            observed = self.price_loader(fetched.html, product, listing_source)
                            observed = [
                                p.model_copy(update={"source_id": source.id}) for p in observed
                            ]
                        except Exception:
                            stage(
                                "prices",
                                "structured Product/Offer metadata",
                                "FAILED",
                                "Price metadata parsing failed; other evidence was retained.",
                            )
                    self.repo.save_cache(
                        key,
                        {
                            "verification": page.model_dump(mode="json"),
                            "prices": [p.model_dump(mode="json") for p in observed],
                        },
                        page.accessed_at,
                    )
                except Exception:
                    page = PageVerification(
                        source_id=source.id,
                        canonical_url=source.url,
                        publisher=publisher_domain(source.url),
                        accessed_at=utc_now(),
                        classification_reason="Source-page retrieval unavailable.",
                        claims=[
                            ClaimVerification(claim=c, status="SOURCE_UNAVAILABLE") for c in claims
                        ],
                    )
            if not page.fetched and prior:
                previous = next(
                    (p for p in prior.page_verifications if p.source_id == source.id and p.fetched),
                    None,
                )
                if previous:
                    stage(
                        f"page:{source.id}",
                        "safe-page-verification",
                        "UNAVAILABLE",
                        "Latest page attempt unavailable; previous dated support retained.",
                        True,
                    )
                    page = previous
                    observed = [p for p in prior.price_observations if p.source_id == source.id]
            pages.append(page)
            prices.extend(observed)
        run.page_request_count = max(
            0, getattr(self.page_provider, "request_count", 0) - page_start
        )
        run.page_fetch_count = max(
            0, getattr(self.page_provider, "source_fetch_count", 0) - fetch_start
        )
        if run.page_request_count:
            run.providers_used.append("Public HTTPS pages")
        stage(
            "page verification",
            "safe-page-verification",
            "SUCCESS"
            if pages and all(p.fetched for p in pages)
            else "PARTIAL"
            if any(p.fetched for p in pages)
            else "UNAVAILABLE",
            "Page support confirms publisher attribution, not objective truth.",
        )
        if len(web.sources) > 6:
            stage(
                "page budget",
                "safe-page-verification",
                "UNAVAILABLE",
                "Only the first six cited pages were attempted in this bounded run.",
            )
        update("Checking demand signals…")
        name = self.demand_provider.name
        location = getattr(self.demand_provider, "location", "United States (2840)")
        key = f"demand-v3:{fingerprint}:{name}:{location}"
        entry = self.repo.get_cache(key)
        demand = None
        if entry and not force:
            ttl = (
                timedelta(days=7)
                if entry.payload.get("status") == "completed"
                else timedelta(hours=1)
            )
            if utc_now() - entry.collected_at < ttl:
                demand = DemandResult.model_validate(entry.payload)
                stage("demand", name, "CACHED", demand.notice)
        if demand is None:
            count = getattr(self.demand_provider, "request_count", 0)
            try:
                demand = self.demand_provider.collect(product)
            except Exception:
                demand = DemandResult(
                    provider=name,
                    query=product.name,
                    location=location,
                    status="failed",
                    notice="Measured demand request failed; other stages were retained.",
                )
            run.demand_requests = max(0, getattr(self.demand_provider, "request_count", 0) - count)
            if run.demand_requests:
                run.providers_used.append(name)
            stage(
                "demand",
                name,
                "SUCCESS"
                if demand.status == "completed"
                else "FAILED"
                if demand.status == "failed"
                else "UNAVAILABLE",
                demand.notice,
            )
            self.repo.save_cache(key, demand.model_dump(mode="json"), demand.collected_at)
        if demand.status != "completed" and prior and prior.demand.status == "completed":
            run.stages[-1].retained = True
            demand = prior.demand
        trend = calculate_trend(demand.observations)
        update("Collecting compatible price observations…")
        if not prices and prior:
            valid_ids = {s.id for s in web.sources}
            prices = [p for p in prior.price_observations if p.source_id in valid_ids]
            if prices:
                stage(
                    "prices retained",
                    "structured Product/Offer metadata",
                    "UNAVAILABLE",
                    "Previous listing observations retained with original dates.",
                    True,
                )
        summaries = summarize_prices(prices)
        stage(
            "prices",
            "structured Product/Offer metadata",
            "SUCCESS" if any(p.minimum is not None for p in summaries) else "UNAVAILABLE",
            "" if summaries else "Insufficient price observations",
        )
        inputs = self.repo.get_economics(product.id) or MarketEconomicsInputs(
            unit_product_cost=product.cost, selling_price=product.selling_price
        )
        economics = calculate_market_economics(inputs)
        update("Calculating market score…")
        score = score_market_report(web, pages, demand, trend, summaries, economics)
        run.completed_at = utc_now()
        report = MarketIntelligenceReport(
            product_id=product.id,
            product_name=product.name,
            input_fingerprint=fingerprint,
            web_evidence=web,
            page_verifications=pages,
            demand=demand,
            trend=trend,
            price_observations=prices,
            price_summaries=summaries,
            economics_inputs=inputs,
            economics_result=economics,
            score=score,
            telemetry=run,
            risk_flags=list(
                dict.fromkeys(
                    score.missing
                    + [
                        s.notice
                        for s in run.stages
                        if s.status in {"FAILED", "UNAVAILABLE"} and s.notice
                    ]
                )
            ),
        )
        self.repo.save_report(report)
        self.repo.save_run(product.id, run)
        return result

    def recalculate(self, product):
        report = self.repo.get_report(product.id)
        if not report or report.input_fingerprint != product_fingerprint(product):
            return None
        inputs = self.repo.get_economics(product.id) or report.economics_inputs
        economics = calculate_market_economics(inputs)
        report.economics_inputs, report.economics_result = inputs, economics
        report.trend = calculate_trend(report.demand.observations)
        report.score = score_market_report(
            report.web_evidence,
            report.page_verifications,
            report.demand,
            report.trend,
            report.price_summaries,
            economics,
        )
        report.risk_flags = list(
            dict.fromkeys(
                report.score.missing
                + [
                    stage.notice
                    for stage in report.telemetry.stages
                    if stage.status in {"FAILED", "UNAVAILABLE"} and stage.notice
                ]
            )
        )
        return report
