"""원문 HTML에서 본문 텍스트와 메타데이터(제목, 날짜) 추출."""

import json
from dataclasses import dataclass

import trafilatura

# 이보다 짧으면 본문 추출에 실패했거나(목록·로그인 페이지 등) 포스트모템이 아닐 가능성이 높다.
MIN_TEXT_CHARS = 500


@dataclass
class Extracted:
    title: str | None
    date: str | None
    text: str

    @property
    def too_short(self) -> bool:
        return len(self.text) < MIN_TEXT_CHARS


def extract(html: bytes | str, url: str | None = None) -> Extracted | None:
    raw = trafilatura.extract(
        html,
        url=url,
        output_format="json",
        with_metadata=True,
        include_comments=False,
        include_tables=True,
    )
    if not raw:
        return None
    data = json.loads(raw)
    text = (data.get("text") or "").strip()
    if not text:
        return None
    return Extracted(title=data.get("title") or None, date=data.get("date") or None, text=text)
