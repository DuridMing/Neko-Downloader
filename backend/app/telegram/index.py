"""In-memory index of channel media, kept separate from downloading.

Deliberately not a database. CLAUDE.md's invariant is that this service holds
no long-term state and a restart is a clean slate, so the index lives and dies
with the process exactly like JobQueue.jobs does. Accepted cost: a restart
re-scans channels from scratch, because the watermark goes with it.

Indexing stores metadata only. Nothing here fetches bytes.
"""

from typing import Optional

from .types import TgMediaItem


class TgIndex:
    def __init__(self) -> None:
        self._items: dict[tuple[int, int], TgMediaItem] = {}
        # First message seen carrying each file. Stage 3 hardlinks against this
        # so the same file reposted in another channel is downloaded once.
        self._by_document: dict[str, tuple[int, int]] = {}
        # Highest message_id seen per channel = incremental resume point.
        self._watermarks: dict[int, int] = {}

    # -- writes ------------------------------------------------------------

    def add(self, item: TgMediaItem) -> bool:
        """Insert one item. False if (channel_id, message_id) was already
        indexed — that pair is the primary key."""
        if item.key in self._items:
            return False
        self._items[item.key] = item
        if item.document_id and item.document_id not in self._by_document:
            self._by_document[item.document_id] = item.key
        # Track the high-water mark even for ids we skip, so resuming never
        # rewinds. Gaps in message ids are normal and carry no meaning.
        current = self._watermarks.get(item.channel_id, 0)
        if item.message_id > current:
            self._watermarks[item.channel_id] = item.message_id
        return True

    def note_scanned(self, channel_id: int, message_id: int) -> None:
        """Advance the watermark past a message we chose not to index (text
        post, unwanted type). Without this a channel ending in non-media posts
        would be re-scanned from the same point forever."""
        if message_id > self._watermarks.get(channel_id, 0):
            self._watermarks[channel_id] = message_id

    # -- reads -------------------------------------------------------------

    def watermark(self, channel_id: int) -> int:
        """Resume point: pass as after_message_id. 0 means "never scanned"."""
        return self._watermarks.get(channel_id, 0)

    def get(self, channel_id: int, message_id: int) -> Optional[TgMediaItem]:
        return self._items.get((channel_id, message_id))

    def duplicate_of(self, item: TgMediaItem) -> Optional[TgMediaItem]:
        """An already-indexed item holding the same file, possibly in another
        channel. None when this is the first sighting."""
        if not item.document_id:
            return None
        key = self._by_document.get(item.document_id)
        if key is None or key == item.key:
            return None
        return self._items.get(key)

    def items(
        self,
        channel_id: Optional[int] = None,
        *,
        kind: Optional[str] = None,
        min_size: Optional[int] = None,
        search: Optional[str] = None,
    ) -> list[TgMediaItem]:
        """Browse/filter before queueing any download."""
        found = self._items.values()
        if channel_id is not None:
            found = [i for i in found if i.channel_id == channel_id]
        if kind is not None:
            # Also match on mime top-level: a video uploaded as a file has
            # kind "document", and "--kind video" that hides every video in
            # the channel is useless. "photo" covers image/* documents too.
            wanted = "image" if kind == "photo" else kind
            found = [
                i
                for i in found
                if i.kind == kind
                or (i.mime_type or "").split("/")[0] == wanted
            ]
        if min_size is not None:
            found = [i for i in found if (i.file_size or 0) >= min_size]
        if search:
            needle = search.lower()
            found = [
                i
                for i in found
                if needle in (i.caption or "").lower()
                or needle in (i.file_name or "").lower()
            ]
        return sorted(found, key=lambda i: i.key)

    def __len__(self) -> int:
        return len(self._items)

