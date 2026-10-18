"""예의 바른 HTTP 수집: robots.txt 준수, 호스트별 요청 간격, 크기·리다이렉트 제한.

리다이렉트는 직접 따라가면서 홉마다 robots.txt를 다시 확인한다 (다른 호스트로 넘어갈 수 있으므로).
"""

import logging
import re
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)

UA_TOKEN = "postmortem-rag"
HTML_TYPES = ("text/html", "application/xhtml+xml")

# 본문 없이 <meta http-equiv="refresh">로 이동만 시키는 페이지 (정적 블로그 이전 등)
META_REFRESH_RE = re.compile(
    rb"""<meta[^>]+http-equiv=["']?refresh["']?[^>]*content=["']?\s*\d+\s*;\s*url=([^"'>\s]+)""",
    re.IGNORECASE,
)
META_REFRESH_MAX_BYTES = 16 * 1024

# 호스트별 최소 간격(초). archive.org는 분당 요청 수 제한이 엄격하다.
HOST_MIN_DELAY = {"web.archive.org": 5.0}


def build_user_agent(contact: str) -> str:
    return f"{UA_TOKEN}/0.1 (+{contact})" if contact else f"{UA_TOKEN}/0.1"


@dataclass
class FetchResult:
    url: str
    ok: bool
    final_url: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    body: bytes = b""
    reason: str | None = None
    # True면 다시 시도해도 결과가 같을 실패 (404, robots 거부 등)
    permanent: bool = False


class _Robots:
    """robots.txt 판정 결과. rp가 None이면 허용 여부를 알 수 없음(서버 오류 등)."""

    def __init__(self, rp: RobotFileParser | None, reason: str | None = None):
        self.rp = rp
        self.reason = reason


class Fetcher:
    def __init__(
        self,
        client: httpx.Client,
        user_agent: str,
        delay_sec: float = 3.0,
        max_bytes: int = 5 * 1024 * 1024,
        max_redirects: int = 5,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.client = client
        self.user_agent = user_agent
        self.delay_sec = delay_sec
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.clock = clock
        self.sleep = sleep
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, _Robots] = {}

    # --- 간격 조절 -------------------------------------------------------

    def _host_delay(self, host: str) -> float:
        delay = max(self.delay_sec, HOST_MIN_DELAY.get(host, 0.0))
        robots = self._robots.get(host)
        if robots and robots.rp:
            crawl_delay = robots.rp.crawl_delay(UA_TOKEN)
            if crawl_delay:
                delay = max(delay, float(crawl_delay))
        return delay

    def _throttle(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            wait = self._host_delay(host) - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self._last_request[host] = self.clock()

    # --- robots.txt -----------------------------------------------------

    def _get_robots(self, url: str) -> _Robots:
        parts = urlsplit(url)
        host = parts.netloc
        if host in self._robots:
            return self._robots[host]

        robots_url = f"{parts.scheme}://{host}/robots.txt"
        self._throttle(host)
        try:
            res = self.client.get(
                robots_url, headers={"User-Agent": self.user_agent}, follow_redirects=True
            )
        except httpx.HTTPError as e:
            robots = _Robots(None, f"robots_unavailable:{type(e).__name__}")
        else:
            rp = RobotFileParser(robots_url)
            if res.status_code >= 500:
                robots = _Robots(None, f"robots_unavailable:http_{res.status_code}")
            elif res.status_code >= 400:
                # RFC 9309: robots.txt가 없으면(4xx) 전체 허용
                rp.allow_all = True
                robots = _Robots(rp)
            else:
                rp.parse(res.text.splitlines())
                rp.modified()  # 안 하면 can_fetch가 항상 False
                robots = _Robots(rp)
        self._robots[host] = robots
        return robots

    # --- 수집 -----------------------------------------------------------

    def fetch(self, url: str, accept_types: tuple[str, ...] = HTML_TYPES) -> FetchResult:
        current = url
        for _ in range(self.max_redirects + 1):
            robots = self._get_robots(current)
            if robots.rp is None:
                return FetchResult(url, ok=False, reason=robots.reason)
            if not robots.rp.can_fetch(UA_TOKEN, current):
                return FetchResult(url, ok=False, final_url=current, reason="robots_disallowed", permanent=True)

            result, location = self._get_once(url, current, accept_types)
            if location is None:
                return result
            current = location
        return FetchResult(url, ok=False, final_url=current, reason="too_many_redirects", permanent=True)

    def _get_once(self, url: str, current: str, accept_types: tuple[str, ...]) -> tuple[FetchResult, str | None]:
        """한 번 요청한다. 리다이렉트면 (_, 다음 주소)를 돌려준다."""
        self._throttle(urlsplit(current).netloc)
        try:
            with self.client.stream(
                "GET", current, headers={"User-Agent": self.user_agent}, follow_redirects=False
            ) as res:
                if res.is_redirect:
                    location = res.headers.get("location")
                    if not location:
                        return self._fail(url, current, res, "redirect_without_location", True), None
                    nxt = urljoin(current, location)
                    if urlsplit(nxt).scheme not in ("http", "https"):
                        return self._fail(url, current, res, "bad_redirect", True), None
                    return FetchResult(url, ok=False), nxt

                if res.status_code >= 400:
                    code = res.status_code
                    transient = code >= 500 or code in (408, 429)
                    return self._fail(url, current, res, f"http_{code}", not transient), None

                ctype = res.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype and ctype not in accept_types:
                    return self._fail(url, current, res, "unsupported_content_type", True), None

                length = res.headers.get("content-length")
                if length and length.isdigit() and int(length) > self.max_bytes:
                    return self._fail(url, current, res, "too_large", True), None

                chunks, size = [], 0
                for chunk in res.iter_bytes():
                    size += len(chunk)
                    if size > self.max_bytes:
                        return self._fail(url, current, res, "too_large", True), None
                    chunks.append(chunk)
                body = b"".join(chunks)

                if not ctype and accept_types == HTML_TYPES and body.lstrip()[:1] != b"<":
                    return self._fail(url, current, res, "unsupported_content_type", True), None

                refresh = _meta_refresh_target(body, current)
                if refresh:
                    return FetchResult(url, ok=False), refresh

                return (
                    FetchResult(
                        url,
                        ok=True,
                        final_url=current,
                        status_code=res.status_code,
                        content_type=ctype or None,
                        body=body,
                    ),
                    None,
                )
        except httpx.TimeoutException:
            return FetchResult(url, ok=False, final_url=current, reason="timeout"), None
        except httpx.TooManyRedirects:
            return FetchResult(url, ok=False, final_url=current, reason="too_many_redirects", permanent=True), None
        except httpx.HTTPError as e:
            return FetchResult(url, ok=False, final_url=current, reason=f"connection_error:{type(e).__name__}"), None

    @staticmethod
    def _fail(url: str, current: str, res: httpx.Response, reason: str, permanent: bool) -> FetchResult:
        return FetchResult(
            url,
            ok=False,
            final_url=current,
            status_code=res.status_code,
            content_type=res.headers.get("content-type"),
            reason=reason,
            permanent=permanent,
        )


def _meta_refresh_target(body: bytes, current: str) -> str | None:
    """작은 페이지가 meta refresh로 다른 주소를 가리키면 그 주소. 큰 페이지(본문 있음)는 무시한다."""
    if len(body) > META_REFRESH_MAX_BYTES:
        return None
    m = META_REFRESH_RE.search(body)
    if not m:
        return None
    target = urljoin(current, m.group(1).decode("utf-8", "replace"))
    if urlsplit(target).scheme not in ("http", "https") or target == current:
        return None
    return target
