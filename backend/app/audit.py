"""Audit trail: every job lifecycle event is written as one JSON line so the
usage of this tool can be reviewed later (who submitted/fetched what, when).

Events go to stdout (docker logs / journalctl) and, unless disabled, to a
rotating file at settings.audit_log_file.
"""

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import BACKEND_DIR, settings

logger = logging.getLogger("neko.audit")
logger.setLevel(logging.INFO)


def _setup_file_handler() -> None:
    if not settings.audit_log_file:
        return
    path = Path(settings.audit_log_file)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    except OSError as exc:
        logging.getLogger("neko").warning(
            "Audit file %s not writable (%s); audit events go to stdout only", path, exc
        )


_setup_file_handler()


def audit(event: str, job_id: str | None = None, **fields) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
    }
    if job_id:
        record["job_id"] = job_id
    record.update({k: v for k, v in fields.items() if v is not None})
    logger.info(json.dumps(record, ensure_ascii=False))
