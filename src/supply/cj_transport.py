"""Fixed CJ research endpoints only; see docs/v4-provider-contracts.md."""

import json
import math
import os
import re
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from enum import StrEnum
from hashlib import sha256
from threading import RLock
from types import MappingProxyType
from typing import Any
from uuid import uuid4
from weakref import WeakValueDictionary

import httpx

from src.supply.models import ActionTelemetry, LimitSource, LocalLimit


class CJOperation(StrEnum):
    SEARCH = "search"
    DETAILS = "details"
    VARIANTS = "variants"
    STOCK = "stock"
    SHIPPING = "shipping"


_HOST = "https://developers.cjdropshipping.com"
_ROOT = "/api2.0/v1/"
_ROUTES = MappingProxyType(
    {
        "auth": ("POST", "authentication/getAccessToken"),
        "auth_refresh": ("POST", "authentication/refreshAccessToken"),
        "search": ("GET", "product/listV2"),
        "details": ("GET", "product/query"),
        "variants": ("GET", "product/variant/query"),
        "stock": ("GET", "product/stock/queryByVid"),
        "shipping": ("POST", "logistic/freightCalculate"),
    }
)
_RATE_CODES = {1600200, 1600201, 16900500}
_TRANSIENT_CODES = {1600000, 1600301}
_AUTH_CODES = set(range(1600001, 1600009))
_BODY_LIMIT = 2 * 1024 * 1024
_CACHE_LIMIT = 16
_CACHE_LOCK = RLock()


@dataclass(repr=False)
class _CredentialState:
    context: str = field(default_factory=lambda: str(uuid4()))
    lock: RLock = field(default_factory=RLock)
    access: str | None = None
    access_expiry: datetime | None = None
    refresh: str | None = None
    refresh_expiry: datetime | None = None
    last_dispatch: float | None = None
    next_allowed: float = 0.0


_TOKEN_CACHE: OrderedDict[str, _CredentialState] = OrderedDict()
# Weak references do not retain evicted tokens; active providers still share a lock.
_ACTIVE_STATES: WeakValueDictionary[str, _CredentialState] = WeakValueDictionary()


@dataclass
class CJTransportOutcome:
    """Internal payload repr-hidden; provider exposes validated sanitized records."""

    status: str
    data: Any = field(default=None, repr=False)
    notice: str = ""
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    code: int | None = None
    limit_source: LimitSource | None = None
    retry_blocked_by: LocalLimit | None = None
    retryable: bool = field(default=False, repr=False)
    retry_after: float = field(default=0.0, repr=False)


def _text(value: Any, maximum: int = 200) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= maximum
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _country(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Z]{2}", value) is not None


def _params(operation: CJOperation, params: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(params, Mapping):
        return None
    if operation == CJOperation.SEARCH:
        if (
            set(params) != {"keyWord", "page", "size"}
            or not _text(params["keyWord"])
            or type(params["page"]) is not int
            or not 1 <= params["page"] <= 2
            or type(params["size"]) is not int
            or not 1 <= params["size"] <= 10
        ):
            return None
    elif operation in {CJOperation.DETAILS, CJOperation.VARIANTS, CJOperation.STOCK}:
        key = "vid" if operation == CJOperation.STOCK else "pid"
        if set(params) != {key} or not _text(params[key]):
            return None
    else:
        if set(params) != {"startCountryCode", "endCountryCode", "products", "storageIdList"}:
            return None
        products, storage = params["products"], params["storageIdList"]
        if (
            not _country(params["startCountryCode"])
            or not _country(params["endCountryCode"])
            or not isinstance(products, list)
            or len(products) != 1
            or not isinstance(products[0], dict)
            or set(products[0]) != {"quantity", "vid"}
            or type(products[0]["quantity"]) is not int
            or products[0]["quantity"] <= 0
            or not _text(products[0]["vid"])
            or not isinstance(storage, list)
            or len(storage) != 1
            or not _text(storage[0])
        ):
            return None
        return {
            "startCountryCode": params["startCountryCode"],
            "endCountryCode": params["endCountryCode"],
            "products": [dict(products[0])],
            "storageIdList": list(storage),
        }
    return dict(params)


class CJResearchTransport:
    """Named research operations; an explicit action owns a bounded dispatch budget."""

    def __init__(
        self,
        *,
        http_transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self._credential = os.environ.get("CJ_API_KEY", "").strip()
        self._http_transport = http_transport
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._action_lock = RLock()
        self._state = None
        if self._credential:
            scope = sha256(self._credential.encode()).hexdigest()
            with _CACHE_LOCK:
                state = _TOKEN_CACHE.get(scope) or _ACTIVE_STATES.get(scope)
                if state is None:
                    state = _CredentialState()
                _TOKEN_CACHE[scope] = state
                _ACTIVE_STATES[scope] = state
                _TOKEN_CACHE.move_to_end(scope)
                while len(_TOKEN_CACHE) > _CACHE_LIMIT:
                    _TOKEN_CACHE.popitem(last=False)
                self._state = state
        self.reset_action(ActionTelemetry())

    @property
    def configured(self) -> bool:
        return bool(self._credential)

    @property
    def cache_context(self) -> str:
        """Opaque backend nonce isolates account-dependent catalogs without key hashes."""
        return self._state.context if self._state is not None else "unavailable"

    def reset_action(
        self, telemetry: ActionTelemetry, *, max_requests: int = 12, max_seconds: float = 90
    ) -> None:
        if (
            type(max_requests) is not int
            or not 1 <= max_requests <= 12
            or isinstance(max_seconds, bool)
            or not isinstance(max_seconds, (int, float))
            or not math.isfinite(max_seconds)
            or not 0 < max_seconds <= 90
        ):
            raise ValueError("CJ action limits exceed the supported research budget")
        with self._action_lock:
            self.telemetry = telemetry
            self._started = self._monotonic()
            self._max_requests = max_requests
            self._deadline = self._started + max_seconds
            self._dispatches = 0

    def _outcome(self, status: str, notice: str = "", **kwargs) -> CJTransportOutcome:
        return CJTransportOutcome(
            status=status, notice=notice, observed_at=self._clock().astimezone(UTC), **kwargs
        )

    def request(
        self, operation: CJOperation | str, params: Mapping[str, Any]
    ) -> CJTransportOutcome:
        try:
            named_operation = CJOperation(operation)
        except (ValueError, TypeError):
            return self._outcome("UNSUPPORTED", "CJ operation is unsupported.")
        safe_params = _params(named_operation, params)
        if safe_params is None:
            return self._outcome("UNSUPPORTED", "CJ research parameters are unsupported.")
        if not self.configured:
            return self._outcome("UNAVAILABLE", "CJ supplier research is not configured.")
        with self._action_lock, self._state.lock:
            try:
                retry = [1]
                token_result = self._ensure_token(retry)
                if token_result is not None:
                    return token_result
                result = self._attempt(named_operation.value, safe_params, retry)
                if result.code in _AUTH_CODES and retry[0]:
                    self._state.access = None
                    self._state.access_expiry = None
                    retry[0] -= 1
                    self.telemetry.retries += 1
                    token_result = self._ensure_token(retry)
                    if token_result is not None:
                        return token_result
                    result = self._attempt(named_operation.value, safe_params, retry)
                return result
            finally:
                self.telemetry.elapsed_seconds = max(0, self._monotonic() - self._started)

    def _ensure_token(self, retry: list[int]) -> CJTransportOutcome | None:
        state = self._state
        now = self._clock().astimezone(UTC)
        if (
            state.access
            and state.access_expiry
            and state.access_expiry > now + timedelta(seconds=60)
        ):
            if "cj_token" not in self.telemetry.cache_hits:
                self.telemetry.cache_hits.append("cj_token")
            return None
        refresh_valid = bool(
            state.refresh
            and state.refresh_expiry
            and state.refresh_expiry > now + timedelta(seconds=60)
        )
        operation = "auth_refresh" if refresh_valid else "auth"
        params = {"refreshToken": state.refresh} if refresh_valid else {"apiKey": self._credential}
        result = self._attempt(operation, params, retry)
        if operation == "auth_refresh" and result.code in _AUTH_CODES and retry[0]:
            state.refresh = None
            state.refresh_expiry = None
            retry[0] -= 1
            self.telemetry.retries += 1
            result = self._attempt("auth", {"apiKey": self._credential}, retry)
        if result.status != "SUCCESS":
            return result
        try:
            data = result.data
            access, refresh = data["accessToken"], data["refreshToken"]
            access_expiry = datetime.fromisoformat(
                data["accessTokenExpiryDate"].replace("Z", "+00:00")
            )
            refresh_expiry = datetime.fromisoformat(
                data["refreshTokenExpiryDate"].replace("Z", "+00:00")
            )
            if (
                not _text(access, 1000)
                or not _text(refresh, 1000)
                or access_expiry.tzinfo is None
                or refresh_expiry.tzinfo is None
                or access_expiry <= self._clock() + timedelta(seconds=60)
                or refresh_expiry <= self._clock()
            ):
                raise ValueError("Invalid token contract")
        except (KeyError, TypeError, ValueError, AttributeError):
            return self._outcome("FAILED", "CJ authentication response is invalid.")
        state.access, state.refresh = access, refresh
        state.access_expiry = access_expiry.astimezone(UTC)
        state.refresh_expiry = refresh_expiry.astimezone(UTC)
        return None

    def _attempt(self, operation: str, params: dict, retry: list[int]) -> CJTransportOutcome:
        result = self._dispatch(operation, params)
        if result.retryable and retry[0]:
            wait = max(1.0, result.retry_after)
            if self._dispatches >= self._max_requests or self._monotonic() + wait >= self._deadline:
                source = (
                    "LOCAL_REQUEST_BUDGET"
                    if self._dispatches >= self._max_requests
                    else "LOCAL_TIME_BUDGET"
                )
                if result.status == "RATE_LIMITED":
                    return self._outcome(
                        "RATE_LIMITED",
                        result.notice + " Local action budget prevents a retry.",
                        code=result.code,
                        limit_source=result.limit_source,
                        retry_blocked_by=source,
                    )
                return self._outcome(
                    "BUDGET_EXHAUSTED",
                    "Local CJ action budget prevents a retry. " + result.notice,
                    limit_source=source,
                )
            self._sleeper(wait)
            retry[0] -= 1
            self.telemetry.retries += 1
            result = self._dispatch(operation, params)
        return result

    def _retry_after(self, value: str | None) -> float:
        if not value:
            return 1.0
        try:
            seconds = float(value)
            if math.isfinite(seconds):
                return max(0, seconds)
        except (TypeError, ValueError):
            pass
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is not None:
                return max(
                    0, (date.astimezone(UTC) - self._clock().astimezone(UTC)).total_seconds()
                )
        except (TypeError, ValueError, OverflowError):
            pass
        return 1.0

    def _dispatch(self, operation: str, params: dict) -> CJTransportOutcome:
        remaining = self._deadline - self._monotonic()
        if self._dispatches >= self._max_requests:
            return self._outcome(
                "BUDGET_EXHAUSTED",
                "Local CJ request budget exhausted; no request dispatched.",
                limit_source="LOCAL_REQUEST_BUDGET",
            )
        if remaining <= 0:
            return self._outcome(
                "BUDGET_EXHAUSTED",
                "Local CJ action time budget exhausted; no request dispatched.",
                limit_source="LOCAL_TIME_BUDGET",
            )
        spacing = (
            max(0.0, 1.0 - (self._monotonic() - self._state.last_dispatch))
            if self._state.last_dispatch is not None
            else 0.0
        )
        wait = max(spacing, self._state.next_allowed - self._monotonic())
        if wait >= remaining:
            return self._outcome(
                "BUDGET_EXHAUSTED",
                "Local CJ action time budget cannot accommodate spacing or cooldown; "
                "no request dispatched.",
                limit_source="LOCAL_TIME_BUDGET",
            )
        if wait:
            self._sleeper(wait)
        remaining = self._deadline - self._monotonic()
        if remaining <= 0:
            return self._outcome(
                "BUDGET_EXHAUSTED",
                "Local CJ action time budget exhausted; no request dispatched.",
                limit_source="LOCAL_TIME_BUDGET",
            )
        method, route = _ROUTES[operation]
        url = _HOST + _ROOT + route
        headers = {"Accept": "application/json"}
        if operation not in {"auth", "auth_refresh"}:
            headers["CJ-Access-Token"] = self._state.access
        self._dispatches += 1
        self.telemetry.requests[operation] = self.telemetry.requests.get(operation, 0) + 1
        self._state.last_dispatch = self._monotonic()
        try:
            # Fresh clients prevent response cookies from affecting subsequent calls.
            with httpx.Client(
                transport=self._http_transport,
                trust_env=False,
                follow_redirects=False,
                timeout=min(20.0, remaining),
            ) as client:
                arguments = {"params": params} if method == "GET" else {"json": params}
                with client.stream(method, url, headers=headers, **arguments) as response:
                    status = response.status_code
                    if status == 429:
                        delay = self._retry_after(response.headers.get("Retry-After"))
                        self._state.next_allowed = self._monotonic() + delay
                        return self._outcome(
                            "RATE_LIMITED",
                            "CJ rate limit reached.",
                            retryable=True,
                            retry_after=delay,
                            limit_source="PROVIDER_RATE_LIMIT",
                        )
                    if status < 200 or status >= 300:
                        retryable = 500 <= status <= 599
                        delay = self._retry_after(response.headers.get("Retry-After"))
                        if retryable:
                            self._state.next_allowed = self._monotonic() + delay
                        return self._outcome(
                            "FAILED",
                            f"CJ HTTP request failed ({status}).",
                            retryable=retryable,
                            retry_after=delay,
                        )
                    content_length = response.headers.get("Content-Length", "")
                    if content_length.isdigit() and int(content_length) > _BODY_LIMIT:
                        return self._outcome("FAILED", "CJ response exceeds the size limit.")
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        if len(content) + len(chunk) > _BODY_LIMIT:
                            return self._outcome("FAILED", "CJ response exceeds the size limit.")
                        content.extend(chunk)
                        if self._monotonic() >= self._deadline:
                            return self._outcome(
                                "BUDGET_EXHAUSTED",
                                "Local CJ action time budget exhausted while reading the response.",
                                limit_source="LOCAL_TIME_BUDGET",
                            )
                    envelope = json.loads(content)
        except (httpx.TimeoutException, httpx.TransportError):
            return self._outcome("FAILED", "CJ transport request failed.", retryable=True)
        except (ValueError, TypeError, RecursionError, httpx.DecodingError):
            return self._outcome("FAILED", "CJ response is malformed.")
        if not isinstance(envelope, dict) or type(envelope.get("code")) is not int:
            return self._outcome("FAILED", "CJ response envelope is malformed.")
        code = envelope["code"]
        success = envelope.get("result") is True or envelope.get("success") is True
        contradictory = envelope.get("result") is False or envelope.get("success") is False
        if code == 200 and success and not contradictory:
            return self._outcome("SUCCESS", data=envelope.get("data"), code=code)
        if code in _RATE_CODES:
            return self._outcome(
                "RATE_LIMITED",
                f"CJ rate or quota limit ({code}).",
                code=code,
                limit_source="PROVIDER_QUOTA_LIMIT",
            )
        return self._outcome(
            "FAILED",
            f"CJ request failed (code {code}).",
            code=code,
            retryable=code in _TRANSIENT_CODES,
        )
