#!/usr/bin/env bash
# AWS(Debian/Ubuntu) 전용: systemd 서비스 등록.
# 현재 사용자와 프로젝트 경로를 자동으로 채워서 /etc/systemd/system/rag.service 를 만든다.
# 사용법:  bash scripts/install_service.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(id -un)"
UNIT_PATH=/etc/systemd/system/rag.service

sed -e "s|__USER__|${RUN_USER}|g" \
    -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
    "${PROJECT_DIR}/deploy/rag.service.template" \
  | sudo tee "$UNIT_PATH" > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable --now rag
sleep 3
systemctl --no-pager status rag | head -n 12
echo
echo "로컬 확인: curl -s http://127.0.0.1:8000/health"
