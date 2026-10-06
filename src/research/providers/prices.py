"""Observe USD prices from cited retail Product/Offer JSON-LD, without CSS scraping."""

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import ValidationError

from src.research.models import PriceObservation, Source

RETAIL_DOMAINS = {
    "chewy.com",
    "walmart.com",
    "target.com",
    "amazon.com",
    "petco.com",
    "bestbuy.com",
    "petsmart.com",
    "chomchomroller.com",
    "blendjet.com",
}
MAX_PAGE_BYTES = 2_000_000


class JsonLdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.current: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            self.capture = dict(attrs).get("type", "").lower() == "application/ld+json"
            self.current = []

    def handle_data(self, data):
        if self.capture:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self.capture:
            self.blocks.append("".join(self.current))
            self.capture = False


def parse_listing_prices(html: str, product_name: str, source_id: str) -> list[PriceObservation]:
    """Keep matching USD offers only; never use an AI-generated numeric price."""
    parser = JsonLdParser()
    parser.feed(html)
    tokens = set(re.findall(r"[a-z0-9]+", product_name.lower()))
    observations = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            kind = node.get("@type", [])
            kinds = kind if isinstance(kind, list) else [kind]
            if any(str(k).rsplit("/", 1)[-1] == "Product" for k in kinds):
                title = node.get("name", "")
                if isinstance(title, str) and tokens:
                    words = set(re.findall(r"[a-z0-9]+", title.lower()))
                    overlap = len(tokens & words)
                    if overlap / len(tokens) >= 0.67 and overlap >= min(2, len(tokens)):
                        offers = node.get("offers", [])
                        offers = offers if isinstance(offers, list) else [offers]
                        for offer in offers:
                            if isinstance(offer, dict) and offer.get("priceCurrency") == "USD":
                                try:
                                    observations.append(
                                        PriceObservation(
                                            product_title=title,
                                            price=offer.get("price"),
                                            source_id=source_id,
                                        )
                                    )
                                except ValidationError:
                                    pass
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)

    for block in parser.blocks:
        try:
            walk(json.loads(block))
        except (ValueError, RecursionError):
            continue
    unique = {(p.product_title, p.price, p.source_id): p for p in observations}
    return list(unique.values())


def _allowed(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    return (
        parts.scheme == "https"
        and host in RETAIL_DOMAINS
        and parts.port in (None, 443)
        and not parts.username
    )


def fetch_listing_prices(
    source: Source, product_name: str, client: httpx.Client | None = None
) -> list[PriceObservation]:
    """Bounded public retail metadata read. No auth headers, arbitrary hosts or redirects."""
    if not _allowed(source.url):
        return []
    if client is None:
        with httpx.Client(timeout=6, follow_redirects=False, trust_env=False) as own_client:
            return fetch_listing_prices(source, product_name, client=own_client)
    url = source.url
    try:
        for _ in range(3):
            if not _allowed(url):
                return []
            with client.stream("GET", url, follow_redirects=False) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                if (
                    response.status_code != 200
                    or "html" not in response.headers.get("content-type", "").lower()
                ):
                    return []
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_PAGE_BYTES:
                        return []
                return parse_listing_prices(
                    body.decode("utf-8", errors="replace"), product_name, source.id
                )
    except (httpx.HTTPError, ValueError, RecursionError):
        return []
    return []
