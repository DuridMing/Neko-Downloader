import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, Field, HttpUrl


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    READY = "ready"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class JobCreate(BaseModel):
    url: HttpUrl
    referer: Optional[str] = None
    # Per-request cookies from the user's browser. Accepts either a raw
    # "name=value; name2=value2" header or a Netscape cookies.txt body.
    cookies: Optional[str] = Field(default=None, max_length=65536)


class Job(BaseModel):
    id: str
    url: str
    referer: Optional[str] = None
    # Sensitive, in-memory only: never serialized to clients (see public_dict)
    # nor written to the audit log; cleared as soon as the download starts.
    cookies: Optional[str] = None
    handler: str
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    speed: Optional[str] = None
    eta: Optional[str] = None
    title: Optional[str] = None
    filename: Optional[str] = None
    filesize: Optional[int] = None
    downloaded: Optional[int] = None
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    file_path: Optional[str] = None

    @classmethod
    def new(
        cls,
        url: str,
        handler: str,
        referer: Optional[str] = None,
        cookies: Optional[str] = None,
    ) -> "Job":
        return cls(
            id=uuid.uuid4().hex[:12],
            url=url,
            referer=referer,
            cookies=cookies,
            handler=handler,
            created_at=datetime.now(timezone.utc),
        )

    def public_dict(self) -> dict:
        """Serializable view sent to clients; never expose file_path or cookies."""
        data = self.model_dump(mode="json")
        data.pop("file_path", None)
        data.pop("cookies", None)
        return data


class CancelledByUser(Exception):
    pass


@dataclass
class DownloadContext:
    """Everything a handler needs to perform a download, format-agnostic."""

    output_dir: Path
    headers: dict[str, str]
    on_progress: Callable[[dict], None]
    is_cancelled: Callable[[], bool]
    # Per-request cookies file (user's browser cookies); takes priority over
    # the system-wide cookie settings. None = fall back to system / no auth.
    cookiefile: Optional[Path] = None

    def check_cancelled(self) -> None:
        if self.is_cancelled():
            raise CancelledByUser()


@dataclass
class DownloadResult:
    file_path: Path
    title: str
    filename: str
    filesize: int = field(default=0)
