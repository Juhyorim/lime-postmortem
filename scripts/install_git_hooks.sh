#!/usr/bin/env bash
# git pre-commit 훅 설치. 저장소를 clone/init 한 PC마다 한 번 실행.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
HOOK="$ROOT/.git/hooks/pre-commit"
cat > "$HOOK" <<'EOF'
#!/usr/bin/env bash
exec bash "$(git rev-parse --show-toplevel)/scripts/check_secrets.sh"
EOF
chmod +x "$HOOK"
echo "pre-commit 훅 설치 완료: $HOOK"
