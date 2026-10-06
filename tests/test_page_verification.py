"""Public-reader security and conservative publisher-attribution behavior."""

import gzip
from datetime import datetime, timezone

import httpx
import pytest

from src.research.models import Source
from src.research.providers.page_verification import PageVerificationProvider
from src.research.providers.safe_http import SafePageFetcher
from src.research.verification import classify_source, publisher_domain, status_label, verify_claim

NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
CLAIM = "The survey found that 42 percent of consumers prefer a reusable lunch container."


def source(url="https://news.example.com/article", source_type="article"):
    return Source(
        title="Research citation",
        url=url,
        accessed_at=NOW,
        source_type=source_type,
        what_claim_it_supports=CLAIM,
    )


def fetcher(handler=None, *, resolver=None, **kwargs):
    def default(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"}
            )
        return httpx.Response(
            200, text=f"<title>Survey</title><p>{CLAIM}</p>", headers={"Content-Type": "text/html"}
        )

    return SafePageFetcher(
        transport=httpx.MockTransport(handler or default),
        resolver=resolver or (lambda host: ["93.184.216.34"]),
        clock=lambda: NOW,
        **kwargs,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/page",
        "https://user:password@example.com/page",
        "https://example.com:8443/page",
        "https://localhost/page",
        "https://thing.internal/page",
        "https://127.0.0.1/page",
        "https://10.0.0.1/page",
        "https://169.254.169.254/page",
        "https://[::1]/page",
        "https://[fc00::1]/page",
        "https://[::ffff:127.0.0.1]/page",
        "https://224.0.0.1/page",
    ],
)
def test_unsafe_targets_never_issue_a_request(url):
    reader = fetcher()
    result = reader.fetch(url)
    assert result.status == "blocked"
    assert result.text == ""
    assert reader.request_count == 0
    assert reader.source_fetch_count == 1


@pytest.mark.parametrize(
    "answers", [["93.184.216.34", "10.1.2.3"], ["2606:4700::1111", "::1"], [], ["not-an-ip"]]
)
def test_any_nonpublic_or_invalid_dns_answer_blocks_entire_origin(answers):
    reader = fetcher(resolver=lambda host: answers)
    assert reader.fetch("https://example.com/a").status == "blocked"
    assert reader.request_count == 0


def test_pins_dns_address_and_preserves_original_host_and_certificate_hostname():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            text="User-agent: *\nAllow: /" if request.url.path == "/robots.txt" else "hello",
            headers={"Content-Type": "text/plain", "Set-Cookie": "secret=x"},
        )

    reader = fetcher(handler)
    assert reader.fetch("https://news.example.com/a").status == "success"
    assert reader.request_count == 2
    assert all(str(r.url.host) == "93.184.216.34" for r in requests)
    assert all(r.headers["host"] == "news.example.com" for r in requests)
    assert all(r.extensions["sni_hostname"] == "news.example.com" for r in requests)
    assert all("cookie" not in r.headers and "authorization" not in r.headers for r in requests)


def test_public_ipv6_is_pinned_and_fetch_identity_remains_original_url():
    reader = fetcher(resolver=lambda host: ["2606:4700::1111"])
    result = reader.fetch("https://example.com/a")
    assert result.status == "success"
    assert result.url == "https://example.com/a"
    assert result.fetched_at == NOW


@pytest.mark.parametrize(
    "policy,status",
    [
        ("User-agent: *\nDisallow: /private", "blocked"),
        ("<html>Unknown policy</html>", "blocked"),
        ("User-agent: *\nAllow: /", "success"),
    ],
)
def test_robots_policy_is_required_and_respected(policy, status):
    def handler(request):
        return httpx.Response(
            200,
            text=policy if request.url.path == "/robots.txt" else "page",
            headers={"Content-Type": "text/plain"},
        )

    reader = fetcher(handler)
    assert reader.fetch("https://example.com/private").status == status
    assert reader.request_count == (2 if status == "success" else 1)


@pytest.mark.parametrize("robots_code", [401, 403, 404, 429, 500])
def test_unknown_robots_http_status_blocks_page_request(robots_code):
    reader = fetcher(lambda request: httpx.Response(robots_code, text="no policy"))
    assert reader.fetch("https://example.com/a").status == "blocked"
    assert reader.request_count == 1


def test_redirect_target_is_revalidated_without_contacting_private_origin():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"}
            )
        return httpx.Response(302, headers={"Location": "https://127.0.0.1/admin"})

    reader = fetcher(handler)
    assert reader.fetch("https://example.com/a").status == "blocked"
    assert reader.request_count == 2


def test_third_redirect_is_never_followed_and_actual_get_count_is_preserved():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"}
            )
        return httpx.Response(302, headers={"Location": request.url.path + "x"})

    reader = fetcher(handler)
    assert reader.fetch("https://example.com/a").status == "blocked"
    assert reader.request_count == 4


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (403, "Forbidden", "blocked"),
        (429, "Rate limit", "blocked"),
        (200, "<title>Just a moment...</title>Verify you are human", "blocked"),
        (200, "<h1>Sign in to continue</h1><input type='password'>", "blocked"),
        (200, "<p>Subscribe to continue reading</p>", "blocked"),
        (404, "Not found", "unavailable"),
        (503, "Server unavailable", "unavailable"),
    ],
)
def test_access_controls_and_unavailable_pages_are_not_returned_as_success(status, body, expected):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"}
            )
        return httpx.Response(status, text=body, headers={"Content-Type": "text/html"})

    reader = fetcher(handler)
    result = reader.fetch("https://example.com/a")
    assert result.status == expected
    assert result.text == ""


@pytest.mark.parametrize("content_type", ["application/pdf", "image/png", "application/json"])
def test_downloads_and_unsupported_content_are_rejected(content_type):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"}
            )
        return httpx.Response(200, content=b"abc", headers={"Content-Type": content_type})

    result = fetcher(handler).fetch("https://example.com/a")
    assert result.status == "unavailable"
    assert result.text == ""


@pytest.mark.parametrize("compressed", [False, True])
def test_decoded_two_megabyte_cap_rejects_large_body(compressed):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"}
            )
        body = b"a" * (2 * 1024 * 1024 + 1)
        headers = {"Content-Type": "text/html"}
        if compressed:
            body = gzip.compress(body)
            headers["Content-Encoding"] = "gzip"
        return httpx.Response(200, content=body, headers=headers)

    result = fetcher(handler).fetch("https://example.com/a")
    assert result.status == "unavailable"
    assert "size" in result.reason.lower()
    assert result.text == ""


def test_total_deadline_and_transport_timeout_return_sanitized_unavailability():
    time = [0.0]

    def handler(request):
        time[0] += 11
        return httpx.Response(
            200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"}
        )

    result = fetcher(handler, monotonic=lambda: time[0], total_timeout=10).fetch(
        "https://example.com/a"
    )
    assert result.status == "unavailable"
    assert "deadline" in result.reason.lower()

    def timeout(request):
        raise httpx.ReadTimeout("token=SECRET", request=request)

    reader = fetcher(timeout)
    result = reader.fetch("https://example.com/a")
    assert result.status == "blocked"  # Robots unknown after the failed request.
    assert "SECRET" not in result.reason
    assert reader.request_count == 1


def test_only_contiguous_visible_claim_support_counts_as_publisher_attribution():
    verified = verify_claim(CLAIM, "Survey results. " + CLAIM + " Respondents answered online.")
    assert verified.status == "VERIFIED_ON_PAGE"
    assert CLAIM in verified.supporting_excerpt
    assert verified.confidence == "high"
    assert status_label(verified.status) == "Supported on source page"
    changed = verify_claim(CLAIM, CLAIM.replace("42", "24"))
    assert changed.status == "PARTIALLY_SUPPORTED"
    assert verify_claim("popular", "popular").status != "VERIFIED_ON_PAGE"
    assert verify_claim(CLAIM, "Unrelated tomato recipe.").status == "CLAIM_NOT_FOUND"
    assert verify_claim(CLAIM, "").status == "SOURCE_REACHABLE_BUT_UNVERIFIED"


def test_hidden_script_and_search_excerpt_do_not_verify_claim():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"}
            )
        html = f"<script>{CLAIM}</script><div hidden>{CLAIM}</div><p>Unrelated text.</p>"
        return httpx.Response(200, text=html, headers={"Content-Type": "text/html"})

    page = PageVerificationProvider(fetcher(handler)).verify(source(), [CLAIM])
    assert page.verification.claims[0].status == "CLAIM_NOT_FOUND"


def test_page_metadata_and_date_provenance_are_separate_from_access_date():
    html = f"""<title>Original study</title><link rel="canonical" href="/study">
      <meta property="article:published_time" content="2026-03-01T10:00:00Z">
      <meta property="article:modified_time" content="2026-04-01T10:00:00Z">
      <p>{CLAIM}</p>"""

    def handler(request):
        return httpx.Response(
            200,
            text="User-agent: *\nAllow: /" if request.url.path == "/robots.txt" else html,
            headers={
                "Content-Type": "text/html" if request.url.path != "/robots.txt" else "text/plain"
            },
        )

    page = PageVerificationProvider(fetcher(handler)).verify(source(), [CLAIM])
    record = page.verification
    assert record.source_id == source().id
    assert record.canonical_url == "https://news.example.com/study"
    assert record.publisher == "example.com"
    assert record.page_title == "Original study"
    assert record.published_at == datetime(2026, 3, 1, 10, tzinfo=timezone.utc)
    assert record.updated_at == datetime(2026, 4, 1, 10, tzinfo=timezone.utc)
    assert record.date_status == "KNOWN"
    assert record.date_provenance[0]["raw"] == "2026-03-01T10:00:00Z"
    assert record.accessed_at == NOW
    assert record.fetched
    assert page.html == html


@pytest.mark.parametrize(
    "metadata",
    [
        "<footer>Copyright 2026</footer>",
        '<meta property="article:published_time" content="2027-01-01">',
        '<meta property="article:published_time" content="2026-01-01">'
        '<meta name="datePublished" content="2026-02-01">',
        '<meta property="article:published_time" content="not a date">',
        '<script type="application/ld+json">'
        '{"@type":"Product","datePublished":"2026-01-01"}</script>',
    ],
)
def test_copyright_future_invalid_conflicting_and_nonarticle_dates_remain_unknown(metadata):
    def handler(request):
        return httpx.Response(
            200,
            text="User-agent: *\nAllow: /"
            if request.url.path == "/robots.txt"
            else metadata + "<p>Body</p>",
            headers={
                "Content-Type": "text/plain" if request.url.path == "/robots.txt" else "text/html"
            },
        )

    record = PageVerificationProvider(fetcher(handler)).verify(source(), [CLAIM]).verification
    assert record.date_status == "UNKNOWN"
    assert record.published_at is None
    assert record.updated_at is None


def test_blocked_fetch_maps_each_claim_to_blocked_without_retaining_html():
    reader = fetcher(lambda request: httpx.Response(403))
    page = PageVerificationProvider(reader).verify(source(), [CLAIM])
    assert not page.verification.fetched
    assert page.verification.claims[0].status == "SOURCE_BLOCKED"
    assert page.html == ""


def test_source_classification_is_conservative_and_offline_domain_grouping_is_registrable():
    assert publisher_domain("https://reviews.shop.example.co.uk/x") == "example.co.uk"
    assert publisher_domain("https://one.blogspot.com/x") == "one.blogspot.com"
    assert classify_source("https://amazon.com/p/123", "", "").category == "MARKETPLACE"
    assert classify_source("https://example.com/products/a", "", "").category == "SELLER"
    assert classify_source("https://reddit.com/r/test", "", "").category == "FORUM"
    assert (
        classify_source("https://example.com/review", "", "affiliate commission").category
        == "REVIEW_AFFILIATE"
    )
    assert (
        classify_source("https://example.com/a", "", "sales grew dramatically").category == "OTHER"
    )


def test_page_stores_original_final_identity_and_classification_confidence():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"}
            )
        if request.url.path == "/article":
            return httpx.Response(302, headers={"Location": "/published"})
        html = '<script type="application/ld+json">{"@type":"NewsArticle"}</script><p>Body</p>'
        return httpx.Response(200, text=html, headers={"Content-Type": "text/html"})

    record = PageVerificationProvider(fetcher(handler)).verify(source(), [CLAIM]).verification
    assert record.original_url == "https://news.example.com/article"
    assert record.final_url == "https://news.example.com/published"
    assert record.classification_confidence == "high"
    assert record.classification_method == "classification-v1"


@pytest.mark.parametrize("url", ["https://user:password@example.com/a", "http://example.com/a"])
def test_redirects_cannot_send_credentials_or_downgrade_https(url):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"}
            )
        return httpx.Response(302, headers={"Location": url})

    reader = fetcher(handler)
    assert reader.fetch("https://example.com/a").status == "blocked"
    assert reader.request_count == 2


def test_redirect_rechecks_robots_for_new_path_without_an_extra_robots_get():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                text="User-agent: *\nDisallow: /private",
                headers={"Content-Type": "text/plain"},
            )
        return httpx.Response(302, headers={"Location": "/private"})

    reader = fetcher(handler)
    assert reader.fetch("https://example.com/public").status == "blocked"
    assert reader.request_count == 2


def test_cross_origin_redirect_checks_new_robots_and_does_not_forward_cookies():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                text="User-agent: *\nAllow: /",
                headers={"Content-Type": "text/plain", "Set-Cookie": "token=secret"},
            )
        if request.headers["host"] == "example.com":
            return httpx.Response(
                302,
                headers={
                    "Location": "https://other.example.com/page",
                    "Set-Cookie": "token=secret",
                },
            )
        return httpx.Response(200, text="Final page", headers={"Content-Type": "text/plain"})

    reader = fetcher(handler)
    assert reader.fetch("https://example.com/a").url == "https://other.example.com/page"
    assert reader.request_count == 4
    assert all("cookie" not in request.headers for request in requests)


def test_streaming_compressed_bomb_is_limited_before_unbounded_decode():
    class Bytes(httpx.SyncByteStream):
        def __iter__(self):
            yield gzip.compress(b"a" * (2 * 1024 * 1024 + 1))

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"}
            )
        return httpx.Response(
            200, stream=Bytes(), headers={"Content-Type": "text/html", "Content-Encoding": "gzip"}
        )

    result = fetcher(handler).fetch("https://example.com/a")
    assert result.status == "unavailable"
    assert "size" in result.reason.lower()
    assert result.text == ""


@pytest.mark.parametrize(
    "json_metadata,status",
    [
        (
            '{"@type":"NewsArticle","url":"https://news.example.com/article",'
            '"datePublished":"2026-03-01T12:00:00+02:00"}',
            "KNOWN",
        ),
        (
            '{"@type":"NewsArticle","url":"https://news.example.com/related",'
            '"datePublished":"2026-03-01T12:00:00+02:00"}',
            "UNKNOWN",
        ),
        ('{"@type":"NewsArticle","datePublished":"2026-03-01T12:00:00"}', "UNKNOWN"),
        (
            '{"@type":"NewsArticle","datePublished":"2026-03-01","dateModified":"2026-02-01"}',
            "UNKNOWN",
        ),
    ],
)
def test_only_page_tied_article_dates_with_known_precision_and_valid_order_are_used(
    json_metadata, status
):
    def handler(request):
        return httpx.Response(
            200,
            text="User-agent: *\nAllow: /"
            if request.url.path == "/robots.txt"
            else f'<script type="application/ld+json">{json_metadata}</script><p>Body</p>',
            headers={
                "Content-Type": "text/plain" if request.url.path == "/robots.txt" else "text/html"
            },
        )

    record = PageVerificationProvider(fetcher(handler)).verify(source(), [CLAIM]).verification
    assert record.date_status == status
    if status == "KNOWN":
        assert record.published_at == datetime(2026, 3, 1, 10, tzinfo=timezone.utc)


def test_css_aria_hidden_and_template_claims_do_not_count_as_visible_support():
    html = f'<div style="display: none">{CLAIM}</div><div aria-hidden="true">{CLAIM}</div>'
    html += f"<template><p>{CLAIM}</p></template><p>Other unrelated content.</p>"

    def handler(request):
        return httpx.Response(
            200,
            text="User-agent: *\nAllow: /" if request.url.path == "/robots.txt" else html,
            headers={
                "Content-Type": "text/plain" if request.url.path == "/robots.txt" else "text/html"
            },
        )

    claim = (
        PageVerificationProvider(fetcher(handler)).verify(source(), [CLAIM]).verification.claims[0]
    )
    assert claim.status == "CLAIM_NOT_FOUND"


def test_exact_match_keeps_claim_qualifiers_and_does_not_verify_changed_numbers():
    claim = "Independent survey reports that demand may increase by 12 percent in urban areas."
    assert verify_claim(claim, claim.replace("may", "will")).status == "PARTIALLY_SUPPORTED"
    assert verify_claim(claim, claim.replace("12", "120")).status == "PARTIALLY_SUPPORTED"


@pytest.mark.parametrize("timeout", [float("inf"), float("nan"), 0, -1])
def test_invalid_deadline_configuration_is_rejected(timeout):
    with pytest.raises(ValueError):
        SafePageFetcher(total_timeout=timeout)


def test_rejected_redirect_credentials_never_escape_into_result_or_persisted_page_identity():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"}
            )
        return httpx.Response(302, headers={"Location": "https://user:SECRET@example.com/a"})

    page = PageVerificationProvider(fetcher(handler)).verify(source(), [CLAIM])
    assert "SECRET" not in page.model_dump_json()
    assert page.verification.final_url == source().url


def test_unfetched_nonstandard_port_canonical_metadata_cannot_replace_page_identity():
    def handler(request):
        return httpx.Response(
            200,
            text="User-agent: *\nAllow: /"
            if request.url.path == "/robots.txt"
            else '<link rel="canonical" href="https://news.example.com:8443/other"><p>Body</p>',
            headers={
                "Content-Type": "text/plain" if request.url.path == "/robots.txt" else "text/html"
            },
        )

    page = PageVerificationProvider(fetcher(handler)).verify(source(), [CLAIM])
    assert page.verification.canonical_url == source().url


def test_repeated_publication_metadata_is_bounded_and_overflow_is_unknown():
    html = '<meta property="article:published_time" content="2026-01-01">' * 100

    def handler(request):
        return httpx.Response(
            200,
            text="User-agent: *\nAllow: /" if request.url.path == "/robots.txt" else html,
            headers={
                "Content-Type": "text/plain" if request.url.path == "/robots.txt" else "text/html"
            },
        )

    record = PageVerificationProvider(fetcher(handler)).verify(source(), [CLAIM]).verification
    assert record.date_status == "UNKNOWN"
    assert record.published_at is None
    assert len(record.date_provenance) <= 65


@pytest.mark.parametrize(
    "policy,path,status",
    [
        ("User-agent: *\nDisallow: /private/*", "/private/report", "blocked"),
        ("User-agent: *\nDisallow: /*.pdf$", "/files/report.pdf", "blocked"),
        ("User-agent: *\nDisallow: /*.pdf$", "/files/report.pdf.html", "success"),
        (
            "User-agent: *\nDisallow: /private/*\nAllow: /private/public/",
            "/private/public/report",
            "success",
        ),
        (
            "User-agent: *\nAllow: /private/public/\nDisallow: /private/*",
            "/private/public/report",
            "success",
        ),
        ("User-agent: *\nDisallow: /same\nAllow: /same", "/same", "success"),
        ("User-agent: *\nAllow: /\nDisallow: /private", "/private/report", "blocked"),
        ("User-agent: *\nDisallow: /private", "/priv%61te/report", "blocked"),
        ("User-agent: *\nDisallow: /café/*", "/caf%C3%A9/report", "blocked"),
        ("User-agent: *\nDisallow: /*?secret=*$", "/page?secret=hidden", "blocked"),
        ("User-agent: OtherBot\nDisallow: /\n\nUser-agent: *\nAllow: /", "/page", "success"),
        (
            "User-agent: *\nAllow: /\n\nUser-agent: aicommerceresearch\nDisallow: /private/*",
            "/private/report",
            "blocked",
        ),
        (
            "User-agent: AICommerceResearch\nAllow: /\n\n"
            "User-agent: AICommerceResearch\nDisallow: /private/*",
            "/private/report",
            "blocked",
        ),
        (
            "User-agent: *\nDisallow: /\n\nUser-agent: AICommerceResearch\nAllow: /",
            "/page",
            "success",
        ),
        (
            "User-agent: *\nAllow: /\n\nUser-agent: OtherBot\n"
            "User-agent: AICommerceResearch\nDisallow: /private/*",
            "/private/report",
            "blocked",
        ),
    ],
)
def test_robots_pattern_matching_and_group_precedence_prevent_forbidden_page_get(
    policy, path, status
):
    def handler(request):
        return httpx.Response(
            200,
            text=policy if request.url.path == "/robots.txt" else "Visible page",
            headers={"Content-Type": "text/plain"},
        )

    reader = fetcher(handler)
    result = reader.fetch("https://example.com" + path)
    assert result.status == status
    assert reader.request_count == (1 if status == "blocked" else 2)


@pytest.mark.parametrize(
    "policy",
    [
        "User-agent: *\nDisallow: relative-path",
        "User-agent: *\nDisallow: /private/$/middle",
        "User-agent: *\nDisallow /private/*",
        "User-agent: *\nDisallow: /broken%ZZ/path",
    ],
)
def test_unsupported_or_malformed_robots_policy_cannot_allow_page_get(policy):
    def handler(request):
        return httpx.Response(
            200,
            text=policy if request.url.path == "/robots.txt" else "page",
            headers={"Content-Type": "text/plain"},
        )

    reader = fetcher(handler)
    assert reader.fetch("https://example.com/private/report").status == "blocked"
    assert reader.request_count == 1


@pytest.mark.parametrize(
    "url,metadata_types",
    [
        ("https://publisher.example.com/article", ["NewsArticle"]),
        ("https://publisher.example.com/study", ["ScholarlyArticle"]),
        ("https://publisher.example.com/report", ["Report"]),
        ("https://reddit.com/r/lunchboxes/article", []),
    ],
)
def test_explicit_affiliate_disclosure_excludes_news_research_and_forum_independence(
    url, metadata_types
):
    classification = classify_source(
        url,
        "Consumer report",
        "We earn a commission from purchases through our affiliate links.",
        metadata_types=metadata_types,
    )
    assert classification.category == "REVIEW_AFFILIATE"
    assert "disclosure" in classification.reason.lower()


@pytest.mark.parametrize(
    "url,types,manufacturer,category",
    [
        ("https://amazon.com/item", ["NewsArticle"], None, "MARKETPLACE"),
        ("https://seller.example.com/products/item", ["NewsArticle"], None, "SELLER"),
        ("https://seller.example.com/article", ["Product", "NewsArticle"], None, "SELLER"),
        ("https://acme.com/news", ["NewsArticle"], "Acme", "MANUFACTURER"),
    ],
)
def test_affiliate_disclosure_preserves_existing_nonindependent_commercial_classification(
    url, types, manufacturer, category
):
    classification = classify_source(
        url,
        "Product article",
        "We earn affiliate commissions.",
        metadata_types=types,
        manufacturer=manufacturer,
    )
    assert classification.category == category


def test_page_supported_news_claim_with_affiliate_disclosure_is_still_nonindependent():
    html = '<script type="application/ld+json">{"@type":"NewsArticle"}</script>'
    html += f"<p>{CLAIM}</p><footer>We earn a commission from affiliate links.</footer>"

    def handler(request):
        return httpx.Response(
            200,
            text="User-agent: *\nAllow: /" if request.url.path == "/robots.txt" else html,
            headers={
                "Content-Type": "text/plain" if request.url.path == "/robots.txt" else "text/html"
            },
        )

    record = PageVerificationProvider(fetcher(handler)).verify(source(), [CLAIM]).verification
    assert record.claims[0].status == "VERIFIED_ON_PAGE"
    assert record.category == "REVIEW_AFFILIATE"
