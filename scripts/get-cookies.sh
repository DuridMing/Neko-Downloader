#!/usr/bin/env bash
# 互動式取得 cookies（不需要瀏覽器擴充功能）。
# 用法：./scripts/get-cookies.sh facebook [-o cookies.txt]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"

[ -x "$PY" ] || { echo "尚未安裝，請先執行 ./scripts/setup.sh" >&2; exit 1; }

exec "$PY" "$ROOT/scripts/get-cookies.py" "$@"
