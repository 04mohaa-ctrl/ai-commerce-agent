"""Research orchestration and caching, composed with the V1 repository."""

from datetime import timedelta

from src.database.database import ProductRepository
from src.research.models import ResearchAttempt, ResearchReport, utc_now
from src.research.providers.base import (
    ProgressCallback,
    ResearchProvider,
    ResearchProviderError,
    product_fingerprint,
)
from src.research.providers.web_research import WebResearchProvider
from src.research.scoring import confidence_for
from src.schemas.product import Product


class EvidenceResearchService:
    def __init__(
        self,
        repository: ProductRepository,
        api_key: str = "",
        model: str = "gpt-4.1-mini",
        force_demo: bool = False,
        provider: ResearchProvider | None = None,
    ):
        self.repository = repository
        self.api_key = api_key.strip()
        self.force_demo = force_demo
        self.model = model
        self.provider = (
            provider
            if provider is not None
            else (WebResearchProvider(self.api_key, model=model) if self.api_key else None)
        )

    def research_product(
        self, product: Product, *, force: bool = False, progress: ProgressCallback | None = None
    ) -> ResearchReport:
        fingerprint = product_fingerprint(product)
        cached = self.repository.get_research(product.id)
        if (
            not force
            and cached
            and cached.status == "completed"
            and cached.input_fingerprint == fingerprint
            and cached.researched_at > utc_now() - timedelta(days=1)
        ):
            return cached
        self.repository.save_research_attempt(product.id, ResearchAttempt(status="researching"))
        if self.force_demo or not self.api_key:
            report = ResearchReport(
                product_name=product.name,
                mode="demo",
                provider="demo",
                notice="Demo Mode: no external research performed; "
                "no evidence or sources invented.",
                input_fingerprint=fingerprint,
            )
        else:
            try:
                report = self.provider.research(product, progress=progress)
                report.input_fingerprint = fingerprint
                report.product_name = product.name
                report.confidence_level = confidence_for(report)
            except ResearchProviderError as error:
                report = error.partial_report or ResearchReport(
                    product_name=product.name,
                    status="failed",
                    mode="web",
                    notice="External research failed. Check API/model access and your connection.",
                    model=self.model,
                )
                report.input_fingerprint = fingerprint
                report.product_name = product.name
        self.repository.save_research(product.id, report)
        return report
