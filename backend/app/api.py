import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .audit import audit
from .models import JobCreate, JobStatus
from .queue import job_queue
from .ws import ws_manager

router = APIRouter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


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


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        await ws.send_json({"type": "queue_snapshot", "jobs": job_queue.snapshot()})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(ws)
