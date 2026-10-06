"""Conservative arithmetic over one uniformly sampled normalization series."""

from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Literal

from pydantic import BaseModel, Field

from src.research.providers.demand_trend import DemandObservation


class TrendResult(BaseModel):
    classification: Literal[
        "STRONGLY_GROWING",
        "GROWING",
        "STABLE",
        "DECLINING",
        "STRONGLY_DECLINING",
        "INSUFFICIENT_DATA",
    ] = "INSUFFICIENT_DATA"
    prior_average: float | None = None
    recent_average: float | None = None
    change_percent: float | None = None
    observation_count: int = 0
    period_start: date | None = None
    period_end: date | None = None
    notes: list[str] = Field(default_factory=list)


def calculate_trend(
    observations: list[DemandObservation], now: datetime | None = None
) -> TrendResult:
    now = now or datetime.now(timezone.utc)

    def insufficient(reason):
        return TrendResult(notes=[reason])

    if not observations:
        return insufficient("No measured observations.")
    identities = {
        (o.provider, o.query, o.location, o.unit, o.series_id, o.metric_name) for o in observations
    }
    if len(identities) != 1:
        return insufficient(
            "Incompatible providers, queries, regions, units or normalization series."
        )
    bins = {}
    for o in observations:
        key = (o.period_start, o.period_end)
        if key in bins and (bins[key].value, bins[key].missing) != (o.value, o.missing):
            return insufficient("Conflicting duplicate observations.")
        bins[key] = o
    ordered = sorted(bins.values(), key=lambda o: o.period_start)
    durations = {(o.period_end - o.period_start).days + 1 for o in ordered}
    if len(durations) != 1 or min(durations) <= 0:
        return insufficient("Periods are not uniform valid intervals.")
    cadence = durations.pop()
    if any(o.period_end >= now.date() for o in ordered):
        return insufficient("Future or unclosed observation periods.")
    if (now.date() - ordered[-1].period_end).days > 30:
        return insufficient("Latest closed observation is over 30 days old.")
    origin = ordered[0].period_start
    for i, o in enumerate(ordered):
        if (o.period_start - origin).days % cadence:
            return insufficient("Overlapping or irregular observation periods.")
        if i and o.period_start <= ordered[i - 1].period_end:
            return insufficient("Overlapping observation periods.")
    end = ordered[-1].period_end
    slots = ((end - origin).days + 1) // cadence
    preferred = max(3, round(90 / cadence))
    per_window = min(preferred, slots // 2)
    if per_window < 3:
        return insufficient("At least three observations per equal window are required.")
    window_days = per_window * cadence
    boundary = end - timedelta(days=window_days - 1)
    first = boundary - timedelta(days=window_days)
    valid = [
        o
        for o in ordered
        if o.period_start >= first
        and not o.missing
        and o.value is not None
        and not (o.unit == "relative_popularity_index" and o.value == 0)
    ]
    prior = [o.value for o in valid if o.period_start < boundary]
    recent = [o.value for o in valid if o.period_start >= boundary]
    if min(len(prior), len(recent)) < 3 or min(len(prior), len(recent)) / per_window < 0.8:
        return insufficient(
            "Each equal window needs at least 80% coverage and three valid observations."
        )
    a, b = mean(prior), mean(recent)
    if a <= 0:
        return insufficient("Prior average is not positive; percentage change is undefined.")
    change = 100 * (b - a) / a
    classification = (
        "STRONGLY_GROWING"
        if change >= 50
        else "GROWING"
        if change >= 15
        else "STABLE"
        if change > -15
        else "DECLINING"
        if change > -50
        else "STRONGLY_DECLINING"
    )
    return TrendResult(
        classification=classification,
        prior_average=a,
        recent_average=b,
        change_percent=change,
        observation_count=len(valid),
        period_start=first,
        period_end=end,
        notes=[
            f"Two adjacent {window_days}-day windows; "
            f"coverage {len(prior)}/{per_window} and {len(recent)}/{per_window}. "
            "Relative popularity does not establish absolute demand."
        ],
    )
