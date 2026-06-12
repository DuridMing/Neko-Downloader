#!/usr/bin/env bash
# 啟動 Neko Downloader（前景執行；也是 systemd 服務的進入點）。
# 設定讀取順序與後端一致：環境變數 > .env > config.json > 預設值。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ -x "$ROOT/backend/.venv/bin/uvicorn" ] ||
    { echo "尚未安裝，請先執行 ./scripts/setup.sh" >&2; exit 1; }

# 只取啟動本身需要的變數；其餘設定由後端的 pydantic-settings 自行載入
if [ -f "$ROOT/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    . "$ROOT/.env"
    set +a
fi

exec "$ROOT/backend/.venv/bin/uvicorn" app.main:app \
    --app-dir "$ROOT/backend" \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8000}"
