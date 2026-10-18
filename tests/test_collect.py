import gzip
import json

import httpx

from ingest.collect import RawPaths, collect
from ingest.extract import MIN_TEXT_CHARS, extract
from ingest.fetch import Fetcher
from ingest.sources import SourceEntry
from ingest.state import CrawlState, doc_id_for

PARAGRAPH = (
    "At 09:12 UTC a configuration change was deployed to the edge fleet. The new rule matched "
    "every request and caused the router process to exhaust memory and crash, returning HTTP 503 "
    "to all customers. "
)
ARTICLE = f"""<html><head><title>Outage post-mortem</title></head><body>
<nav>Home | Blog | Careers</nav>
<article><h1>Outage post-mortem</h1>
<p>{PARAGRAPH * 2}</p><h2>Timeline</h2><p>{PARAGRAPH * 2}</p><h2>Remediation</h2><p>{PARAGRAPH}</p>
</article><footer>Copyright</footer></body></html>""".encode()


def entry(url: str, secondary: bool = False) -> SourceEntry:
    return SourceEntry(url=url, company="Acme", category="Config Errors", description="desc", is_secondary=secondary)


class Server:
    """URL 경로별 응답을 정해두고 요청 기록을 남기는 가짜 서버."""

    def __init__(self, routes):
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        self.calls.append(str(request.url))
        route = self.routes.get(request.url.path)
        if route is None:
            return httpx.Response(404)
        if isinstance(route, Exception):
            raise route
        return route


def setup(tmp_path, routes):
    server = Server(routes)
    client = httpx.Client(transport=httpx.MockTransport(server))
    fetcher = Fetcher(client, "postmortem-rag/0.1", delay_sec=0, sleep=lambda s: None)
    paths = RawPaths(tmp_path / "raw")
    state = CrawlState(paths.db)
    return server, fetcher, paths, state


def html(body: bytes = ARTICLE) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/html"}, content=body)


def test_success_saves_raw_and_text(tmp_path):
    server, fetcher, paths, state = setup(tmp_path, {"/post": html()})
    url = "https://a.example/post"
    state.upsert_entries([entry(url)])

    assert collect(fetcher, state, paths, None, False) == {"ok": 1, "failed": 0}

    doc_id = doc_id_for(url)
    assert gzip.decompress(paths.html_file(doc_id).read_bytes()) == ARTICLE
    doc = json.loads(paths.text_file(doc_id).read_text())
    assert doc["title"] == "Outage post-mortem"
    assert doc["company"] == "Acme"
    assert "HTTP 503" in doc["text"]
    assert "Careers" not in doc["text"]  # 내비게이션은 빠짐
    assert doc["extract_status"] == "ok"

    row = state.conn.execute("SELECT * FROM fetches").fetchone()
    assert row["status"] == "ok"
    assert row["attempts"] == 1
    assert row["fetched_at"]
    assert row["text_chars"] == len(doc["text"])


def test_already_fetched_is_not_requested_again(tmp_path):
    server, fetcher, paths, state = setup(tmp_path, {"/post": html()})
    state.upsert_entries([entry("https://a.example/post")])
    collect(fetcher, state, paths, None, False)
    server.calls.clear()

    # 다음 날 README에 같은 URL이 또 있어도 다시 받지 않는다
    assert state.upsert_entries([entry("https://a.example/post")]) == 0
    assert collect(fetcher, state, paths, None, False) == {"ok": 0, "failed": 0}
    assert server.calls == []


def test_permanent_failure_not_retried(tmp_path):
    server, fetcher, paths, state = setup(tmp_path, {})
    state.upsert_entries([entry("https://a.example/gone")])
    collect(fetcher, state, paths, None, False)

    row = state.conn.execute("SELECT * FROM fetches").fetchone()
    assert (row["status"], row["reason"], row["permanent"], row["http_status"]) == ("failed", "http_404", 1, 404)

    server.calls.clear()
    collect(fetcher, state, paths, None, False)
    assert server.calls == []


def test_transient_failure_retried_up_to_limit(tmp_path):
    server, fetcher, paths, state = setup(tmp_path, {"/flaky": httpx.Response(503)})
    state.upsert_entries([entry("https://a.example/flaky")])
    for _ in range(5):
        collect(fetcher, state, paths, None, False)
    assert len(server.calls) == 3
    row = state.conn.execute("SELECT * FROM fetches").fetchone()
    assert (row["attempts"], row["reason"], row["permanent"]) == (3, "http_503", 0)


def test_transient_then_success(tmp_path):
    server, fetcher, paths, state = setup(tmp_path, {"/post": httpx.Response(503)})
    state.upsert_entries([entry("https://a.example/post")])
    collect(fetcher, state, paths, None, False)
    server.routes["/post"] = html()
    collect(fetcher, state, paths, None, False)
    row = state.conn.execute("SELECT * FROM fetches").fetchone()
    assert (row["status"], row["reason"], row["attempts"]) == ("ok", None, 2)


def test_limit_and_secondary_excluded(tmp_path):
    routes = {f"/p{i}": html() for i in range(5)}
    server, fetcher, paths, state = setup(tmp_path, routes)
    state.upsert_entries([entry(f"https://a.example/p{i}") for i in range(4)] + [entry("https://a.example/p4", True)])

    assert collect(fetcher, state, paths, 2, False)["ok"] == 2
    assert collect(fetcher, state, paths, None, False)["ok"] == 2
    assert "https://a.example/p4" not in server.calls
    assert collect(fetcher, state, paths, None, True)["ok"] == 1


def test_wayback_fetches_raw_snapshot(tmp_path):
    seen = []

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        seen.append(str(request.url))
        return html()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = Fetcher(client, "ua", delay_sec=0, sleep=lambda s: None)
    paths = RawPaths(tmp_path / "raw")
    state = CrawlState(paths.db)
    url = "https://web.archive.org/web/20211006135542/https://blog.example/outage/"
    state.upsert_entries([entry(url)])
    collect(fetcher, state, paths, None, False)

    assert seen == ["https://web.archive.org/web/20211006135542id_/https://blog.example/outage/"]
    doc = json.loads(paths.text_file(doc_id_for(url)).read_text())
    assert doc["url"] == url  # 상태와 파일은 README의 원래 URL 기준
    assert doc["original_url"] == "https://blog.example/outage/"


def test_short_text_marked(tmp_path):
    short = b"<html><body><article><p>Our status page.</p></article></body></html>"
    server, fetcher, paths, state = setup(tmp_path, {"/s": html(short)})
    state.upsert_entries([entry("https://a.example/s")])
    collect(fetcher, state, paths, None, False)
    row = state.conn.execute("SELECT * FROM fetches").fetchone()
    assert row["status"] == "ok"
    assert row["extract_status"] in ("too_short", "failed")


def test_report_success_rate(tmp_path):
    server, fetcher, paths, state = setup(tmp_path, {"/ok": html()})
    state.upsert_entries([entry("https://a.example/ok"), entry("https://a.example/missing")])
    collect(fetcher, state, paths, None, False)
    r = state.report()
    assert r["success_rate"] == 0.5
    assert r["fail_reasons"][0]["reason"] == "http_404"
    assert r["fail_hosts"][0]["host"] == "a.example"


def test_extract_length_threshold():
    doc = extract(ARTICLE, url="https://a.example/post")
    assert doc is not None
    assert len(doc.text) >= MIN_TEXT_CHARS
    assert not doc.too_short
