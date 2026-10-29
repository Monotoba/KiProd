from __future__ import annotations

import hashlib
import ipaddress
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class HttpError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    from_cache: bool = False

    def json(self) -> Any:
        return json.loads(self.body)


class _SameOriginRedirectHandler(HTTPRedirectHandler):
    """Prevent redirects from forwarding credentials or requests across origins."""

    def redirect_request(
        self,
        request: Request,
        fp: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Request | None:
        original = urlsplit(request.full_url)
        target = urlsplit(new_url)
        original_origin = (original.scheme, original.hostname, original.port)
        target_origin = (target.scheme, target.hostname, target.port)
        if target_origin != original_origin:
            raise HTTPError(new_url, code, "cross-origin redirect is not permitted", headers, fp)
        return super().redirect_request(request, fp, code, message, headers, new_url)


class HttpClient:
    """Small allowlisted HTTP client with deterministic fixture replay and cache."""

    def __init__(
        self,
        allowed_hosts: set[str],
        *,
        fixtures: dict[tuple[str, str], HttpResponse] | None = None,
        timeout: float = 10.0,
        retries: int = 2,
        rate_limit_seconds: float = 0.0,
        allow_local_http: bool = False,
    ) -> None:
        self.allowed_hosts = {host.lower() for host in allowed_hosts}
        self.fixtures = fixtures or {}
        self.timeout = timeout
        self.retries = max(0, retries)
        self.rate_limit_seconds = max(0.0, rate_limit_seconds)
        self.allow_local_http = allow_local_http
        self._cache: dict[str, HttpResponse] = {}
        self._last_request: dict[str, float] = {}

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> HttpResponse:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        local_http = (
            self.allow_local_http
            and parsed.scheme == "http"
            and host in self.allowed_hosts
            and _is_loopback(host)
        )
        if host not in self.allowed_hosts or (parsed.scheme != "https" and not local_http):
            raise HttpError(f"URL is not permitted: {url}")
        verb = method.upper()
        if verb not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}:
            raise HttpError(f"unsupported HTTP method: {verb}")
        fingerprint = hashlib.sha256(
            b"\0".join((verb.encode(), url.encode(), body or b""))
        ).hexdigest()
        if verb == "GET" and fingerprint in self._cache:
            cached = self._cache[fingerprint]
            return HttpResponse(cached.status, cached.headers, cached.body, from_cache=True)
        fixture = self.fixtures.get((verb, url))
        if fixture is not None:
            if verb == "GET":
                self._cache[fingerprint] = fixture
            return fixture
        request = Request(url, data=body, headers=headers or {}, method=verb)
        for attempt in range(self.retries + 1):
            self._throttle(host)
            try:
                opener = build_opener(_SameOriginRedirectHandler())
                with opener.open(request, timeout=self.timeout) as response:
                    result = HttpResponse(
                        response.status,
                        dict(response.headers.items()),
                        response.read(),
                    )
                if verb == "GET":
                    self._cache[fingerprint] = result
                return result
            except HTTPError as exc:
                if exc.code < 500 or attempt == self.retries:
                    raise HttpError(f"HTTP {exc.code} from {host}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt == self.retries:
                    raise HttpError(f"request to {host} failed: {exc}") from exc
            time.sleep(min(0.25 * (2**attempt), 2.0))
        raise HttpError(f"request to {host} failed")

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> HttpResponse:
        return self.request("GET", url, headers=headers)

    def post(self, url: str, body: bytes, *, headers: dict[str, str] | None = None) -> HttpResponse:
        return self.request("POST", url, headers=headers, body=body)

    def _throttle(self, host: str) -> None:
        previous = self._last_request.get(host)
        now = time.monotonic()
        if previous is not None:
            delay = self.rate_limit_seconds - (now - previous)
            if delay > 0:
                time.sleep(delay)
        self._last_request[host] = time.monotonic()


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
