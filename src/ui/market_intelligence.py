"""V3 report views read persisted observations and calculate locally."""

import streamlit as st

from src.database.market_repository import MarketIntelligenceRepository
from src.research.market_intelligence import MarketIntelligenceService
from src.research.verification import status_label


def current_market_report(product, repo):
    return MarketIntelligenceService(MarketIntelligenceRepository(repo)).recalculate(product)


def render_page_support(report, prefix="market"):
    st.caption(
        "Supported on source page confirms attribution to the publisher, "
        "not objective truth or independent market verification."
    )
    for page in report.page_verifications:
        st.markdown(
            f"**{page.page_title or page.publisher}** · {page.category.replace('_', ' ').title()}"
        )
        st.link_button(
            "Open source page",
            page.canonical_url,
            key=f"{prefix}_source_{report.product_id}_{page.source_id}",
        )
        known = []
        for label, value in (("Published", page.published_at), ("Updated", page.updated_at)):
            if value:
                known.append(f"{label} {value:%Y-%m-%d}")
        st.caption(" · ".join(known) or "Publication date: Unknown")
        st.caption(f"Accessed {page.accessed_at:%Y-%m-%d %H:%M} UTC · {page.classification_reason}")
        for claim in page.claims:
            st.markdown(f"**{status_label(claim.status)}** · {claim.claim}")
            if claim.supporting_excerpt:
                st.caption(f"Page excerpt: {claim.supporting_excerpt}")


def render_telemetry(run):
    st.markdown("**Research-run requests and cache usage**")
    if not run:
        st.caption("No research run recorded. Navigation makes no external requests.")
        return
    tools = run.web_search_calls if run.web_search_calls is not None else "Unknown"
    st.markdown(
        f"OpenAI model requests: **{run.openai_model_requests}** · web_search calls: **{tools}**"
    )
    st.markdown(
        f"Source-page fetch attempts: **{run.page_fetch_count}** · "
        f"Page HTTP requests (robots/redirects included): **{run.page_request_count}** · "
        f"Demand-provider requests: **{run.demand_requests}**"
    )
    st.caption("Providers actually used: " + (", ".join(run.providers_used) or "None"))
    st.caption(f"Cache hits: {len(run.cache_hits)} · " + ", ".join(run.cache_hits))
    st.caption(f"Run {run.run_id} · {run.started_at:%Y-%m-%d %H:%M:%S} UTC")
    if not (run.openai_model_requests or run.page_request_count or run.demand_requests):
        st.caption("No external requests were made in this run.")
    st.caption("Dollar cost unavailable: request counts are not a reliable billing estimate.")
    for stage in run.stages:
        st.write(
            f"{stage.stage.title()} · {stage.provider or 'no provider'} · {stage.status}"
            + (" · Previous dated result retained" if stage.retained else "")
        )
        if stage.notice:
            st.caption(stage.notice)


def render_market_intelligence(product, repo):
    st.markdown("**MARKET INTELLIGENCE · V3**")
    report = current_market_report(product, repo)
    run = MarketIntelligenceRepository(repo).latest_run(product.id)
    if not report:
        st.info("Measured demand data unavailable")
        st.info("No V3 report for these inputs. Use Research product to collect evidence.")
        st.write("Insufficient price observations")
        render_telemetry(run)
        return
    st.caption(
        f"Report collected {report.researched_at:%Y-%m-%d %H:%M} UTC · "
        "OBSERVED metrics · Publisher attribution · ESTIMATED finances · AI JUDGEMENT"
    )
    demand, trend, score = report.demand, report.trend, report.score
    st.markdown("**Demand · relative search-interest / popularity data**")
    if demand.status != "completed" or not demand.observations:
        st.info("Measured demand data unavailable")
    else:
        st.caption(
            f"Provider {demand.provider} · Query {demand.query} · Location {demand.location} · "
            f"Collected {demand.collected_at:%Y-%m-%d %H:%M} UTC"
        )
        st.dataframe(
            [
                {
                    "Period start": o.period_start,
                    "Period end": o.period_end,
                    "Raw provider value": o.value,
                    "Unit": o.unit,
                    "Missing": o.missing,
                }
                for o in demand.observations
            ],
            hide_index=True,
            width="stretch",
        )
    st.caption(
        "Relative popularity is not monthly search volume or measured sales. "
        "Raw provider values are separate from our deterministic classification."
    )
    st.markdown(f"**Trend: {trend.classification.replace('_', ' ').title()}**")
    if trend.change_percent is not None:
        st.write(
            f"Recent average {trend.recent_average:.2f}; prior average {trend.prior_average:.2f}; "
            f"change {trend.change_percent:+.2f}% · {trend.observation_count} observations"
        )
        st.caption(f"Period {trend.period_start} to {trend.period_end}")
    for note in trend.notes:
        st.caption(note)
    st.markdown("**Market pricing · OBSERVED structured listing metadata**")
    if not report.price_observations:
        st.write("Insufficient price observations")
    for price in report.price_observations:
        st.write(
            f"{price.retailer} · {price.product_name} · {price.currency} {price.price:.2f} · "
            f"{price.availability} · {price.match_outcome.replace('_', ' ')}"
        )
        st.link_button("Inspect listing", price.url)
        st.caption(
            f"Observed {price.observed_at:%Y-%m-%d %H:%M} UTC · " + "; ".join(price.match_reasons)
        )
    for group in report.price_summaries:
        st.markdown(
            f"**{group.product_name}** · Brand: {group.brand or 'Unspecified'} · "
            f"Variant: {group.variant or 'Unspecified'}"
        )
        if group.minimum is None:
            st.write(
                f"{group.currency} · {group.count} listing(s) · Insufficient price observations"
            )
        else:
            st.write(
                f"{group.currency} · Low {group.minimum:.2f} · Median {group.median:.2f} · "
                f"High {group.maximum:.2f} · {group.count} compatible listings"
            )
    st.caption(
        "Observed listings are not a true market price; "
        "currencies, brands and variants stay separate."
    )
    st.markdown("**Source quality and confidence**")
    st.write(
        f"Eligible independent publisher proxies: {score.independent_domains} · "
        f"Seller/marketplace/manufacturer pages: {score.seller_sources} · "
        f"Independent claims supported on page: {score.supported_claims}"
    )
    st.markdown(f"**Confidence: {score.confidence.upper()}**")
    for text in score.positives:
        st.write(f"✓ {text}")
    for text in score.missing:
        st.write(f"Missing: {text}")
    st.caption(
        "Different domains do not prove independent ownership; seller claims do not "
        "establish measured demand."
    )
    render_page_support(report)
    st.markdown("**V3 prioritization score and recommendation**")
    st.write(f"{score.final_score:.1f} / 100 · {score.recommendation}")
    st.dataframe(
        [
            {
                "Dimension": k,
                "Raw value (0–10)": v,
                "Weight": score.weights[k],
                "Weighted points": score.contributions[k],
            }
            for k, v in score.dimensions.items()
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        f"Raw {score.raw_score:.4f} × confidence factor {score.confidence_factor:.2f} "
        f"= {score.final_score:.1f} · {score.version}"
    )
    st.caption(
        "A prioritization heuristic, not a probability of commercial success. "
        "Legacy V1/V2 saved scores remain separate and unchanged."
    )
    for flag in report.risk_flags:
        st.caption(f"Risk / limitation: {flag}")
    render_telemetry(run)
