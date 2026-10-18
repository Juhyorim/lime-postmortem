#!/usr/bin/env bash
# 수집 배치 실행 스크립트. cron에서 호출한다 (systemd timer는 쓰지 않음).
#   bash scripts/run_collect.sh [--limit N] [--report] ...
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# 설정은 레포 밖에 둔다: ~/.config/postmortem-rag/rag.env (run_api.sh와 같은 방식)
RAG_CONFIG_DIR="${RAG_CONFIG_DIR:-$HOME/.config/postmortem-rag}"
RAG_ENV_FILE="$RAG_CONFIG_DIR/rag.env"
if [[ -f "$RAG_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$RAG_ENV_FILE"
  set +a
fi

# cron 환경에는 ~/.local/bin 이 PATH에 없을 수 있어서 직접 찾는다.
UV_BIN="${UV_BIN:-$(command -v uv || echo "$HOME/.local/bin/uv")}"
if [[ ! -x "$UV_BIN" ]]; then
  echo "uv를 찾을 수 없습니다: $UV_BIN" >&2
  exit 1
fi

# API 서버보다 낮은 우선순위로
exec nice -n 10 "$UV_BIN" run --frozen --no-dev python -m ingest.collect "$@"
