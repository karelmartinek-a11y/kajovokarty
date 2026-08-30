from __future__ import annotations

import random
import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from ...app.config import BETTER_HOTEL_BASE_URL

CancelCallback = Callable[[], bool]
TraceCallback = Callable[[dict[str, Any]], None]


class BetterHotelError(RuntimeError):
    pass


class BetterHotelAuthError(BetterHotelError):
    pass


class BetterHotelCancelled(BetterHotelError):
    pass


class CursorCycleError(BetterHotelError):
    pass


@dataclass(frozen=True, slots=True)
class Tokens:
    access_token: str
    client_token: str

    @property
    def complete(self) -> bool:
        return bool(self.access_token.strip() and self.client_token.strip())


@dataclass(frozen=True, slots=True)
class Page:
    data: list[dict[str, Any]]
    total_count: int
    cursor: str | None
    has_more: bool
    raw: dict[str, Any]


class TokenBucket:
    def __init__(self, rate_per_second: float = 2.0, capacity: int = 10) -> None:
        if not 0.2 <= rate_per_second <= 2.0:
            raise ValueError("Rate musí být 0,2 až 2 requesty za sekundu.")
        self.rate = rate_per_second
        self.capacity = capacity
        self.tokens = float(capacity)
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self, cancel: CancelCallback | None = None) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            _cooperative_sleep(min(wait, 0.25), cancel)


class BetterHotelClient:
    """Read-only Better Hotel client. The public API exposes GET operations only."""

    def __init__(
        self,
        tokens: Tokens,
        *,
        timeout_seconds: float = 30.0,
        retries: int = 3,
        requests_per_second: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        trace: TraceCallback | None = None,
    ) -> None:
        if not tokens.complete:
            raise BetterHotelAuthError("Access Token a Client Token nejsou vyplněné.")
        if not 5 <= timeout_seconds <= 120:
            raise ValueError("Timeout musí být 5 až 120 sekund.")
        if not 0 <= retries <= 5:
            raise ValueError("Počet retry musí být 0 až 5.")
        self._tokens = tokens
        self._retries = retries
        self._bucket = TokenBucket(requests_per_second, 10)
        self._trace = trace
        self._client = httpx.Client(
            base_url=BETTER_HOTEL_BASE_URL.rstrip("/") + "/",
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BetterHotelClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def base_url(self) -> str:
        return BETTER_HOTEL_BASE_URL

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        cancel: CancelCallback | None = None,
    ) -> dict[str, Any]:
        if not path.startswith("/"):
            path = "/" + path
        request_headers = {
            "X-Access-Token": self._tokens.access_token,
            "X-Client-Token": self._tokens.client_token,
        }
        if headers:
            request_headers.update(headers)
        retry_no = 0
        while True:
            if cancel is not None and cancel():
                raise BetterHotelCancelled("Synchronizace byla bezpečně zrušena.")
            self._bucket.acquire(cancel)
            started = time.monotonic()
            self._emit(
                event="api_request",
                method="GET",
                path=path,
                params=dict(params or {}),
                retry_no=retry_no,
            )
            try:
                response = self._client.get(path, params=params, headers=request_headers)
            except httpx.TimeoutException as exc:
                if retry_no >= self._retries:
                    raise BetterHotelError("Better Hotel neodpověděl v nastaveném čase.") from exc
                self._backoff(retry_no, cancel)
                retry_no += 1
                continue
            except httpx.HTTPError as exc:
                if retry_no >= self._retries:
                    raise BetterHotelError(f"Síťová chyba Better Hotel: {exc}") from exc
                self._backoff(retry_no, cancel)
                retry_no += 1
                continue
            duration_ms = int((time.monotonic() - started) * 1000)
            self._emit(event="api_response", path=path, status=response.status_code, duration_ms=duration_ms)
            if response.status_code == 429:
                if retry_no >= self._retries:
                    raise BetterHotelError("Better Hotel opakovaně omezuje počet požadavků.")
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                _cooperative_sleep(retry_after, cancel)
                retry_no += 1
                continue
            if response.status_code in {500, 502, 503, 504}:
                if retry_no >= self._retries:
                    raise BetterHotelError(f"Better Hotel vrátil HTTP {response.status_code}.")
                self._backoff(retry_no, cancel)
                retry_no += 1
                continue
            if response.status_code in {401, 403}:
                raise BetterHotelAuthError("Připojení se nezdařilo. Zkontrolujte Access Token a Client Token v Nastavení.")
            if response.status_code >= 400:
                raise BetterHotelError(f"Better Hotel vrátil HTTP {response.status_code}: {_safe_message(response)}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise BetterHotelError("Better Hotel vrátil neplatný JSON.") from exc
            if not isinstance(payload, dict):
                raise BetterHotelError("Better Hotel vrátil neočekávaný formát odpovědi.")
            return payload

    def pages(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        cancel: CancelCallback | None = None,
    ) -> Iterator[Page]:
        original = dict(params or {})
        original["count"] = 25
        cursor: str | None = None
        seen_cursors: set[str] = set()
        seen_ids: set[str] = set()
        while True:
            page_params = dict(original)
            if cursor:
                page_params["cursor"] = cursor
            raw = self.get(path, params=page_params, headers=headers, cancel=cancel)
            data_value = raw.get("data", [])
            if isinstance(data_value, dict):
                data = [data_value]
            elif isinstance(data_value, list):
                data = [item for item in data_value if isinstance(item, dict)]
            else:
                data = []
            unique: list[dict[str, Any]] = []
            duplicates = 0
            for item in data:
                external_id = str(item.get("id") or item.get("uuid") or "")
                if external_id and external_id in seen_ids:
                    duplicates += 1
                    continue
                if external_id:
                    seen_ids.add(external_id)
                unique.append(item)
            meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
            next_cursor = str(meta.get("cursor") or "").strip() or None
            has_more = bool(meta.get("has_more"))
            total_count = _safe_int(meta.get("total_count"), len(unique))
            self._emit(event="api_page", path=path, count=len(unique), duplicate_ids=duplicates, cursor=next_cursor)
            yield Page(unique, total_count, next_cursor, has_more, raw)
            if not has_more:
                return
            if next_cursor is None:
                raise CursorCycleError("API oznámilo další stránku bez cursoru.")
            if next_cursor in seen_cursors:
                raise CursorCycleError("API vrátilo opakovaný cursor; běh byl bezpečně ukončen.")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    def iter_items(self, path: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
        for page in self.pages(path, **kwargs):
            yield from page.data

    def _backoff(self, retry_no: int, cancel: CancelCallback | None) -> None:
        delay = min(8.0, (2**retry_no) * 0.5) + random.uniform(0.0, 0.2)
        _cooperative_sleep(delay, cancel)

    def _emit(self, **event: Any) -> None:
        if self._trace is not None:
            self._trace(event)


def _cooperative_sleep(seconds: float, cancel: CancelCallback | None) -> None:
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        if cancel is not None and cancel():
            raise BetterHotelCancelled("Synchronizace byla bezpečně zrušena.")
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))


def _retry_after_seconds(value: str | None) -> float:
    if value is None:
        return 1.0
    try:
        return min(60.0, max(0.1, float(value)))
    except ValueError:
        return 1.0


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_message(response: httpx.Response) -> str:
    text = response.text.replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return "bez detailu"
    patterns = (
        r"(?i)(x-access-token|x-client-token|access[_ -]?token|client[_ -]?token|authorization)\s*[:=]\s*[^,;\s\"}]+",
        r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+",
        r"\beyJ[A-Za-z0-9._-]{20,}\b",
        r"\bbh_[A-Za-z0-9._-]{20,}\b",
    )
    for pattern in patterns:
        text = re.sub(pattern, "[REDACTED]", text)
    return text[:300]
