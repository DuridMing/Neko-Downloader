import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import BACKEND_DIR
from .queue import job_queue

logging.basicConfig(level=logging.INFO)

# Write all application logs to a rotating file so they survive container
# restarts and can be inspected outside of `docker logs`.
_app_log_path = BACKEND_DIR / "logs" / "app.log"
try:
    _app_log_path.parent.mkdir(parents=True, exist_ok=True)
    _app_log_handler = RotatingFileHandler(
        _app_log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    _app_log_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    )
    logging.getLogger().addHandler(_app_log_handler)
except OSError as exc:
    logging.getLogger("neko").warning(
        "App log %s not writable (%s); logs go to stdout only", _app_log_path, exc
    )

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await job_queue.start()
    yield
    await job_queue.stop()


app = FastAPI(title="Neko Downloader", lifespan=lifespan)
app.include_router(router)

if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
