#!/usr/bin/env bash
# 레포 밖에 설정 폴더를 만든다: ~/.config/postmortem-rag/
#   rag.env           앱 설정 (LLM 키 등)            ← run_api.sh 가 읽음
#   secret-patterns   커밋 금지 문자열 (도메인 등)     ← check_secrets.sh 가 읽음
# 이미 있는 파일은 덮어쓰지 않는다.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAG_CONFIG_DIR="${RAG_CONFIG_DIR:-$HOME/.config/postmortem-rag}"

mkdir -p "$RAG_CONFIG_DIR"
chmod 700 "$RAG_CONFIG_DIR"

for pair in "rag.env.example:rag.env" "secret-patterns.example:secret-patterns"; do
  src="$PROJECT_DIR/${pair%%:*}"
  dst="$RAG_CONFIG_DIR/${pair##*:}"
  if [[ -e "$dst" ]]; then
    echo "유지: $dst (이미 있음)"
  else
    install -m 600 "$src" "$dst"
    echo "생성: $dst"
  fi
done

echo
echo "편집:  nano $RAG_CONFIG_DIR/rag.env"
