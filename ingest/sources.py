"""출처 목록 파싱: danluu/post-mortems README의 링크 목록.

항목 형식: 한 문단에 하나씩 `[회사](URL). 설명...`
첫 링크가 포스트모템 본문이고, 설명 안의 링크(회사 홈페이지, "See also" 등)는 보조 링크로 따로 표시한다.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

README_URL = "https://raw.githubusercontent.com/danluu/post-mortems/master/README.md"

# 포스트모템 목록이 아닌 섹션
EXCLUDED_SECTIONS = {
    "table of contents",
    "other lists of postmortems",
    "analysis",
    "contributors",
}

# URL 안의 괄호 한 겹까지 허용: https://en.wikipedia.org/wiki/Shellshock_(software_bug)
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://(?:[^()\s]|\([^()\s]*\))+)\)")
HEADING_RE = re.compile(r"^#{2,}\s+(.+?)\s*$")

WAYBACK_RE = re.compile(r"^(https?://web\.archive\.org/web/)(\d+)(?:[a-z]{2}_)?/(.+)$")


@dataclass(frozen=True)
class SourceEntry:
    url: str
    company: str
    category: str
    description: str
    is_secondary: bool


def normalize_url(url: str) -> str:
    """중복 판정용 정규화: 스킴·호스트 소문자, fragment 제거. 경로와 쿼리는 그대로 둔다."""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))


def wayback_raw_url(url: str) -> str:
    """Wayback 스냅샷이면 툴바 없는 원본 HTML 주소(`<ts>id_/`)로 바꾼다. 아니면 그대로."""
    m = WAYBACK_RE.match(url)
    if not m:
        return url
    return f"{m.group(1)}{m.group(2)}id_/{m.group(3)}"


def original_url(url: str) -> str:
    """Wayback 스냅샷이면 원래 문서 주소, 아니면 그대로 (추출 메타데이터용)."""
    m = WAYBACK_RE.match(url)
    return m.group(3) if m else url


def _strip_links(text: str) -> str:
    return LINK_RE.sub(lambda m: m.group(1), text)


def parse_readme(text: str) -> list[SourceEntry]:
    entries: list[SourceEntry] = []
    category = ""
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        heading = HEADING_RE.match(block)
        if heading:
            category = heading.group(1)
            continue
        if not category or category.lower() in EXCLUDED_SECTIONS:
            continue
        links = list(LINK_RE.finditer(block))
        if not links or links[0].start() != 0:
            continue

        first = links[0]
        company = first.group(1).strip()
        description = _strip_links(block[first.end():]).lstrip(" .").strip()
        description = re.sub(r"\s+", " ", description)
        for i, m in enumerate(links):
            entries.append(
                SourceEntry(
                    url=normalize_url(m.group(2)),
                    company=company,
                    category=category,
                    description=description,
                    is_secondary=i > 0,
                )
            )
    return _dedupe(entries)


def _dedupe(entries: list[SourceEntry]) -> list[SourceEntry]:
    """같은 URL은 한 번만. 어느 한 곳에서라도 주 링크였다면 주 링크로 남긴다."""
    by_url: dict[str, SourceEntry] = {}
    for e in entries:
        prev = by_url.get(e.url)
        if prev is None or (prev.is_secondary and not e.is_secondary):
            by_url[e.url] = e
    return list(by_url.values())
