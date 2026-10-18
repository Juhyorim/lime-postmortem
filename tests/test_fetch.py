import httpx
import pytest

from ingest.fetch import Fetcher

HTML = b"<html><body><p>hello</p></body></html>"


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, sec: float) -> None:
        self.sleeps.append(sec)
        self.now += sec


def make_fetcher(handler, robots: dict[str, httpx.Response] | None = None, **kw):
    """handler(request) → Response. robots: 호스트별 robots.txt 응답 (기본은 404 = 전체 허용)."""
    robots = robots or {}
    calls: list[str] = []

    def dispatch(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return robots.get(request.url.host, httpx.Response(404))
        return handler(request)

    clock = FakeClock()
    client = httpx.Client(transport=httpx.MockTransport(dispatch))
    fetcher = Fetcher(client, "postmortem-rag/0.1", delay_sec=3.0, clock=clock, sleep=clock.sleep, **kw)
    return fetcher, calls, clock


def html_ok(request):
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=HTML)


def test_fetch_ok():
    fetcher, _, _ = make_fetcher(html_ok)
    res = fetcher.fetch("https://a.example/post")
    assert res.ok
    assert res.body == HTML
    assert res.content_type == "text/html"


def test_user_agent_sent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return html_ok(request)

    fetcher, _, _ = make_fetcher(handler)
    fetcher.fetch("https://a.example/post")
    assert seen["ua"] == "postmortem-rag/0.1"


def test_robots_disallow_is_permanent_and_not_requested():
    robots = {"a.example": httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")}
    fetcher, calls, _ = make_fetcher(html_ok, robots)
    res = fetcher.fetch("https://a.example/private/post")
    assert not res.ok
    assert res.reason == "robots_disallowed"
    assert res.permanent
    assert "https://a.example/private/post" not in calls

    assert fetcher.fetch("https://a.example/public").ok


def test_robots_server_error_blocks_without_permanent_failure():
    robots = {"a.example": httpx.Response(503)}
    fetcher, calls, _ = make_fetcher(html_ok, robots)
    res = fetcher.fetch("https://a.example/post")
    assert not res.ok
    assert res.reason == "robots_unavailable:http_503"
    assert not res.permanent
    assert calls == ["https://a.example/robots.txt"]


def test_robots_fetched_once_per_host():
    fetcher, calls, _ = make_fetcher(html_ok)
    fetcher.fetch("https://a.example/1")
    fetcher.fetch("https://a.example/2")
    assert calls.count("https://a.example/robots.txt") == 1


def test_same_host_delay_and_crawl_delay():
    robots = {"b.example": httpx.Response(200, text="User-agent: *\nCrawl-delay: 10\n")}
    fetcher, _, clock = make_fetcher(html_ok, robots)
    fetcher.fetch("https://a.example/1")  # robots + 본문: 두 번째 요청 전에 3초
    fetcher.fetch("https://a.example/2")  # 3초
    assert clock.sleeps == [3.0, 3.0]

    clock.sleeps.clear()
    fetcher.fetch("https://b.example/1")  # robots 받기 전엔 기본 3초, 이후 Crawl-delay 10초
    fetcher.fetch("https://b.example/2")
    assert clock.sleeps == [10.0, 10.0]


def test_different_hosts_do_not_wait():
    fetcher, _, clock = make_fetcher(html_ok)
    fetcher.fetch("https://a.example/1")
    clock.sleeps.clear()
    clock.now += 100
    fetcher.fetch("https://a.example/2")
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "status,reason,permanent",
    [(404, "http_404", True), (410, "http_410", True), (403, "http_403", True),
     (429, "http_429", False), (503, "http_503", False)],
)
def test_http_errors(status, reason, permanent):
    fetcher, _, _ = make_fetcher(lambda r: httpx.Response(status))
    res = fetcher.fetch("https://a.example/post")
    assert not res.ok
    assert res.reason == reason
    assert res.permanent is permanent
    assert res.status_code == status


def test_timeout_is_transient():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    fetcher, _, _ = make_fetcher(handler)
    res = fetcher.fetch("https://a.example/post")
    assert res.reason == "timeout"
    assert not res.permanent


def test_connection_error_is_transient():
    def handler(request):
        raise httpx.ConnectError("dns", request=request)

    fetcher, _, _ = make_fetcher(handler)
    res = fetcher.fetch("https://a.example/post")
    assert res.reason == "connection_error:ConnectError"
    assert not res.permanent


def test_pdf_rejected():
    fetcher, _, _ = make_fetcher(
        lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")
    )
    res = fetcher.fetch("https://a.example/report.pdf")
    assert res.reason == "unsupported_content_type"
    assert res.permanent


def test_accept_types_override():
    fetcher, _, _ = make_fetcher(
        lambda r: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"# README")
    )
    assert not fetcher.fetch("https://a.example/README.md").ok
    assert fetcher.fetch("https://a.example/README.md", accept_types=("text/plain",)).ok


def test_too_large_by_streaming():
    fetcher, _, _ = make_fetcher(
        lambda r: httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>" + b"x" * 200),
        max_bytes=100,
    )
    res = fetcher.fetch("https://a.example/big")
    assert res.reason == "too_large"
    assert res.permanent


def test_redirect_to_other_host_checks_its_robots():
    robots = {"b.example": httpx.Response(200, text="User-agent: *\nDisallow: /\n")}

    def handler(request):
        if request.url.host == "a.example":
            return httpx.Response(301, headers={"location": "https://b.example/moved"})
        return html_ok(request)

    fetcher, calls, _ = make_fetcher(handler, robots)
    res = fetcher.fetch("https://a.example/post")
    assert res.reason == "robots_disallowed"
    assert res.final_url == "https://b.example/moved"
    assert "https://b.example/moved" not in calls


def test_relative_redirect_followed():
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(302, headers={"location": "/new"})
        return html_ok(request)

    fetcher, _, _ = make_fetcher(handler)
    res = fetcher.fetch("https://a.example/old")
    assert res.ok
    assert res.final_url == "https://a.example/new"
    assert res.url == "https://a.example/old"


def test_redirect_loop_stops():
    fetcher, _, _ = make_fetcher(lambda r: httpx.Response(302, headers={"location": "/loop"}), max_redirects=3)
    res = fetcher.fetch("https://a.example/loop")
    assert res.reason == "too_many_redirects"
    assert res.permanent


def test_meta_refresh_followed():
    def handler(request):
        if request.url.path == "/old.html":
            body = b'<html><head><meta http-equiv="refresh" content="0; url=/new/"></head></html>'
            return httpx.Response(200, headers={"content-type": "text/html"}, content=body)
        return html_ok(request)

    fetcher, _, _ = make_fetcher(handler)
    res = fetcher.fetch("https://a.example/old.html")
    assert res.ok
    assert res.final_url == "https://a.example/new/"
    assert res.body == HTML


def test_meta_refresh_ignored_on_large_page():
    body = b'<meta http-equiv="refresh" content="300;url=/other">' + b"<p>article</p>" * 2000
    fetcher, calls, _ = make_fetcher(
        lambda r: httpx.Response(200, headers={"content-type": "text/html"}, content=body)
    )
    res = fetcher.fetch("https://a.example/live")
    assert res.ok
    assert "https://a.example/other" not in calls
