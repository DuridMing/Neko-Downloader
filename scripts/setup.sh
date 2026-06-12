#!/usr/bin/env bash
# 一次性安裝：建立 Python venv、安裝相依、下載無頭 Chromium、建置前端。
# 用法：./scripts/setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null || die "找不到 python3，請先安裝 Python 3.11+"
command -v ffmpeg  >/dev/null || warn "找不到 ffmpeg，下載合併會失敗 — 請安裝（如：sudo apt install ffmpeg）"

info "建立 Python 虛擬環境並安裝後端相依"
[ -d backend/.venv ] || python3 -m venv backend/.venv
backend/.venv/bin/pip install --upgrade -q -r backend/requirements.txt

info "下載瀏覽器嗅探用的無頭 Chromium"
backend/.venv/bin/playwright install chromium ||
    warn "Chromium 安裝失敗，瀏覽器嗅探功能將無法使用（其餘功能不受影響）"

if command -v npm >/dev/null; then
    info "建置前端（輸出到 backend/static）"
    (cd frontend && npm install --no-audit --no-fund && npm run build)
elif [ -d backend/static ]; then
    warn "找不到 npm，沿用既有的 backend/static 前端建置產物"
else
    die "找不到 npm 且 backend/static 不存在，請先安裝 Node.js 20+ 再執行本腳本"
fi

info "完成！啟動方式："
echo "    ./scripts/start.sh                       # 前景執行"
echo "    sudo ./scripts/install-service.sh        # 安裝為 systemd 服務（開機自動啟動）"
