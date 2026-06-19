# db/crud.py
import logging
import aiomysql

from db import get_pool
from config import _trace_id_var

logger = logging.getLogger(__name__)


# -------- sessions --------
async def create_session(thread_id: str, user_id: str = "default", title: str = "新对话"):
    trace_id = _trace_id_var.get()
    logger.info(f"[{trace_id}] create_session thread_id={thread_id}")
    async with get_pool().acquire() as conn:
        async with conn.cursor() as cur:
                        await cur.execute(
                "INSERT IGNORE INTO sessions (id, user_id, title) VALUES (%s, %s, %s)",
                (thread_id, user_id, title)
            )

async def get_sessions(user_id: str = "default"):
    trace_id = _trace_id_var.get()
    logger.info(f"[{trace_id}] get_sessions user_id={user_id}")
    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT id, title, created_at, updated_at FROM sessions WHERE user_id=%s ORDER BY updated_at DESC",
                (user_id,)
            )
            return await cur.fetchall()

async def update_session_title(thread_id: str, title: str):
    trace_id = _trace_id_var.get()
    logger.info(f"[{trace_id}] update_session_title thread_id={thread_id}")
    async with get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE sessions SET title=%s WHERE id=%s",
                (title, thread_id)
            )

async def delete_session(thread_id: str):
    trace_id = _trace_id_var.get()
    logger.info(f"[{trace_id}] delete_session thread_id={thread_id}")
    async with get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM sessions WHERE id=%s", (thread_id,))
            await cur.execute("DELETE FROM messages WHERE thread_id=%s", (thread_id,))

# -------- messages --------

async def save_message(thread_id: str, role: str, content: str):
    trace_id = _trace_id_var.get()
    content_preview = content[:50] + "..." if len(content) > 50 else content
    logger.info(f"[{trace_id}] save_message thread_id={thread_id} role={role} content={content_preview}")
    async with get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO messages (thread_id, role, content) VALUES (%s, %s, %s)",
                (thread_id, role, content)
            )

async def get_messages(thread_id: str):
    trace_id = _trace_id_var.get()
    logger.info(f"[{trace_id}] get_messages thread_id={thread_id}")
    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT role, content, created_at FROM messages WHERE thread_id=%s ORDER BY created_at ASC",
                (thread_id,)
            )
            return await cur.fetchall()