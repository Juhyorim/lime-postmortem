#!/usr/bin/env bash
# API 서버 실행 스크립트.
# AWS에서는 systemd가, 갤럭시폰(Termux)에서는 termux-services가 이 스크립트를 호출한다.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# 설정은 레포 밖에 둔다: ~/.config/postmortem-rag/rag.env
# (다른 위치를 쓰려면 RAG_CONFIG_DIR 환경 변수로 지정)
RAG_CONFIG_DIR="${RAG_CONFIG_DIR:-$HOME/.config/postmortem-rag}"
RAG_ENV_FILE="$RAG_CONFIG_DIR/rag.env"
if [[ -f "$RAG_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$RAG_ENV_FILE"
  set +a
else
  echo "설정 파일이 없어 기본값으로 실행합니다: $RAG_ENV_FILE (scripts/init_config.sh 로 생성)" >&2
fi

# systemd 환경에는 ~/.local/bin 이 PATH에 없을 수 있어서 직접 찾는다.
UV_BIN="${UV_BIN:-$(command -v uv || echo "$HOME/.local/bin/uv")}"
if [[ ! -x "$UV_BIN" ]]; then
  echo "uv를 찾을 수 없습니다: $UV_BIN" >&2
  exit 1
fi

# 워커는 1개: 이후 임베딩 모델이 워커마다 따로 로드되므로 2GB 서버에서는 1개로 고정.
exec "$UV_BIN" run --frozen --no-dev \
  uvicorn app.main:app \
  --host 127.0.0.1 \
  --port "${PORT:-8000}" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips 127.0.0.1
