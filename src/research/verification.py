"""Deterministic publisher attribution; page support does not establish objective truth."""

import re
import unicodedata
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

import tldextract
from pydantic import BaseModel, ConfigDict, Field

from src.research.models import Confidence

ClaimStatus = Literal[
    "VERIFIED_ON_PAGE",
    "PARTIALLY_SUPPORTED",
    "SOURCE_REACHABLE_BUT_UNVERIFIED",
    "SOURCE_BLOCKED",
    "SOURCE_UNAVAILABLE",
    "CLAIM_NOT_FOUND",
]
SourceCategory = Literal[
    "MARKETPLACE",
    "SELLER",
    "MANUFACTURER",
    "FORUM",
    "RESEARCH_REPORT",
    "NEWS_EDITORIAL",
    "REVIEW_AFFILIATE",
    "SEARCH_TREND",
    "OTHER",
]


class ClaimVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str = Field(min_length=1, max_length=4000)
    status: ClaimStatus
    supporting_excerpt: str = Field(default="", max_length=1000)
    confidence: Confidence = "low"
    method: str = "visible-contiguous-v1"


class PageVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    canonical_url: str
    original_url: str = ""
    final_url: str = ""
    publisher: str
    page_title: str = ""
    published_at: datetime | None = None
    updated_at: datetime | None = None
    date_status: Literal["KNOWN", "UNKNOWN"] = "UNKNOWN"
    date_provenance: list[dict[str, str]] = Field(default_factory=list)
    accessed_at: datetime
    fetched: bool = False
    category: SourceCategory = "OTHER"
    classification_reason: str = "classification-v1: No identifying source metadata."
    classification_confidence: Confidence = "low"
    classification_method: str = "classification-v1"
    claims: list[ClaimVerification] = Field(default_factory=list)


class SourceClassification(BaseModel):
    category: SourceCategory
    reason: str
    confidence: Confidence
    method: str = "classification-v1"


_DOMAIN_EXTRACTOR = tldextract.TLDExtract(
    suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True
)


def publisher_domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    extracted = _DOMAIN_EXTRACTOR(host)
    return extracted.top_domain_under_public_suffix or host


def classify_source(
    url: str,
    title: str = "",
    text: str = "",
    *,
    metadata_types: list[str] | None = None,
    manufacturer: str | None = None,
) -> SourceClassification:
    """Conservative fixed rules in precedence order; no prose-based demand inference."""
    domain = publisher_domain(url)
    parsed = urlsplit(url)
    path = parsed.path.lower()
    types = {item.lower() for item in metadata_types or []}
    lowered = text.lower()
    result = ("OTHER", "No identifying source metadata.", "low")
    if domain in {
        "amazon.com",
        "amazon.co.uk",
        "amazon.de",
        "ebay.com",
        "walmart.com",
        "aliexpress.com",
        "etsy.com",
        "temu.com",
        "target.com",
    }:
        result = ("MARKETPLACE", "Known marketplace publisher domain.", "high")
    elif types & {"product", "offer", "aggregateoffer"} or re.search(
        r"/(products?|shop|store|cart)(?:/|$)", path
    ):
        result = ("SELLER", "Product/Offer metadata or shop path.", "high")
    elif manufacturer and re.sub(r"[^a-z0-9]", "", manufacturer.lower()) == re.sub(
        r"[^a-z0-9]", "", domain.split(".")[0]
    ):
        result = ("MANUFACTURER", "Explicit manufacturer matches publisher domain.", "medium")
    elif "affiliate" in lowered or "commission" in lowered:
        # Text support preserves commercial attribution even when Article/Report metadata
        # otherwise resembles independent editorial or research evidence.
        result = ("REVIEW_AFFILIATE", "Explicit affiliate or commission disclosure.", "medium")
    elif domain in {"reddit.com", "quora.com"} or re.search(r"/(forums?|community)(?:/|$)", path):
        result = ("FORUM", "Known forum publisher or forum path.", "high")
    elif types & {"scholarlyarticle", "report", "medicalscholarlyarticle"}:
        result = ("RESEARCH_REPORT", "Scholarly article/report metadata.", "high")
    elif types & {"newsarticle"}:
        result = ("NEWS_EDITORIAL", "NewsArticle metadata.", "high")
    elif types & {"review"} or re.search(r"/reviews?(?:/|$)", path):
        result = ("REVIEW_AFFILIATE", "Review path/metadata or affiliate disclosure.", "medium")
    elif domain in {"trends.google.com", "google.com", "bing.com"} and (
        "trends" in (parsed.hostname or "") or path.startswith(("/search", "/trends"))
    ):
        result = ("SEARCH_TREND", "Known search/trend URL.", "high")
    elif types & {"article", "blogposting"}:
        result = ("NEWS_EDITORIAL", "Article/editorial metadata.", "medium")
    return SourceClassification(
        category=result[0], reason=f"classification-v1: {result[1]}", confidence=result[2]
    )


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def verify_claim(claim: str, visible_text: str) -> ClaimVerification:
    normalized = _normalize(claim)
    page = _normalize(visible_text)
    if not page:
        return ClaimVerification(claim=claim, status="SOURCE_REACHABLE_BUT_UNVERIFIED")
    # Preserve all numbers and qualifiers. Very short matches provide too little context.
    position = page.find(normalized)
    if len(normalized) >= 40 and len(normalized.split()) >= 7 and position >= 0:
        # Return bounded actual page text, rather than manufacturing a search-summary quote.
        excerpt = " ".join(visible_text.split())
        if len(excerpt) > 1000:
            normalized_excerpt = _normalize(excerpt)
            position = normalized_excerpt.find(normalized)
            excerpt = normalized_excerpt[max(0, position - 100) : position + len(normalized) + 100]
        return ClaimVerification(
            claim=claim,
            status="VERIFIED_ON_PAGE",
            supporting_excerpt=excerpt[:1000],
            confidence="high",
        )
    claim_words = set(re.findall(r"\b\w+\b", normalized))
    page_words = set(re.findall(r"\b\w+\b", page))
    overlap = claim_words & page_words
    if len(overlap) >= 4 and len(overlap) / max(len(claim_words), 1) >= 0.5:
        return ClaimVerification(
            claim=claim,
            status="PARTIALLY_SUPPORTED",
            supporting_excerpt=" ".join(visible_text.split())[:1000],
            confidence="low",
        )
    return ClaimVerification(claim=claim, status="CLAIM_NOT_FOUND")


def status_label(status: ClaimStatus) -> str:
    return {
        "VERIFIED_ON_PAGE": "Supported on source page",
        "PARTIALLY_SUPPORTED": "Partially supported on source page",
        "SOURCE_REACHABLE_BUT_UNVERIFIED": "Source reachable; claim unverified",
        "SOURCE_BLOCKED": "Source blocked",
        "SOURCE_UNAVAILABLE": "Source unavailable",
        "CLAIM_NOT_FOUND": "Claim not found on source page",
    }[status]
