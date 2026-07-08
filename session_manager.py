"""
会话级别的工具状态管理
"""
import asyncio
from enum import Enum
from typing import Dict, Optional
from dataclasses import dataclass, field


class SessionState(Enum):
    """会话状态机"""
    IDLE = "idle"
    STREAMING = "streaming"
    INTERRUPTED = "interrupted"
    WAITING_APPROVAL = "waiting_approval"
    RESUMED = "resumed"
    DONE = "done"


@dataclass
class SessionContext:
    """单个会话的上下文"""
    session_id: str
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    state: SessionState = SessionState.IDLE
    push_task: Optional[asyncio.Task] = None
    stream_task: Optional[asyncio.Task] = None
    websocket: Optional[object] = None  # 实际类型是 WebSocket
    config: Optional[dict] = None


class SessionManager:
    """会话管理器 - 管理所有会话的生命周期"""

    def __init__(self):
        self._sessions: Dict[str, SessionContext] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, session_id: str, websocket=None) -> SessionContext:
        """获取或创建会话上下文"""
        async with self._lock:
            if session_id not in self._sessions:
                ctx = SessionContext(session_id=session_id)
                if websocket:
                    ctx.websocket = websocket
                self._sessions[session_id] = ctx
            return self._sessions[session_id]

    async def get(self, session_id: str) -> Optional[SessionContext]:
        """获取会话上下文"""
        async with self._lock:
            return self._sessions.get(session_id)

    async def set_state(self, session_id: str, state: SessionState):
        """设置会话状态"""
        async with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].state = state

    async def get_queue(self, session_id: str) -> asyncio.Queue:
        """获取会话的队列"""
        ctx = await self.get_or_create(session_id)
        return ctx.queue

    async def cleanup(self, session_id: str):
        """清理会话资源"""
        async with self._lock:
            ctx = self._sessions.pop(session_id, None)
            if ctx:
                # 取消 push_task
                if ctx.push_task and not ctx.push_task.done():
                    ctx.push_task.cancel()
                    try:
                        await ctx.push_task
                    except asyncio.CancelledError:
                        pass

                # 清空队列
                while not ctx.queue.empty():
                    try:
                        ctx.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

    def get_all_sessions(self) -> list:
        """获取所有会话ID（用于监控）"""
        return list(self._sessions.keys())


# 全局单例
session_manager = SessionManager()
