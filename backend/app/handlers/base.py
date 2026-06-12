from abc import ABC, abstractmethod

from ..models import DownloadContext, DownloadResult, Job


class DownloadHandler(ABC):
    """A download strategy for one family of sources.

    To support a new format: subclass this, implement both methods, and
    register an instance in `handlers/__init__.py`. The queue, API, WebSocket
    layer and frontend never need to change.
    """

    name: str

    @abstractmethod
    def can_handle(self, url: str) -> bool: ...

    @abstractmethod
    def download(self, job: Job, ctx: DownloadContext) -> DownloadResult:
        """Blocking download; runs in a worker thread. Must call
        ctx.on_progress() with progress events and honor ctx.check_cancelled()."""
        ...


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: list[DownloadHandler] = []

    def register(self, handler: DownloadHandler) -> None:
        self._handlers.append(handler)

    def resolve(self, url: str) -> DownloadHandler:
        for handler in self._handlers:
            if handler.can_handle(url):
                return handler
        raise ValueError(f"No handler can process URL: {url}")

    def resolve_all(self, url: str) -> list[DownloadHandler]:
        """All matching handlers in priority order; the worker tries each in
        turn so a failed strategy falls back to the next one."""
        matched = [h for h in self._handlers if h.can_handle(url)]
        if not matched:
            raise ValueError(f"No handler can process URL: {url}")
        return matched


registry = HandlerRegistry()
