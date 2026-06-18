# api/session.py
import logging
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from db import get_sessions, get_messages, delete_session,create_session as db_create_session, update_session_title
from config import _trace_id_var
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class CreateSessionRequest(BaseModel):
    thread_id: str
    title: str = "新对话"

class UpdateTitleRequest(BaseModel):
    title: str

@router.patch("/sessions/{thread_id}/title")
async def update_title(thread_id: str, req: UpdateTitleRequest):
    await update_session_title(thread_id, req.title)
    return {"ok": True}
@router.post("/sessions")
async def create_session_api(req: CreateSessionRequest):
    trace_id = _trace_id_var.get()
    logger.info(f"[{trace_id}] POST /api/sessions thread_id={req.thread_id}")
    await db_create_session(req.thread_id, title=req.title)
    return {"ok": True}


@router.get("/sessions")
async def list_sessions():
    trace_id = _trace_id_var.get()
    logger.info(f"[{trace_id}] GET /api/sessions")
    data = await get_sessions()
    return JSONResponse([
        {**s,
         "created_at": s["created_at"].isoformat() if s.get("created_at") else None,
         "updated_at": s["updated_at"].isoformat() if s.get("updated_at") else None,
        }
        for s in data
    ])


@router.get("/sessions/{thread_id}/messages")
async def list_messages(thread_id: str):
    trace_id = _trace_id_var.get()
    logger.info(f"[{trace_id}] GET /api/sessions/{thread_id}/messages")
    data = await get_messages(thread_id=thread_id)
    return JSONResponse([
        {**m,
         "created_at": m["created_at"].isoformat() if m.get("created_at") else None,
        }
        for m in data
    ])


@router.delete("/sessions/{thread_id}")
async def remove_session(thread_id: str):
    trace_id = _trace_id_var.get()
    logger.info(f"[{trace_id}] DELETE /api/sessions/{thread_id}")
    await delete_session(thread_id)
    return {"ok": True}