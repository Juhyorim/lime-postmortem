#!/usr/bin/env bash
# 커밋하려는 변경분(staged)에 비밀값/개인정보가 있으면 커밋을 막는다.
# git pre-commit 훅으로 실행된다 (scripts/install_git_hooks.sh 로 설치).
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
fail=0

# 1) 금지 파일이 staged 되었는지
blocked_files=$(git diff --cached --name-only --diff-filter=ACMR \
  | grep -E '(^|/)\.env($|\.)|(^|/)rag\.env$|\.pem$|\.key$|(^|/)\.?secret-patterns$|(^|/)secrets/|^deploy/Caddyfile$' || true)
if [[ -n "$blocked_files" ]]; then
  echo "❌ 커밋하면 안 되는 파일이 포함되어 있습니다:"
  echo "$blocked_files" | sed 's/^/   /'
  fail=1
fi

# 추가된 줄만 검사 (예시 파일은 제외)
added=$(git diff --cached -U0 --diff-filter=ACMR -- . \
  ':(exclude)secret-patterns.example' ':(exclude)scripts/check_secrets.sh' \
  | grep -E '^\+' | grep -v -E '^\+\+\+' || true)

# 2) 흔한 비밀값 형태
generic='(sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{20,}|LLM_API_KEY=[^[:space:]]+)'
if hits=$(echo "$added" | grep -n -E "$generic"); then
  echo "❌ API 키/개인키/비밀번호 해시로 보이는 값이 있습니다:"
  # 값 자체가 터미널(과 Claude Code)에 보이지 않도록 앞부분만 표시
  echo "$hits" | cut -c1-14 | sed 's/^/   /; s/$/***/'
  fail=1
fi

# 3) 개인 금지 목록 (레포 밖: ~/.config/postmortem-rag/secret-patterns)
PATTERNS_FILE="${RAG_CONFIG_DIR:-$HOME/.config/postmortem-rag}/secret-patterns"
if [[ -f "$PATTERNS_FILE" ]]; then
  while IFS= read -r pat; do
    [[ -z "$pat" || "$pat" =~ ^# ]] && continue
    if echo "$added" | grep -q -i -F -- "$pat"; then
      echo "❌ 개인 금지 목록의 값이 포함되어 있습니다: ${pat:0:3}***"
      fail=1
    fi
  done < "$PATTERNS_FILE"
else
  echo "⚠️  $PATTERNS_FILE 가 없습니다. scripts/init_config.sh 로 만들고 도메인/이메일을 적어주세요."
fi

if [[ $fail -ne 0 ]]; then
  echo
  echo "커밋을 중단했습니다. 해당 값을 placeholder(rag.example.com 등)로 바꾸거나 파일을 unstage 하세요:"
  echo "   git restore --staged <파일>"
  exit 1
fi
