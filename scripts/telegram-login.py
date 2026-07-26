#!/usr/bin/env python3
"""One-time Telegram 登入，產生 MTProto session 檔。

用法（從 repo 根目錄）：
    backend/.venv/bin/python scripts/telegram-login.py

需要先在 .env 設定 TELEGRAM_API_ID / TELEGRAM_API_HASH
（到 https://my.telegram.org/apps 申請）。

網頁「設定」面板也能登入（同一套流程，見 app/telegram/weblogin.py）；
沒有瀏覽器、或不想讓驗證碼經過 HTTP 時，用這支腳本。
session 檔等同帳號完整存取權，不會進資料庫、日誌、API 回應，也不該跟著一般備份走。
"""

import asyncio
import sys
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.telegram import TgError, build_source, session_dir  # noqa: E402


async def main() -> int:
    try:
        source = build_source()
    except TgError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        print("  請先在 .env 設定 TELEGRAM_API_ID 與 TELEGRAM_API_HASH", file=sys.stderr)
        return 2

    print(f"session 目錄：{session_dir()}")
    phone = input("手機號碼（含國碼，例 +886912345678）：").strip()
    if not phone:
        print("✗ 未輸入號碼", file=sys.stderr)
        return 2

    try:
        account = await source.login(
            phone,
            ask_code=lambda: input("Telegram 傳送的驗證碼："),
            ask_password=lambda: getpass("兩步驟驗證密碼（不會顯示）："),
        )
    except TgError as exc:
        print(f"✗ 登入失敗：{exc}", file=sys.stderr)
        return 1

    print(f"✓ 已登入：{account.label}（id={account.id}）")
    print("  session 已寫入並設為 0600，請勿提交或備份此檔。")
    print("  下一步：索引頻道前，請先用官方 Telegram 手動加入目標頻道。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
