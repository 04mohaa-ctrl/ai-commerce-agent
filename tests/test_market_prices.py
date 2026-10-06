import json
from decimal import Decimal

from src.research.matching import match_product
from src.research.models import Source, utc_now
from src.research.providers.retail_prices import extract_market_prices, summarize_prices


def source(url="https://shop.example/item"):
    return Source(
        title="Retail listing",
        url=url,
        accessed_at=utc_now(),
        what_claim_it_supports="Listing metadata",
    )


def html(name="Pet Hair Remover", price="19.99", **changes):
    item = {
        "@type": "Product",
        "name": name,
        "offers": {
            "@type": "Offer",
            "price": price,
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock",
        },
    }
    item.update(changes)
    return '<script type="application/ld+json">' + json.dumps(item) + "</script>"


def test_exact_and_qualified_identity_matching(product):
    assert match_product(product, "PET hair remover").outcome == "MATCH"
    assert match_product(product, "Reusable Pet Hair Remover roller").outcome == "LIKELY_MATCH"
    assert match_product(product, "Laptop charger").outcome == "NO_MATCH"
    assert match_product(product, "Pet Hair Remover", brand="Acme").outcome == "AMBIGUOUS"
    p = product.model_copy(
        update={"name": "Acme Pet Hair Remover 2 pack 500 ml red", "description": "Brand: Acme"}
    )
    assert match_product(p, p.name, brand="Acme").outcome == "MATCH"
    assert match_product(p, p.name, brand="Other").outcome == "NO_MATCH"
    assert (
        match_product(p, "Acme Pet Hair Remover 3 pack 500 ml red", brand="Acme").outcome
        == "NO_MATCH"
    )
    assert (
        match_product(p, "Acme Pet Hair Remover 2 pack 750 ml red", brand="Acme").outcome
        == "NO_MATCH"
    )
    assert (
        match_product(p, "Acme Pet Hair Remover 2 pack 500 ml blue", brand="Acme").outcome
        == "NO_MATCH"
    )
    assert match_product(p, "Acme Pet Hair Remover", brand="Acme").outcome == "AMBIGUOUS"


def test_native_prices_dates_decimal_and_compatible_statistics(product):
    rows = []
    for i, price in enumerate(["19.99", "30.00", "21.00"]):
        rows += extract_market_prices(
            html(price=price), product, source(f"https://shop{i}.example/item")
        )
    assert rows[0].price == Decimal("19.99")
    assert rows[0].observed_at.tzinfo
    summary = summarize_prices(rows)[0]
    assert summary.count == 3
    assert (summary.minimum, summary.median, summary.maximum) == (
        Decimal("19.99"),
        Decimal("21"),
        Decimal("30"),
    )


def test_only_available_reviewed_compatible_unique_listings_contribute(product):
    first = extract_market_prices(html(), product, source())[0]
    duplicate = first.model_copy(update={"url": "https://shop.example/item?utm_source=x"})
    likely = first.model_copy(
        update={"url": "https://two.example/item", "match_outcome": "LIKELY_MATCH"}
    )
    unavailable = first.model_copy(
        update={"url": "https://three.example/item", "availability": "OutOfStock"}
    )
    ambiguous = first.model_copy(
        update={"url": "https://four.example/item", "match_outcome": "AMBIGUOUS", "reviewed": True}
    )
    summary = summarize_prices([first, duplicate, likely, unavailable, ambiguous])[0]
    assert summary.count == 1 and summary.minimum is None
    assert summary.notice == "Insufficient price observations"
    likely.reviewed = True
    assert summarize_prices([first, likely])[0].count == 2


def test_currency_brand_and_pack_groups_never_pool(product):
    first = extract_market_prices(html(), product, source())[0]
    rows = [first]
    for field, value in [("currency", "EUR"), ("brand", "Acme"), ("variant", "2 pack")]:
        rows.append(first.model_copy(update={"url": f"https://{field}.example/item", field: value}))
    groups = summarize_prices(rows)
    assert len(groups) == 4
    assert all(g.count == 1 and g.median is None for g in groups)


def test_invalid_or_missing_metadata_never_becomes_price(product):
    assert not extract_market_prices("<p>$29.99 cheap</p>", product, source())
    assert not extract_market_prices(html(price="NaN"), product, source())
    assert not extract_market_prices(
        html(offers={"price": 12, "priceCurrency": "US"}), product, source()
    )
    assert not extract_market_prices(
        html(
            offers={
                "@type": "AggregateOffer",
                "lowPrice": 10,
                "highPrice": 20,
                "priceCurrency": "USD",
            }
        ),
        product,
        source(),
    )


def test_structured_brand_variant_discriminators_prevent_false_match(product):
    rows = extract_market_prices(
        html(brand={"name": "Acme"}, size="500ml", color="red"), product, source()
    )
    assert rows[0].match_outcome == "AMBIGUOUS"
    assert rows[0].brand == "Acme" and "500ml" in rows[0].variant


def test_structured_pack_count_requires_matching_product_discriminator(product):
    rows = extract_market_prices(html(numberOfItems=3), product, source())
    assert rows[0].match_outcome == "AMBIGUOUS"
    assert "3" in rows[0].variant
    p = product.model_copy(update={"name": "Pet Hair Remover 2 pack"})
    rows = extract_market_prices(html(name=p.name, numberOfItems=3), p, source())
    assert rows[0].match_outcome == "NO_MATCH"


def test_matching_metadata_does_not_demote_exact_identity(product):
    p = product.model_copy(update={"name": "Pet Hair Remover 500ml red"})
    rows = extract_market_prices(html(name=p.name, size="500ml", color="red"), p, source())
    assert rows[0].match_outcome == "MATCH"


def test_conflicting_duplicate_prices_do_not_count_twice(product):
    first = extract_market_prices(html(), product, source())[0]
    second = first.model_copy(update={"price": Decimal("50")})
    summary = summarize_prices([first, second])[0]
    assert summary.count == 0 and summary.minimum is None


def test_brand_requires_whole_identity_words(product):
    p = product.model_copy(update={"name": "Surface Hair Remover"})
    assert match_product(p, p.name, brand="Face").outcome == "AMBIGUOUS"


def test_unspecified_model_variant_is_ambiguous(product):
    rows = extract_market_prices(html(model="X1"), product, source())
    assert rows[0].match_outcome == "AMBIGUOUS"
