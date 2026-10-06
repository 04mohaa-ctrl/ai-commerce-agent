"""Ephemeral page parsing and publication metadata; only extracted attribution is persisted."""

import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from pydantic import BaseModel, ConfigDict

from src.research.models import Source, canonical_url
from src.research.providers.safe_http import SafePageFetcher
from src.research.verification import (
    ClaimVerification,
    PageVerification,
    classify_source,
    publisher_domain,
    verify_claim,
)


class VerifiedPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verification: PageVerification
    html: str = ""


class _PageParser(HTMLParser):
    """Parse ordinary visible HTML without executing scripts or fetching resources."""

    _VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
    _BLOCK = {"p", "div", "br", "li", "section", "article", "h1", "h2", "h3", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.visible = []
        self.title = []
        self.canonical = ""
        self.metadata_dates = []
        self.json_scripts = []
        self.script_parts = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        style = re.sub(r"\s+", "", attrs.get("style", "").lower())
        hidden = (
            tag in {"script", "style", "head", "title", "template", "noscript"}
            or "hidden" in attrs
            or attrs.get("aria-hidden", "").lower() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self.script_parts = []
        if tag == "meta":
            name = attrs.get("property", attrs.get("name", "")).lower()
            field = {
                "article:published_time": "published_at",
                "datepublished": "published_at",
                "article:modified_time": "updated_at",
                "datemodified": "updated_at",
            }.get(name)
            if field and "content" in attrs:
                self.metadata_dates.append((field, name, attrs["content"]))
        if tag == "link" and "canonical" in attrs.get("rel", "").lower().split():
            self.canonical = attrs.get("href", "")
        if tag in self._BLOCK:
            self.visible.append("\n")
        if tag not in self._VOID:
            inherited = bool(self.stack and self.stack[-1][1])
            self.stack.append((tag, hidden or inherited))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "script" and self.script_parts is not None:
            self.json_scripts.append("".join(self.script_parts))
            self.script_parts = None
        for position in range(len(self.stack) - 1, -1, -1):
            if self.stack[position][0] == tag:
                self.stack = self.stack[:position]
                break
        if tag in self._BLOCK:
            self.visible.append("\n")

    def handle_data(self, data):
        if self.script_parts is not None:
            self.script_parts.append(data)
        if any(tag == "title" for tag, hidden in self.stack):
            self.title.append(data)
        if not self.stack or not self.stack[-1][1]:
            self.visible.append(data)


def _objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def _identity_matches(value, url):
    if isinstance(value, dict):
        value = value.get("@id", value.get("url"))
    if not isinstance(value, str):
        return False
    try:
        return canonical_url(urljoin(url, value)) == canonical_url(url)
    except ValueError:
        return False


def _structured_metadata(parser, url):
    metadata_types, dates = [], []
    for raw in parser.json_scripts:
        try:
            parsed = json.loads(raw)
        except (ValueError, RecursionError):
            continue
        for item in _objects(parsed):
            kinds = item.get("@type", [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if not isinstance(kinds, list):
                continue
            kinds = [kind for kind in kinds if isinstance(kind, str)]
            metadata_types.extend(kinds)
            if not {kind.lower() for kind in kinds} & {
                "article",
                "newsarticle",
                "blogposting",
                "scholarlyarticle",
                "report",
                "medicalscholarlyarticle",
            }:
                continue
            identity = item.get("mainEntityOfPage", item.get("url", item.get("@id")))
            if identity is not None and not _identity_matches(identity, url):
                continue
            for key, field in (("datePublished", "published_at"), ("dateModified", "updated_at")):
                if isinstance(item.get(key), str):
                    dates.append((field, f"jsonld:{','.join(kinds)}:{key}", item[key]))
    return metadata_types, dates


def _dates(raw_dates, accessed_at):
    values = {"published_at": [], "updated_at": []}
    provenance = []
    invalid = len(raw_dates) > 64
    for field, origin, raw in raw_dates[:64]:
        precision = "day" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) else "timestamp"
        reason = "valid"
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if precision == "day":
                value = value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None:
                raise ValueError
            value = value.astimezone(timezone.utc)
            if value > accessed_at:
                reason = "future"
                invalid = True
            else:
                values[field].append(value)
        except ValueError:
            reason = "invalid"
            invalid = True
        provenance.append(
            {
                "field": field,
                "source": origin,
                "raw": raw[:500],
                "precision": precision,
                "status": reason,
            }
        )
    if len(raw_dates) > 64:
        provenance.append(
            {
                "field": "dates",
                "source": "metadata-limit",
                "raw": "",
                "precision": "unknown",
                "status": "overflow",
            }
        )
    if any(len(set(items)) > 1 for items in values.values()):
        invalid = True
        for item in provenance:
            item["status"] = "conflicting"
    published = values["published_at"][0] if values["published_at"] else None
    updated = values["updated_at"][0] if values["updated_at"] else None
    if published and updated and updated < published:
        invalid = True
        for item in provenance:
            item["status"] = "conflicting"
    if invalid or not (published or updated):
        return None, None, "UNKNOWN", provenance
    return published, updated, "KNOWN", provenance


class PageVerificationProvider:
    name = "safe-page-verification"

    def __init__(self, fetcher: SafePageFetcher | None = None):
        self.fetcher = fetcher or SafePageFetcher()

    @property
    def request_count(self):
        return self.fetcher.request_count

    @property
    def source_fetch_count(self):
        return self.fetcher.source_fetch_count

    def verify(self, source: Source, claims: list[str]) -> VerifiedPage:
        result = self.fetcher.fetch(source.url)
        page = PageVerification(
            source_id=source.id,
            canonical_url=source.url,
            original_url=source.url,
            final_url=result.url,
            publisher=publisher_domain(source.url),
            accessed_at=result.fetched_at,
        )
        if result.status != "success":
            status = "SOURCE_BLOCKED" if result.status == "blocked" else "SOURCE_UNAVAILABLE"
            page.claims = [ClaimVerification(claim=claim, status=status) for claim in claims]
            page.classification_reason = f"classification-v1: {result.reason}"
            return VerifiedPage(verification=page)
        parser = _PageParser()
        try:
            parser.feed(result.text)
            parser.close()
        except (ValueError, RecursionError):
            page.fetched = True
            page.claims = [
                ClaimVerification(claim=claim, status="SOURCE_REACHABLE_BUT_UNVERIFIED")
                for claim in claims
            ]
            return VerifiedPage(verification=page, html=result.text)
        url = result.url
        if parser.canonical:
            try:
                candidate = canonical_url(urljoin(result.url, parser.canonical))
                if (
                    candidate.startswith("https://")
                    and urlsplit(candidate).netloc == urlsplit(result.url).netloc
                ):
                    url = candidate
            except ValueError:
                pass
        page.canonical_url = url
        page.publisher = publisher_domain(result.url)
        page.page_title = " ".join("".join(parser.title).split())[:500]
        visible_text = " ".join("".join(parser.visible).split())
        types, json_dates = _structured_metadata(parser, url)
        page.published_at, page.updated_at, page.date_status, page.date_provenance = _dates(
            [*parser.metadata_dates, *json_dates], result.fetched_at
        )
        classification = classify_source(
            result.url, page.page_title, visible_text, metadata_types=types
        )
        page.category, page.classification_reason = classification.category, classification.reason
        page.classification_confidence = classification.confidence
        page.classification_method = classification.method
        page.fetched = True
        page.claims = [verify_claim(claim, visible_text) for claim in claims]
        return VerifiedPage(verification=page, html=result.text)
