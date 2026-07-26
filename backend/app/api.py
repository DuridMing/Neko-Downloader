import asyncio
from pathlib import Path

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from . import auth
from . import telegram as tg
from .audit import audit
from .handlers import telegram_handler
from .models import JobCreate, JobStatus
from .queue import job_queue
from .ws import ws_manager

router = APIRouter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/api/unlock")
async def unlock(payload: dict, request: Request, response: Response):
    """Exchange the shared password for a cookie. See app/auth.py."""
    if not auth.enabled():
        return {"ok": True, "required": False}
    if not auth.password_ok(str(payload.get("password", ""))):
        # Blunt brake: an internal tool does not need a rate limiter, but it
        # should not answer thousands of guesses per second either.
        await asyncio.sleep(1)
        audit("unlock_failed", client=_client_ip(request))
        raise HTTPException(status_code=401, detail="密碼不正確")
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.token(),
        max_age=auth.COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        # Only over HTTPS, or the cookie would be dropped on a plain-HTTP LAN.
        secure=request.url.scheme == "https",
    )
    audit("unlock_ok", client=_client_ip(request))
    return {"ok": True, "required": True}


@router.post("/api/jobs", status_code=201)
async def create_job(payload: JobCreate, request: Request):
    try:
        job = await job_queue.submit(str(payload.url), payload.referer, payload.cookies)
    except asyncio.QueueFull:
        audit("job_rejected_queue_full", url=str(payload.url), client=_client_ip(request))
        raise HTTPException(status_code=429, detail="Queue is full, try again later")
    audit(
        "job_submitted",
        job.id,
        url=job.url,
        referer=job.referer,
        # Record only that cookies were supplied, never their value.
        with_cookies=bool(payload.cookies),
        client=_client_ip(request),
    )
    return job.public_dict()


@router.get("/api/jobs")
async def list_jobs():
    return job_queue.snapshot()


@router.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = job_queue.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.public_dict()


@router.delete("/api/jobs/{job_id}")
async def cancel_job(job_id: str, request: Request):
    job = await job_queue.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    audit("job_cancel_requested", job_id, url=job.url, client=_client_ip(request))
    return {"ok": True}


@router.post("/api/jobs/{job_id}/select")
async def select_candidate(job_id: str, payload: dict, request: Request):
    index = payload.get("index")
    if not isinstance(index, int):
        raise HTTPException(status_code=422, detail="index must be an integer")
    try:
        job = await job_queue.select(job_id, index)
    except IndexError:
        raise HTTPException(status_code=422, detail="index out of range")
    except asyncio.QueueFull:
        raise HTTPException(status_code=429, detail="Queue is full, try again later")
    if job is None:
        raise HTTPException(status_code=409, detail="Job is not awaiting selection")
    audit("job_candidate_selected", job_id, url=job.url, index=index)
    return job.public_dict()


@router.get("/api/jobs/{job_id}/download")
async def download_job(job_id: str, request: Request):
    job = job_queue.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.READY or not job.file_path:
        raise HTTPException(status_code=409, detail=f"Job is not ready (status: {job.status})")
    path = Path(job.file_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="File no longer available")
    audit(
        "file_downloaded",
        job_id,
        url=job.url,
        filename=job.filename,
        filesize=job.filesize,
        client=_client_ip(request),
    )
    return FileResponse(
        path,
        filename=job.filename or path.name,
        media_type="application/octet-stream",
        background=BackgroundTask(job_queue.mark_done, job),
    )


# -- Telegram account ------------------------------------------------------
#
# Login moved out of the CLI and into the web UI on request. What that means:
# the phone number, the login code and the 2FA password travel over this API,
# so ACCESS_PASSWORD (app/auth.py) matters most here — without it these
# endpoints are open to anyone who can reach the port. Keep the service off
# public networks either way; plain HTTP means the values are readable to
# anyone who can capture traffic. The session file never leaves the server,
# and no credential is logged: the audit trail records only that a login
# happened, with the client IP.


@router.get("/api/telegram")
async def telegram_status():
    return await tg.status()


@router.post("/api/telegram/login")
async def telegram_login(payload: dict, request: Request):
    phone = str(payload.get("phone", "")).strip()
    if not phone:
        raise HTTPException(status_code=422, detail="請輸入手機號碼")
    if telegram_handler.is_busy():
        raise HTTPException(status_code=409, detail="有 Telegram 下載進行中，請稍後再登入")
    try:
        state = await tg.web_login.start(tg.build_source(), phone)
    except tg.TgError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Never record the phone number: an audit log is not the place for it.
    audit("telegram_login_started", client=_client_ip(request))
    return state


@router.post("/api/telegram/login/verify")
async def telegram_login_verify(payload: dict, request: Request):
    answer = str(payload.get("answer", "")).strip()
    if not answer:
        raise HTTPException(status_code=422, detail="請輸入驗證碼")
    try:
        state = await tg.web_login.submit(answer)
    except tg.TgError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if state["stage"] == "done":
        tg.forget_account()
        audit("telegram_login_succeeded", client=_client_ip(request))
    return state


@router.delete("/api/telegram/login")
async def telegram_login_abort():
    tg.web_login.cancel()
    return {"ok": True}


@router.delete("/api/telegram/session")
async def telegram_logout(request: Request):
    """Revoke and delete the session — the UI's "刪除設定"."""
    if telegram_handler.is_busy():
        raise HTTPException(status_code=409, detail="有 Telegram 下載進行中，請稍後再刪除")
    source = tg.build_source()
    if not source.session_exists():
        raise HTTPException(status_code=404, detail="目前沒有已登入的 Telegram 帳號")
    await source.logout()
    tg.forget_account()
    tg.web_login.cancel()
    audit("telegram_session_deleted", client=_client_ip(request))
    return {"ok": True}


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # HTTP middleware does not run for websockets, so the gate is repeated here.
    if auth.needs_auth("/ws") and not auth.cookie_ok(ws.cookies.get(auth.COOKIE_NAME)):
        await ws.close(code=1008)  # policy violation
        return
    await ws_manager.connect(ws)
    try:
        await ws.send_json({"type": "queue_snapshot", "jobs": job_queue.snapshot()})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(ws)
