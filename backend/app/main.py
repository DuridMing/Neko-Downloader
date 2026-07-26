import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth
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


@app.middleware("http")
async def require_password(request: Request, call_next):
    """The gate. Only covers HTTP — Starlette middleware never sees websocket
    connections, so /ws checks the same cookie itself in api.py."""
    if auth.needs_auth(request.url.path) and not auth.cookie_ok(
        request.cookies.get(auth.COOKIE_NAME)
    ):
        return JSONResponse({"detail": "需要密碼"}, status_code=401)
    return await call_next(request)


app.include_router(router)

if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
