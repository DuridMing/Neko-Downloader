#!/usr/bin/env python3
"""索引單一頻道的媒體（只抓 metadata，不下載任何檔案）。

用法（從 repo 根目錄）：
    backend/.venv/bin/python scripts/telegram-index.py @channelname
    backend/.venv/bin/python scripts/telegram-index.py https://t.me/c/1234567890/1 --limit 50
    backend/.venv/bin/python scripts/telegram-index.py @channelname --kind video --min-mb 100

頻道必須是你的帳號「已經加入」的：本工具不會、也無法自動加入頻道。
"""

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.telegram import (  # noqa: E402
    TgError,
    TgFloodWait,
    TgIndex,
    build_source,
    parse_ref,
)


def _human(size: int | None) -> str:
    if not size:
        return "-"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GB"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("channel", help="@username、t.me 連結，或數字 id")
    parser.add_argument(
        "--limit",
        type=int,
        help="最多索引幾筆（單則貼文連結預設 1，整個頻道預設 30）",
    )
    parser.add_argument("--kind", help="只列出某類型：video / document / audio / photo")
    parser.add_argument("--min-mb", type=float, default=0, help="只列出大於此 MB 的檔案")
    args = parser.parse_args()

    source = build_source()
    index = TgIndex()

    try:
        await source.connect()
    except TgError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    try:
        channel = await source.get_channel(args.channel)
        flags = []
        if channel.is_private:
            flags.append("私人")
        if channel.protected:
            flags.append("限制轉存")
        print(
            f"頻道：{channel.title} (id={channel.id})"
            + (f"  [{'、'.join(flags)}]" if flags else "")
        )

        added = duplicate = 0
        seen = Counter()

        def on_scan(message_id: int, kind: str | None) -> None:
            seen[kind or "（純文字／服務訊息）"] += 1
            # Advance past posts we index nothing for, or a channel whose newest
            # posts are text would be rescanned from the same point forever.
            index.note_scanned(channel.id, message_id)

        # A post link means that post, not the channel's first message ever.
        # -1 so the linked post itself is included; limit 1 so only it is.
        _, from_message_id = parse_ref(args.channel)
        after = from_message_id - 1 if from_message_id else 0
        limit = args.limit if args.limit is not None else (1 if after else 30)
        if after:
            print(f"從 message_id={from_message_id} 開始，往新的掃 {limit} 筆")

        async for item in source.iter_media(
            channel, after_message_id=after, limit=limit, on_scan=on_scan
        ):
            if index.add(item):
                added += 1
            else:
                duplicate += 1

        print(
            f"掃描 {sum(seen.values())} 則訊息："
            f"新增 {added} 筆，重複 {duplicate} 筆，"
            f"水位 message_id={index.watermark(channel.id)}"
        )
        if seen:
            breakdown = "、".join(f"{k} {n}" for k, n in seen.most_common())
            print(f"訊息型別分布：{breakdown}")
        if added == 0:
            print("⚠ 這個頻道沒有掃到可下載的檔案（上面的型別分布可看出原因）。")
        elif from_message_id and index.get(channel.id, from_message_id) is None:
            # The link pointed at a text/service post, so what follows is the
            # *next* file — say so instead of letting it pass as that post.
            print(f"⚠ message_id={from_message_id} 本身沒有檔案，以下是它之後的貼文。")
        print()
    except TgFloodWait as exc:
        print(f"✗ 觸發限流，需等到 {exc.retry_at.isoformat(timespec='seconds')}", file=sys.stderr)
        return 3
    except TgError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    finally:
        await source.close()

    rows = index.items(
        channel.id,
        kind=args.kind,
        min_size=int(args.min_mb * 1024 * 1024) or None,
    )
    print(f"{'msg_id':>8}  {'類型':<8} {'大小':>8}  {'時長':>6}  檔名／說明")
    print("-" * 78)
    for item in rows:
        secs = int(item.duration or 0)  # the library hands back floats
        duration = f"{secs // 60}:{secs % 60:02d}" if secs else "-"
        label = item.file_name or (item.caption or "").replace("\n", " ")[:40] or "-"
        print(
            f"{item.message_id:>8}  {item.kind:<8} {_human(item.file_size):>8}  "
            f"{duration:>6}  {label}"
        )
    print(f"\n共 {len(rows)} 筆（未下載任何檔案）")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
