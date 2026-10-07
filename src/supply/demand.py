"""Explicit demand actions and read-only V4 eligibility over historical V3 evidence."""

import hashlib
import json
import time
from datetime import date, timedelta

from pydantic import Field, ValidationError

from src.database.market_repository import MarketIntelligenceRepository
from src.database.supply_repository import SupplyRepository
from src.research.market_scoring import score_market_report
from src.research.models import utc_now
from src.research.providers.base import product_fingerprint
from src.research.providers.demand_trend import (
    DataForSEOTrendProvider,
    DemandResult,
    UnavailableDemandProvider,
)
from src.research.providers.retail_prices import MarketPriceObservation, summarize_prices
from src.research.telemetry import ProviderAttempt
from src.research.trends import TrendResult, calculate_trend
from src.supply.models import ActionTelemetry, ProviderOutcome, SupplyModel

# Country rows verified in the official supported-location CSV linked from:
# https://docs.dataforseo.com/v3/keywords_data-dataforseo_trends-locations/
# https://cdn.dataforseo.com/v3/locations/locations_dataforseo_trends_2026_09_01.csv
DEMAND_COUNTRIES = {
    "US": (2840, "United States"),
    "GB": (2826, "United Kingdom"),
    "SE": (2752, "Sweden"),
    "DE": (2276, "Germany"),
    "FR": (2250, "France"),
}


def demand_provider_for(destination, *, clock=utc_now):
    """Construct the existing opt-in adapter for a verified country, without requests."""
    setting = DEMAND_COUNTRIES.get(destination.country)
    if setting is None:
        return UnavailableDemandProvider()
    code, name = setting
    return DataForSEOTrendProvider(clock=clock, location_code=code, location_name=name)


def _query(value):
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        raise ValueError("Demand query requires visible plain text.")
    value = " ".join(value.split())
    if not value or len(value) > 120:
        raise ValueError("Demand query must contain 1–120 characters.")
    return value


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _location(country):
    setting = DEMAND_COUNTRIES.get(country)
    return f"{setting[1]} ({setting[0]})" if setting else f"Unsupported country ({country})"


def _closed_dates(collected_at):
    try:
        first = collected_at.date().replace(year=collected_at.year - 1)
    except ValueError:
        first = date(collected_at.year - 1, 2, 28)
    return first, collected_at.date() - timedelta(days=1)


class DemandSnapshot(SupplyModel):
    product_id: str
    input_fingerprint: str
    country: str
    query: str
    provider: str
    location: str
    request_context: str
    period_start: date
    period_end: date
    outcome: ProviderOutcome
    demand: DemandResult
    trend: TrendResult = Field(default_factory=TrendResult)
    telemetry: ActionTelemetry
    retained: bool = False
    current_eligible: bool = False


class DemandIntelligenceService:
    def __init__(self, repo, provider=None, clock=utc_now):
        self.repo = repo if isinstance(repo, SupplyRepository) else SupplyRepository(repo)
        self.provider, self.clock = provider, clock

    @staticmethod
    def _current_key(product, destination, query):
        return "demand-current-v4:" + _hash(
            [product.id, product_fingerprint(product), destination.country, query.casefold()]
        )

    def _stored(self, product, destination, query):
        record = self.repo.get_cache(self._current_key(product, destination, query))
        if record and record.records:
            return DemandSnapshot.model_validate(record.records[0])
        return None

    def get_current(self, product, destination, *, query=None):
        """Read and recheck freshness locally; do not create providers or rewrite timestamps."""
        query = _query(product.name if query is None else query)
        snapshot = self._stored(product, destination, query)
        if snapshot is None:
            return None
        snapshot = snapshot.model_copy(deep=True)
        age = self.clock() - snapshot.demand.collected_at
        snapshot.current_eligible = (
            snapshot.outcome.status == "SUCCESS"
            and not snapshot.retained
            and timedelta(0) <= age < timedelta(days=7)
            and snapshot.demand.status == "completed"
            and any(not o.missing and o.value is not None for o in snapshot.demand.observations)
            and all(
                timedelta(0) <= self.clock() - o.collected_at < timedelta(days=7)
                for o in snapshot.demand.observations
            )
        )
        snapshot.trend = (
            calculate_trend(snapshot.demand.observations, now=self.clock())
            if snapshot.current_eligible
            else TrendResult(notes=["Measured demand is unavailable, historical or stale."])
        )
        return snapshot

    current = get_current

    @staticmethod
    def _compatible(result, provider, query, location):
        return (
            result.provider == provider
            and result.query.casefold().split() == query.casefold().split()
            and result.location == location
            and all(
                o.provider == provider
                and o.query.casefold().split() == query.casefold().split()
                and o.location == location
                for o in result.observations
            )
        )

    def _legacy_cached(self, product, provider, query, location, now):
        if query.casefold().split() != product.name.casefold().split():
            return None
        market = MarketIntelligenceRepository(self.repo.repository)
        entry = market.get_cache(
            f"demand-v3:{product_fingerprint(product)}:{provider.name}:{location}"
        )
        if entry is None:
            return None
        try:
            result = DemandResult.model_validate(entry.payload)
        except ValidationError:
            return None
        ttl = timedelta(days=7) if result.status == "completed" else timedelta(hours=1)
        if not (
            timedelta(0) <= now - entry.collected_at < ttl
            and self._compatible(result, provider.name, query, location)
        ):
            return None
        # Disabled V3 attempts cannot suppress a newly configured paid provider.
        if result.status == "unavailable" and getattr(provider, "enabled", True):
            run = market.latest_run(product.id)
            if not run or not run.demand_requests:
                return None
        return result

    def refresh(self, product, destination, *, query=None, force=False, demo=False, action_id=None):
        query = _query(product.name if query is None else query)
        now, started = self.clock(), time.monotonic()
        run = ActionTelemetry(
            action="demand", started_at=now, **({"action_id": action_id} if action_id else {})
        )
        if not self.repo.claim_action(run.action_id, product.id):
            return self.get_current(product, destination, query=query)
        provider = self.provider or demand_provider_for(destination, clock=self.clock)
        name = provider.name if provider else "dataforseo_trends"
        location = _location(destination.country)
        context = _hash(
            [
                "demand-v4",
                product_fingerprint(product),
                name,
                getattr(provider, "cache_context", bool(getattr(provider, "enabled", True))),
                query.casefold(),
                destination.country,
                location,
                "web",
                "relative_popularity_index",
                "closed_previous_calendar_year",
                bool(demo),
            ]
        )
        prior = self._stored(product, destination, query)
        if prior and not self._compatible(prior.demand, name, query, location):
            prior = None
        first, end = _closed_dates(now)
        result, outcome, cached = None, None, False
        requests = 0
        legacy = None
        if (
            not force
            and not demo
            and destination.country in DEMAND_COUNTRIES
            and getattr(provider, "enabled", True)
            and getattr(provider, "location", location) == location
        ):
            legacy = self._legacy_cached(product, provider, query, location, now)
        newer_legacy = legacy and prior and legacy.collected_at > prior.outcome.observed_at
        if (
            not force
            and not demo
            and prior
            and prior.request_context == context
            and not newer_legacy
        ):
            ttl = (
                timedelta(days=7)
                if prior.outcome.status in {"SUCCESS", "SUCCESS_EMPTY"}
                else timedelta(hours=1)
            )
            if timedelta(0) <= now - prior.outcome.observed_at < ttl:
                outcome = prior.outcome.model_copy(deep=True)
                # A failed attempt keeps its own status, not the retained success status.
                result = (
                    prior.demand.model_copy(deep=True)
                    if outcome.status == "SUCCESS"
                    else DemandResult(
                        provider=name,
                        query=query,
                        location=location,
                        status="failed" if outcome.status == "FAILED" else "unavailable",
                        collected_at=outcome.observed_at,
                    )
                )
                first, end, cached = prior.period_start, prior.period_end, True
                run.cache_hits.append("demand")
        if outcome is None:
            if destination.country not in DEMAND_COUNTRIES:
                status = "UNSUPPORTED"
                notice = "Measured demand is unsupported for this country; no request made."
            elif demo:
                status = "UNAVAILABLE"
                notice = "Demo Mode disables external demand requests."
            elif not getattr(provider, "enabled", True):
                status = "UNAVAILABLE"
                notice = "Measured demand data unavailable; provider credentials are missing."
            elif getattr(provider, "location", location) != location:
                status = "UNSUPPORTED"
                notice = "Demand provider geography does not match the selected country."
            else:
                status = None
                notice = ""
            if status:
                outcome = ProviderOutcome(status=status, notice=notice, observed_at=now)
            else:
                result = legacy
                if result is not None:
                    run.cache_hits.append("demand-v3")
                    cached = True
                    first, end = _closed_dates(result.collected_at)
                else:
                    before = getattr(provider, "request_count", 0)
                    try:
                        requested = product.model_copy(update={"name": query})
                        result = DemandResult.model_validate(provider.collect(requested))
                        if not self._compatible(result, name, query, location):
                            raise ValueError("Demand response identity mismatch.")
                    except Exception:
                        result = DemandResult(
                            provider=name,
                            query=query,
                            location=location,
                            status="failed",
                            collected_at=now,
                        )
                    requests = max(0, getattr(provider, "request_count", 0) - before)
                successful_empty = (result.status == "completed" and not result.observations) or (
                    isinstance(provider, DataForSEOTrendProvider)
                    and getattr(provider, "enabled", False)
                    and (requests or cached)
                    and result.status == "unavailable"
                    and not result.observations
                )
                status = (
                    "SUCCESS_EMPTY"
                    if successful_empty
                    else "SUCCESS"
                    if result.status == "completed"
                    else "FAILED"
                    if result.status == "failed"
                    else "UNAVAILABLE"
                )
                notice = {
                    "SUCCESS": "Provider-relative popularity; not monthly volume or sales.",
                    "SUCCESS_EMPTY": "Successful demand response contains no observations.",
                    "FAILED": "Demand request failed; prior observations are historical only.",
                    "UNAVAILABLE": "Measured demand data unavailable.",
                }[status]
                outcome = ProviderOutcome(
                    status=status,
                    notice=notice,
                    observed_at=result.collected_at,
                    records=[result.model_dump(mode="json")] if status == "SUCCESS" else [],
                )
        if result is None:
            result = DemandResult(
                provider=name,
                query=query,
                location=location,
                status="unavailable",
                collected_at=outcome.observed_at,
            )
        retained = bool(
            outcome.status not in {"SUCCESS", "SUCCESS_EMPTY"}
            and prior
            and prior.demand.observations
        )
        if retained:
            result = prior.demand.model_copy(deep=True)
        run.requests[name] = requests
        run.stages.append(
            {
                "component": "demand",
                "provider": name,
                "query": query,
                "country": destination.country,
                "location": location,
                "status": outcome.status,
                "notice": outcome.notice,
                "observed_at": outcome.observed_at.isoformat(),
                "cached": cached,
                "retained": retained,
            }
        )
        run.completed_at = self.clock()
        run.elapsed_seconds = max(0, time.monotonic() - started)
        snapshot = DemandSnapshot(
            product_id=product.id,
            input_fingerprint=product_fingerprint(product),
            country=destination.country,
            query=query,
            provider=name,
            location=location,
            request_context=context,
            period_start=first,
            period_end=end,
            demand=result,
            outcome=outcome,
            telemetry=run,
            retained=retained,
        )
        # Actual closed dates are part of the request cache identity. The current pointer
        # permits seven-day reuse of those same dated observations without changing dates.
        request_key = "demand-request-v4:" + _hash([context, first.isoformat(), end.isoformat()])
        self.repo.save_cache(request_key, outcome)
        self.repo.save_cache(
            self._current_key(product, destination, query),
            ProviderOutcome(
                status="SUCCESS",
                records=[snapshot.model_dump(mode="json")],
                observed_at=outcome.observed_at,
            ),
        )
        self.repo.save_action(product.id, run)
        return self.get_current(product, destination, query=query)


def current_market_overlay(product, repository, destination):
    """Return a local eligibility view; historical V3 reports and telemetry are never saved."""
    extension = (
        repository if isinstance(repository, SupplyRepository) else SupplyRepository(repository)
    )
    market = MarketIntelligenceRepository(extension.repository)
    report = market.get_report(product.id)
    if report is None or report.input_fingerprint != product_fingerprint(product):
        return None
    report = report.model_copy(deep=True)
    valid_prices = []
    failed_sources = {
        stage.stage.split(":", 1)[1]
        for stage in report.telemetry.stages
        if stage.stage.startswith("page:") and stage.status in {"FAILED", "UNAVAILABLE"}
    }
    for source in report.web_evidence.sources:
        claims = list(
            dict.fromkeys(
                f.claim for f in report.web_evidence.findings if source.id in f.source_ids
            )
        ) or [source.what_claim_it_supports]
        claim_hash = hashlib.sha256(json.dumps(claims).encode()).hexdigest()
        entry = market.get_cache(f"page-v3:{product_fingerprint(product)}:{source.id}:{claim_hash}")
        rows = [p for p in report.price_observations if p.source_id == source.id]
        if source.id in failed_sources:
            rows = []
            for page in report.page_verifications:
                if page.source_id == source.id:
                    page.fetched = False
        elif entry is not None:
            metadata = entry.payload.get("verification", {})
            latest = entry.collected_at
            if not rows or latest >= max(p.observed_at for p in rows):
                if not metadata.get("fetched", False):
                    rows = []
                    for page in report.page_verifications:
                        if page.source_id == source.id:
                            page.fetched = False
                else:
                    rows = [
                        MarketPriceObservation.model_validate(row)
                        for row in entry.payload.get("prices", [])
                    ]
        valid_prices.extend(rows)
    report.price_observations = valid_prices
    report.price_summaries = summarize_prices(valid_prices)
    snapshot = DemandIntelligenceService(extension).get_current(product, destination)
    if snapshot:
        report.demand = snapshot.demand.model_copy(deep=True)
        if not snapshot.current_eligible:
            report.demand.status = (
                "failed" if snapshot.outcome.status == "FAILED" else "unavailable"
            )
        report.trend = snapshot.trend
        report.telemetry.stages = [s for s in report.telemetry.stages if s.stage != "demand"]
        report.telemetry.stages.append(
            ProviderAttempt(
                stage="demand",
                provider=snapshot.provider,
                status="CACHED"
                if snapshot.current_eligible
                else "FAILED"
                if snapshot.outcome.status == "FAILED"
                else "UNAVAILABLE",
                notice=snapshot.outcome.notice,
                retained=snapshot.retained,
                collected_at=snapshot.outcome.observed_at,
            )
        )
    elif report.demand.location != _location(destination.country):
        report.demand = DemandResult(
            provider=report.demand.provider,
            query=product.name,
            location=_location(destination.country),
            status="unavailable",
            notice="No measured demand for the selected country.",
        )
        report.trend = TrendResult()
    else:
        report.trend = calculate_trend(report.demand.observations)
    report.score = score_market_report(
        report.web_evidence,
        report.page_verifications,
        report.demand,
        report.trend,
        report.price_summaries,
        report.economics_result,
    )
    return report
