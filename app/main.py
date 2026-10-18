from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI

from app.config import load_settings

settings = load_settings()

try:
    APP_VERSION = version("postmortem-rag")
except PackageNotFoundError:
    APP_VERSION = "0.1.0"

app = FastAPI(
    title="Postmortem RAG",
    version=APP_VERSION,
    # 운영 환경에서는 API 문서 페이지를 숨긴다.
    docs_url=None if settings.app_env == "prod" else "/docs",
    redoc_url=None,
    openapi_url=None if settings.app_env == "prod" else "/openapi.json",
)


@app.get("/health")
def health() -> dict:
    """서버 생존 확인용. 이후 단계에서 인덱스 상태도 여기에 추가한다."""
    return {
        "status": "ok",
        "version": APP_VERSION,
        "env": settings.app_env,
        "index_ready": settings.index_path.exists(),
        "llm_configured": settings.llm_api_key_set,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
