"""수집 배치 진입점.

    python -m ingest.collect               # README 갱신 → 받을 차례인 URL 전부 수집·추출
    python -m ingest.collect --limit 50    # 이번 실행에서 최대 50개만
    python -m ingest.collect --dry-run     # README 파싱 결과만 확인 (원문 요청 없음)
    python -m ingest.collect --extract-only  # 네트워크 없이 data/raw/html에서 다시 추출
    python -m ingest.collect --report      # 수집 현황

cron에서는 scripts/run_collect.sh 로 실행한다.
"""

import argparse
import fcntl
import gzip
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.config import load_settings
from ingest.extract import extract
from ingest.fetch import FetchResult, Fetcher, build_user_agent
from ingest.sources import README_URL, original_url, parse_readme, wayback_raw_url
from ingest.state import CrawlState

log = logging.getLogger("ingest.collect")

MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class RawPaths:
    root: Path

    @property
    def html(self) -> Path:
        return self.root / "html"

    @property
    def text(self) -> Path:
        return self.root / "text"

    @property
    def sources(self) -> Path:
        return self.root / "sources"

    @property
    def db(self) -> Path:
        return self.root / "crawl.db"

    def html_file(self, doc_id: str) -> Path:
        return self.html / f"{doc_id}.html.gz"

    def text_file(self, doc_id: str) -> Path:
        return self.text / f"{doc_id}.json"


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def load_readme(fetcher: Fetcher, paths: RawPaths, local: Path | None) -> str:
    """README를 받아 날짜별 스냅샷으로 남긴다. 같은 날 이미 받았으면 다시 요청하지 않는다."""
    if local:
        return local.read_text(encoding="utf-8")
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    snapshot = paths.sources / f"danluu-{today}.md"
    if snapshot.exists():
        return snapshot.read_text(encoding="utf-8")
    res = fetcher.fetch(README_URL, accept_types=("text/plain", "text/markdown"))
    if not res.ok:
        # 목록을 못 받아도 이전 스냅샷이 있으면 그걸로 진행한다
        previous = sorted(paths.sources.glob("danluu-*.md"))
        if previous:
            log.warning("README 수집 실패(%s), 이전 스냅샷 사용: %s", res.reason, previous[-1].name)
            return previous[-1].read_text(encoding="utf-8")
        raise RuntimeError(f"README 수집 실패: {res.reason}")
    _write_atomic(snapshot, res.body)
    return res.body.decode("utf-8")


def extract_one(row, paths: RawPaths, state: CrawlState) -> str:
    html = gzip.decompress(paths.html_file(row["doc_id"]).read_bytes())
    try:
        doc = extract(html, url=original_url(row["url"]))
    except Exception:
        log.exception("추출 오류: %s", row["url"])
        doc = None
    if doc is None:
        state.record_extract(row["url"], "failed", None)
        return "failed"

    status = "too_short" if doc.too_short else "ok"
    record = {
        "doc_id": row["doc_id"],
        "url": row["url"],
        "original_url": original_url(row["url"]),
        "final_url": row["final_url"],
        "company": row["company"],
        "category": row["category"],
        "description": row["description"],
        "title": doc.title,
        "date": doc.date,
        "fetched_at": row["fetched_at"],
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "extract_status": status,
        "text": doc.text,
    }
    _write_atomic(paths.text_file(row["doc_id"]), json.dumps(record, ensure_ascii=False, indent=1).encode())
    state.record_extract(row["url"], status, len(doc.text))
    return status


def collect(fetcher: Fetcher, state: CrawlState, paths: RawPaths, limit: int | None, include_secondary: bool) -> dict:
    rows = state.due(MAX_ATTEMPTS, include_secondary=include_secondary, limit=limit)
    log.info("이번 실행 대상: %d개", len(rows))
    counts = {"ok": 0, "failed": 0}
    for i, row in enumerate(rows, 1):
        url = row["url"]
        try:
            result = fetcher.fetch(wayback_raw_url(url))
        except Exception as e:  # 잘못된 URL 등 예상 못 한 오류도 실패로 기록하고 계속
            log.exception("수집 오류: %s", url)
            result = FetchResult(url, ok=False, reason=f"error:{type(e).__name__}", permanent=True)

        if result.ok:
            _write_atomic(paths.html_file(row["doc_id"]), gzip.compress(result.body))
            state.record_success(url, result, hashlib.sha256(result.body).hexdigest())
            row = state.conn.execute("SELECT * FROM fetches WHERE url = ?", (url,)).fetchone()
            extract_status = extract_one(row, paths, state)
            counts["ok"] += 1
            log.info("[%d/%d] ok (%s) %s", i, len(rows), extract_status, url)
        else:
            state.record_failure(url, result)
            counts["failed"] += 1
            will_retry = not result.permanent and row["attempts"] + 1 < MAX_ATTEMPTS
            log.info("[%d/%d] 실패 %s%s %s", i, len(rows), result.reason,
                     " (재시도 예정)" if will_retry else "", url)
    return counts


def print_report(state: CrawlState) -> None:
    r = state.report(MAX_ATTEMPTS)
    rate = f"{r['success_rate']:.0%}" if r["success_rate"] is not None else "-"
    print(f"주 링크 {r['primary_total']}개  상태별 {r['by_status']}  수집 성공률 {rate}")
    print(f"본문 추출: {r['extract']}")
    if r["fail_reasons"]:
        print("실패 사유:")
        for row in r["fail_reasons"]:
            print(f"  {row['n']:4d}  {row['reason']}{' (재시도 예정)' if row['will_retry'] else ''}")
        print("실패 많은 호스트:")
        for row in r["fail_hosts"]:
            print(f"  {row['n']:4d}  {row['host']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="포스트모템 원문 수집")
    parser.add_argument("--limit", type=int, help="이번 실행에서 수집할 최대 URL 수")
    parser.add_argument("--dry-run", action="store_true", help="README 파싱 결과만 출력")
    parser.add_argument("--extract-only", action="store_true", help="저장된 원문에서 다시 추출")
    parser.add_argument("--report", action="store_true", help="수집 현황 출력")
    parser.add_argument("--include-secondary", action="store_true",
                        help="설명 안의 보조 링크도 수집 (회사 홈페이지 등이 섞여 있어 기본은 제외)")
    parser.add_argument("--readme", type=Path, help="README를 받지 않고 이 파일을 사용")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청마다 찍히는 로그 끔
    settings = load_settings()
    paths = RawPaths(settings.data_dir / "raw")
    paths.root.mkdir(parents=True, exist_ok=True)

    # cron 실행이 겹치지 않게
    lock = open(paths.root / ".collect.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.error("다른 수집 프로세스가 실행 중입니다")
        return 1

    state = CrawlState(paths.db)
    try:
        if args.report:
            print_report(state)
            return 0
        if args.extract_only:
            counts: dict[str, int] = {}
            for row in state.fetched():
                status = extract_one(row, paths, state)
                counts[status] = counts.get(status, 0) + 1
            log.info("재추출 결과: %s", counts)
            return 0

        user_agent = build_user_agent(settings.crawl_contact)
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            fetcher = Fetcher(client, user_agent, delay_sec=settings.crawl_delay_sec)
            entries = parse_readme(load_readme(fetcher, paths, args.readme))
            primary = sum(not e.is_secondary for e in entries)
            log.info("README 항목: 주 링크 %d개, 보조 링크 %d개", primary, len(entries) - primary)
            if args.dry_run:
                for e in entries:
                    if not e.is_secondary:
                        print(f"{e.category}\t{e.company}\t{e.url}")
                return 0
            new = state.upsert_entries(entries)
            log.info("새 URL %d개", new)
            counts = collect(fetcher, state, paths, args.limit, args.include_secondary)
        log.info("완료: %s", counts)
        print_report(state)
        return 0
    finally:
        state.close()


if __name__ == "__main__":
    sys.exit(main())
