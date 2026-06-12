#!/usr/bin/env bash
# 將 Neko Downloader 安裝為 systemd 服務（開機自動啟動）。
# 用法：sudo ./scripts/install-service.sh [執行身分的使用者名稱]
#       預設使用者為呼叫 sudo 的人（$SUDO_USER）。
# 移除：sudo systemctl disable --now neko-downloader
#       sudo rm /etc/systemd/system/neko-downloader.service
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DST=/etc/systemd/system/neko-downloader.service
RUN_USER="${1:-${SUDO_USER:-$(id -un)}}"

[ "$(id -u)" -eq 0 ] || { echo "請以 sudo 執行：sudo $0" >&2; exit 1; }
[ -x "$ROOT/backend/.venv/bin/uvicorn" ] ||
    { echo "尚未安裝，請先以一般使用者執行 ./scripts/setup.sh" >&2; exit 1; }
id "$RUN_USER" >/dev/null 2>&1 || { echo "使用者不存在：$RUN_USER" >&2; exit 1; }

# 審查日誌目錄（服務以 ProtectHome=read-only 執行，僅此目錄開放寫入）
mkdir -p "$ROOT/backend/logs"
chown "$RUN_USER": "$ROOT/backend/logs"

sed -e "s|@PROJECT_DIR@|$ROOT|g" -e "s|@RUN_USER@|$RUN_USER|g" \
    "$ROOT/scripts/neko-downloader.service.template" > "$UNIT_DST"

systemctl daemon-reload
systemctl enable --now neko-downloader

echo "已安裝並啟動。常用指令："
echo "    systemctl status neko-downloader     # 查看狀態"
echo "    journalctl -u neko-downloader -f     # 追蹤日誌"
echo "    sudo systemctl restart neko-downloader"
