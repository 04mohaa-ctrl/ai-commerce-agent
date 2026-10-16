"""Bounded public HTTPS retrieval. No browser, proxy, cookies or alternate identities."""

import ipaddress
import math
import queue
import re
import socket
import ssl
import threading
import time
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpcore
import httpx

MAX_BODY_BYTES = 2 * 1024 * 1024
USER_AGENT = "AICommerceResearch/3.0"


@dataclass(frozen=True)
class FetchResult:
    url: str
    text: str
    status_code: int | None
    status: Literal["success", "blocked", "unavailable"]
    reason: str
    fetched_at: datetime


class _Rejected(Exception):
    def __init__(self, reason: str, status: str = "blocked", status_code: int | None = None):
        self.reason = reason
        self.status = status
        self.status_code = status_code


def _robots_octets(value: str, *, pattern: bool) -> str:
    """Normalize UTF-8 and encoded unreserved octets without decoding reserved separators."""
    unreserved = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
    result, index = [], 0
    while index < len(value):
        char = value[index]
        if char == "%":
            encoded = value[index + 1 : index + 3]
            if len(encoded) != 2 or not re.fullmatch(r"[a-fA-F0-9]{2}", encoded):
                raise _Rejected("Robots policy has unsupported percent encoding.")
            decoded = chr(int(encoded, 16))
            result.append(decoded if decoded in unreserved else "%" + encoded.upper())
            index += 3
            continue
        if ord(char) < 32 or ord(char) == 127:
            raise _Rejected("Robots policy contains unsupported characters.")
        if ord(char) > 127 or char == " " or (not pattern and char in "*$"):
            result.append(quote(char, safe=""))
        else:
            result.append(char)
        index += 1
    return "".join(result)


def _robots_match(pattern: str, path: str) -> bool:
    """Match star-separated literals in linear scans, avoiding regex backtracking."""
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    if "*" not in body:
        return path == body if anchored else path.startswith(body)
    pieces = body.split("*")
    if not path.startswith(pieces[0]):
        return False
    position = len(pieces[0])
    limit = len(path)
    if anchored:
        last = pieces[-1]
        if not path.endswith(last):
            return False
        limit -= len(last)
        pieces = pieces[:-1]
    for piece in pieces[1:]:
        found = path.find(piece, position, limit)
        if found < 0:
            return False
        position = found + len(piece)
    return position <= limit


class _RobotsPolicy:
    """RFC 9309 matching with conservative rejection of ambiguous policy syntax."""

    def __init__(self, text: str, check_deadline):
        self.groups = []
        self.check_deadline = check_deadline
        agents, rules = [], []
        has_rules = False
        for raw in text.lstrip("\ufeff").splitlines():
            check_deadline()
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" not in line:
                raise _Rejected("Robots policy has unsupported syntax.")
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.casefold()
            if key == "user-agent":
                if value != "*" and not re.fullmatch(r"[A-Za-z_-]+", value):
                    raise _Rejected("Robots policy has an unsupported user-agent token.")
                if has_rules:
                    self.groups.append((agents, rules))
                    agents, rules, has_rules = [], [], False
                agents.append(value.casefold())
            elif key in {"allow", "disallow"}:
                if not agents:
                    raise _Rejected("Robots policy contains ungrouped rules.")
                has_rules = True
                if not value:
                    continue
                if not value.startswith(("/", "*")) or "$" in value[:-1] or len(value) > 4000:
                    raise _Rejected("Robots policy has an unsupported path pattern.")
                normalized = _robots_octets(value, pattern=True)
                # Encoded octets count once. Wildcard and end-marker are operators.
                literal = normalized.rstrip("$").replace("*", "")
                specificity = len(re.sub(r"%[A-F0-9]{2}", "x", literal))
                rules.append((normalized, specificity, key == "allow"))
            elif key not in {"sitemap", "host", "crawl-delay", "request-rate"}:
                raise _Rejected("Robots policy contains an unsupported directive.")
            if len(self.groups) > 5000 or len(rules) > 5000:
                raise _Rejected("Robots policy complexity limit exceeded.")
        if agents:
            self.groups.append((agents, rules))
        if not self.groups:
            raise _Rejected("Robots policy could not be established.")

    def can_fetch(self, useragent: str, url: str) -> bool:
        token = useragent.split("/", 1)[0].casefold()
        specific = [rules for agents, rules in self.groups if token in agents]
        groups = specific or [rules for agents, rules in self.groups if "*" in agents]
        parsed = urlsplit(url)
        path = _robots_octets(
            (parsed.path or "/") + ("?" + parsed.query if parsed.query else ""), pattern=False
        )
        matches = []
        for rules in groups:
            for pattern, specificity, allowed in rules:
                self.check_deadline()
                if _robots_match(pattern, path):
                    matches.append((specificity, allowed))
        # Equal-specificity allow takes precedence independent of declaration order.
        return max(matches)[1] if matches else True


def _remaining(deadline: float, monotonic: Callable[[], float], timeout=None) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise _Rejected("Total retrieval deadline exceeded.", "unavailable")
    return min(remaining, timeout) if timeout is not None else remaining


class _DeadlineStream(httpcore.NetworkStream):
    """Apply the remaining absolute budget before each socket operation, including TLS."""

    def __init__(self, stream, deadline, monotonic):
        self.stream, self.deadline, self.monotonic = stream, deadline, monotonic

    def read(self, max_bytes, timeout=None):
        return self.stream.read(max_bytes, _remaining(self.deadline, self.monotonic, timeout))

    def write(self, buffer, timeout=None):
        return self.stream.write(buffer, _remaining(self.deadline, self.monotonic, timeout))

    def close(self):
        self.stream.close()

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        stream = self.stream.start_tls(
            ssl_context, server_hostname, _remaining(self.deadline, self.monotonic, timeout)
        )
        return _DeadlineStream(stream, self.deadline, self.monotonic)

    def get_extra_info(self, info):
        return self.stream.get_extra_info(info)


class _DeadlineBackend(httpcore.NetworkBackend):
    def __init__(self, deadline, monotonic):
        self.backend = httpcore.SyncBackend()
        self.deadline, self.monotonic = deadline, monotonic

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        # System getaddrinfo is not covered by socket timeouts. Resolve on a bounded
        # worker and connect only to a numeric address; HTTPcore retains the original
        # host for TLS verification and SNI. A timed-out worker never opens a socket.
        try:
            ipaddress.ip_address(host)
            address = host
        except ValueError:
            answers = queue.Queue(maxsize=1)

            def resolve():
                try:
                    answers.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
                except OSError:
                    answers.put(None)

            threading.Thread(target=resolve, daemon=True).start()
            try:
                resolved = answers.get(timeout=_remaining(self.deadline, self.monotonic, timeout))
            except queue.Empty:
                raise _Rejected("DNS deadline exceeded.", "unavailable") from None
            _remaining(self.deadline, self.monotonic, timeout)
            if not resolved:
                raise httpcore.ConnectError("DNS resolution failed.")
            address = resolved[0][4][0]
        stream = self.backend.connect_tcp(
            address,
            port,
            _remaining(self.deadline, self.monotonic, timeout),
            local_address,
            socket_options,
        )
        return _DeadlineStream(stream, self.deadline, self.monotonic)

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise _Rejected("Local sockets are not supported.")

    def sleep(self, seconds):
        raise _Rejected("Transport retries are not supported.")


class _CoreResponseStream(httpx.SyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    def __iter__(self):
        yield from self.stream

    def close(self):
        self.stream.close()


class _DeadlineTransport(httpx.BaseTransport):
    """HTTPX transport using HTTPcore's public backend API for a strict total deadline."""

    def __init__(self, deadline, monotonic):
        self.pool = httpcore.ConnectionPool(
            ssl_context=ssl.create_default_context(),
            max_connections=1,
            max_keepalive_connections=0,
            retries=0,
            network_backend=_DeadlineBackend(deadline, monotonic),
        )

    def handle_request(self, request):
        response = self.pool.handle_request(
            httpcore.Request(
                method=request.method,
                url=httpcore.URL(
                    scheme=request.url.raw_scheme,
                    host=request.url.raw_host,
                    port=request.url.port,
                    target=request.url.raw_path,
                ),
                headers=request.headers.raw,
                content=request.stream,
                extensions=request.extensions,
            )
        )
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=_CoreResponseStream(response.stream),
            extensions=response.extensions,
        )

    def close(self):
        self.pool.close()


def _resolve(host: str) -> list[str]:
    return list({answer[4][0] for answer in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})


class SafePageFetcher:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: Callable[[str], Iterable[str]] | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        total_timeout: float = 10.0,
        connect_timeout: float = 3.0,
        read_timeout: float = 3.0,
    ):
        if any(
            not math.isfinite(value) or value <= 0
            for value in (total_timeout, connect_timeout, read_timeout)
        ):
            raise ValueError("Timeouts must be finite and positive.")
        self.transport = transport
        self.resolver = resolver or _resolve
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic
        self.total_timeout, self.connect_timeout, self.read_timeout = (
            total_timeout,
            connect_timeout,
            read_timeout,
        )
        self.request_count = 0
        self.source_fetch_count = 0

    def _target(self, value: str, deadline: float) -> tuple[str, str, str]:
        try:
            if any(ord(char) < 33 for char in value) or "\\" in value:
                raise ValueError
            parsed = urlsplit(value)
            host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
            if (
                parsed.scheme.lower() != "https"
                or not host
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in (None, 443)
                or "%" in host
                or host == "localhost"
                or host.endswith((".localhost", ".local", ".internal", ".home", ".lan"))
            ):
                raise ValueError
            try:
                literal = ipaddress.ip_address(host)
            except ValueError:
                literal = None
                if "." not in host:
                    raise ValueError
            if literal is not None:
                answers = [str(literal)]
            else:
                # A stuck system DNS call cannot consume the page budget indefinitely.
                result_queue = queue.Queue(maxsize=1)

                def resolve():
                    try:
                        result_queue.put(list(self.resolver(host)))
                    except Exception:
                        result_queue.put(None)

                worker = threading.Thread(target=resolve, daemon=True)
                worker.start()
                try:
                    answers = result_queue.get(timeout=_remaining(deadline, self.monotonic))
                except queue.Empty:
                    raise _Rejected("DNS resolution deadline exceeded.", "unavailable") from None
            if not answers:
                raise ValueError
            addresses = [ipaddress.ip_address(answer) for answer in answers]
            if any(
                not address.is_global
                or address.is_multicast
                or address.is_reserved
                or address.is_unspecified
                or (
                    getattr(address, "ipv4_mapped", None) is not None
                    and not address.ipv4_mapped.is_global
                )
                for address in addresses
            ):
                raise ValueError
            authority = f"[{host}]" if ":" in host else host
            normalized = urlunsplit(("https", authority, parsed.path or "/", parsed.query, ""))
            return normalized, host, str(addresses[0])
        except (ValueError, UnicodeError):
            raise _Rejected("Unsafe public HTTPS target or DNS answers.") from None

    def _get(self, url: str, host: str, address: str, deadline: float):
        remaining = _remaining(deadline, self.monotonic)
        target = httpx.URL(url).copy_with(host=address)
        transport = self.transport or _DeadlineTransport(deadline, self.monotonic)
        # A fresh client per GET prevents response cookies from reaching any next request.
        with httpx.Client(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(
                min(self.read_timeout, remaining), connect=min(self.connect_timeout, remaining)
            ),
        ) as client:
            self.request_count += 1
            with client.stream(
                "GET",
                target,
                headers={
                    "Host": f"[{host}]" if ":" in host else host,
                    "User-Agent": USER_AGENT,
                    "Accept-Encoding": "identity",
                    "Accept": "text/html, text/plain",
                },
                extensions={"sni_hostname": host},
            ) as response:
                _remaining(deadline, self.monotonic)
                headers = dict(response.headers)
                if response.status_code in {301, 302, 303, 307, 308}:
                    return response.status_code, headers, ""
                if response.status_code != 200:
                    return response.status_code, headers, ""
                content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
                    raise _Rejected("Unsupported page content type.", "unavailable", 200)
                if "attachment" in headers.get("content-disposition", "").lower():
                    raise _Rejected("Page downloads are not supported.", "unavailable", 200)
                chunks = []
                size = 0
                encoding = headers.get("content-encoding", "identity").lower()
                decoder = None
                if response.is_stream_consumed:
                    stream = [response.content]  # HTTPX fixture/eager content is already decoded.
                else:
                    if encoding == "gzip":
                        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                    elif encoding == "deflate":
                        decoder = zlib.decompressobj()
                    elif encoding != "identity":
                        raise _Rejected("Unsupported page content encoding.", "unavailable", 200)
                    stream = response.iter_raw()
                for chunk in stream:
                    _remaining(deadline, self.monotonic)
                    decoded = (
                        decoder.decompress(chunk, MAX_BODY_BYTES - size + 1) if decoder else chunk
                    )
                    size += len(decoded)
                    if size > MAX_BODY_BYTES or (decoder and decoder.unconsumed_tail):
                        raise _Rejected("Decoded page size limit exceeded.", "unavailable", 200)
                    chunks.append(decoded)
                if decoder:
                    tail = decoder.flush(MAX_BODY_BYTES - size + 1)
                    size += len(tail)
                    if size > MAX_BODY_BYTES or not decoder.eof or decoder.unused_data:
                        raise _Rejected(
                            "Invalid or oversized decoded page body.", "unavailable", 200
                        )
                    chunks.append(tail)
                _remaining(deadline, self.monotonic)
                charset = response.charset_encoding or "utf-8"
                try:
                    text = b"".join(chunks).decode(charset, errors="replace")
                except LookupError:
                    text = b"".join(chunks).decode("utf-8", errors="replace")
                return response.status_code, headers, text

    def _robots(self, url, host, address, deadline):
        parsed = urlsplit(url)
        robots_url = urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
        for redirects in range(3):
            try:
                normalized, robots_host, robots_address = self._target(robots_url, deadline)
                # Keep same-origin robots pinned to the origin's validated address.
                if robots_host == host:
                    robots_address = address
                code, headers, text = self._get(normalized, robots_host, robots_address, deadline)
                if code in {301, 302, 303, 307, 308}:
                    if redirects == 2 or not headers.get("location"):
                        raise _Rejected("Robots policy redirect limit exceeded.")
                    robots_url = urljoin(normalized, headers["location"])
                    continue
                if (
                    code != 200
                    or not any(
                        line.strip().lower().startswith("user-agent:") for line in text.splitlines()
                    )
                    or "<html" in text.lower()
                ):
                    raise _Rejected("Robots policy could not be established.")
                policy = _RobotsPolicy(text, lambda: _remaining(deadline, self.monotonic))
                if not policy.can_fetch(USER_AGENT, url):
                    raise _Rejected("Source page disallowed by robots policy.")
                return policy
            except (
                httpx.HTTPError,
                httpcore.NetworkError,
                httpcore.TimeoutException,
                httpcore.ProtocolError,
                zlib.error,
            ):
                raise _Rejected("Robots policy could not be safely established.") from None

    def fetch(self, url: str) -> FetchResult:
        self.source_fetch_count += 1
        deadline = self.monotonic() + self.total_timeout
        candidate_url = url
        final_url = ""
        status_code = None
        robots_checked = {}
        try:
            for redirects in range(3):
                final_url, host, address = self._target(candidate_url, deadline)
                origin = urlsplit(final_url).netloc
                if origin not in robots_checked:
                    robots_checked[origin] = self._robots(final_url, host, address, deadline)
                # Policies may differ by path even within the same origin.
                elif redirects:
                    if not robots_checked[origin].can_fetch(USER_AGENT, final_url):
                        raise _Rejected("Source page disallowed by robots policy.")
                code, headers, text = self._get(final_url, host, address, deadline)
                status_code = code
                if code in {301, 302, 303, 307, 308}:
                    if redirects == 2 or not headers.get("location"):
                        raise _Rejected("Source page redirect limit exceeded.", status_code=code)
                    candidate_url = urljoin(final_url, headers["location"])
                    continue
                if code in {401, 403, 407, 429, 451}:
                    raise _Rejected("Source access blocked.", status_code=code)
                if code != 200:
                    raise _Rejected("Source page unavailable.", "unavailable", code)
                lowered = text.lower()
                indicators = (
                    "verify you are human",
                    "captcha",
                    "cf-chl-",
                    "just a moment...",
                    "sign in to continue",
                    "log in to continue",
                    "subscribe to continue reading",
                    "subscription required",
                )
                if any(indicator in lowered for indicator in indicators):
                    raise _Rejected(
                        "Source access challenge or restricted content.", status_code=code
                    )
                if not text.strip():
                    raise _Rejected("Source returned no usable content.", "unavailable", code)
                return FetchResult(final_url, text, code, "success", "", self.clock())
        except _Rejected as exc:
            return FetchResult(
                final_url, "", exc.status_code or status_code, exc.status, exc.reason, self.clock()
            )
        except (
            httpx.HTTPError,
            httpcore.NetworkError,
            httpcore.TimeoutException,
            httpcore.ProtocolError,
            zlib.error,
            OSError,
        ):
            return FetchResult(
                final_url,
                "",
                status_code,
                "unavailable",
                "Public HTTPS retrieval failed.",
                self.clock(),
            )
        return FetchResult(
            final_url, "", status_code, "unavailable", "Source page unavailable.", self.clock()
        )
