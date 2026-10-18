"""환경 변수 기반 설정.

설정 파일은 레포 밖(~/.config/postmortem-rag/rag.env)에 있고,
scripts/run_api.sh 가 읽어서 환경 변수로 넘겨준다.
(systemd, Termux 어느 쪽에서 띄워도 같은 방식으로 동작하게 하기 위함)
"""

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    app_env: str
    data_dir: Path
    index_path: Path
    llm_provider: str
    llm_model: str
    llm_api_key_set: bool
    crawl_contact: str
    crawl_delay_sec: float


def load_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))
    return Settings(
        app_env=os.getenv("APP_ENV", "dev"),
        data_dir=data_dir,
        index_path=Path(os.getenv("INDEX_PATH", data_dir / "index.db")),
        llm_provider=os.getenv("LLM_PROVIDER", ""),
        llm_model=os.getenv("LLM_MODEL", ""),
        # 키 값 자체는 어디에도 노출하지 않고, 설정 여부만 기록한다.
        llm_api_key_set=bool(os.getenv("LLM_API_KEY")),
        # 수집기 User-Agent에 붙는 연락처 (실제 값은 rag.env에만)
        crawl_contact=os.getenv("CRAWL_CONTACT", ""),
        crawl_delay_sec=float(os.getenv("CRAWL_DELAY_SEC") or 3.0),
    )
