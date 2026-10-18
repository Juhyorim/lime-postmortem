"""수집 상태 기록 (data/raw/crawl.db).

URL마다 한 행: 받았는지, 언제, 실패 사유, 시도 횟수, 본문 추출 결과.
원문·텍스트 파일 이름은 doc_id(정규화 URL의 sha1)로 정해지므로 경로는 따로 저장하지 않는다.
"""

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ingest.fetch import FetchResult
from ingest.sources import SourceEntry

SCHEMA = """
CREATE TABLE IF NOT EXISTS fetches (
    url           TEXT PRIMARY KEY,
    doc_id        TEXT NOT NULL,
    company       TEXT,
    category      TEXT,
    description   TEXT,
    is_secondary  INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'pending',   -- pending / ok / failed
    reason        TEXT,
    permanent     INTEGER NOT NULL DEFAULT 0,        -- 1이면 재시도하지 않는 실패
    http_status   INTEGER,
    final_url     TEXT,
    content_type  TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    first_seen    TEXT NOT NULL,
    fetched_at    TEXT,
    sha256        TEXT,
    extract_status TEXT,                             -- ok / too_short / failed
    text_chars    INTEGER
);
"""


def doc_id_for(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CrawlState:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def upsert_entries(self, entries: list[SourceEntry]) -> int:
        """출처 목록을 반영한다. 새 URL 수를 돌려준다. 기존 행의 수집 상태는 건드리지 않는다."""
        before = self.conn.execute("SELECT COUNT(*) FROM fetches").fetchone()[0]
        now = _now()
        self.conn.executemany(
            """
            INSERT INTO fetches (url, doc_id, company, category, description, is_secondary, first_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                company = excluded.company,
                category = excluded.category,
                description = excluded.description,
                is_secondary = excluded.is_secondary
            """,
            [
                (e.url, doc_id_for(e.url), e.company, e.category, e.description, int(e.is_secondary), now)
                for e in entries
            ],
        )
        self.conn.commit()
        after = self.conn.execute("SELECT COUNT(*) FROM fetches").fetchone()[0]
        return after - before

    def due(self, max_attempts: int, include_secondary: bool = False, limit: int | None = None) -> list[sqlite3.Row]:
        """받아야 할 URL: 처음 보는 것 + 재시도 가능한 일시 실패(시도 횟수 상한 이내)."""
        sql = """
            SELECT * FROM fetches
            WHERE (status = 'pending'
                   OR (status = 'failed' AND permanent = 0 AND attempts < ?))
        """
        params: list = [max_attempts]
        if not include_secondary:
            sql += " AND is_secondary = 0"
        sql += " ORDER BY attempts, first_seen, rowid"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return self.conn.execute(sql, params).fetchall()

    def fetched(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM fetches WHERE status = 'ok' ORDER BY rowid").fetchall()

    def record_success(self, url: str, result: FetchResult, sha256: str) -> None:
        self.conn.execute(
            """
            UPDATE fetches SET status = 'ok', reason = NULL, permanent = 0,
                http_status = ?, final_url = ?, content_type = ?,
                attempts = attempts + 1, fetched_at = ?, sha256 = ?
            WHERE url = ?
            """,
            (result.status_code, result.final_url, result.content_type, _now(), sha256, url),
        )
        self.conn.commit()

    def record_failure(self, url: str, result: FetchResult) -> None:
        self.conn.execute(
            """
            UPDATE fetches SET status = 'failed', reason = ?, permanent = ?,
                http_status = ?, final_url = ?, content_type = ?,
                attempts = attempts + 1, fetched_at = ?
            WHERE url = ?
            """,
            (result.reason, int(result.permanent), result.status_code, result.final_url,
             result.content_type, _now(), url),
        )
        self.conn.commit()

    def record_extract(self, url: str, status: str, text_chars: int | None) -> None:
        self.conn.execute(
            "UPDATE fetches SET extract_status = ?, text_chars = ? WHERE url = ?",
            (status, text_chars, url),
        )
        self.conn.commit()

    def report(self, max_attempts: int) -> dict:
        q = self.conn.execute
        total = q("SELECT COUNT(*) FROM fetches WHERE is_secondary = 0").fetchone()[0]
        by_status = dict(q("SELECT status, COUNT(*) FROM fetches WHERE is_secondary = 0 GROUP BY status").fetchall())
        attempted = by_status.get("ok", 0) + by_status.get("failed", 0)
        return {
            "primary_total": total,
            "by_status": by_status,
            "success_rate": (by_status.get("ok", 0) / attempted) if attempted else None,
            "extract": dict(q(
                "SELECT COALESCE(extract_status, '-'), COUNT(*) FROM fetches WHERE status = 'ok' GROUP BY 1"
            ).fetchall()),
            # will_retry: 다음 실행에서 실제로 다시 요청하는지 (일시 실패라도 시도 횟수를 다 쓰면 0)
            "fail_reasons": q(
                "SELECT reason, (permanent = 0 AND attempts < ?) AS will_retry, COUNT(*) AS n "
                "FROM fetches WHERE status = 'failed' GROUP BY reason, will_retry ORDER BY n DESC",
                (max_attempts,),
            ).fetchall(),
            "fail_hosts": q(
                "SELECT substr(url, instr(url, '://') + 3, instr(substr(url, instr(url, '://') + 3), '/') - 1) AS host, "
                "COUNT(*) AS n FROM fetches WHERE status = 'failed' GROUP BY host ORDER BY n DESC LIMIT 10"
            ).fetchall(),
        }
