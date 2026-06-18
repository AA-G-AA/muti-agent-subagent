# api/chat.py
# Controller 层 —— 处理 WebSocket 连接，调用 supervisor_agent

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.utils.uuid import uuid7
from langchain_core.messages import ToolMessage


# from agents.supervisor_agent import supervisor_agent
import agents.supervisor_agent as supervisor_agent_module
from config import _trace_id_var
from db import create_session, save_message, get_messages, get_sessions

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text(json.dumps({
        "type": "info",
        "content": "✅ 已连接到 AI 助手，请开始对话！"
    }))

    try:
        while True:
            # 1. 接收前端发来的消息
            raw = await websocket.receive_text()
            data = json.loads(raw)
            user_message = data.get("message", "")

            # 检查是否为心跳
            if data.get("type") == "ping":
                continue

            if not user_message.strip():
                continue

            logger.info(f"📩 收到用户消息: {user_message}")

            # 2. 构造配置（从前端获取 thread_id，实现会话隔离）
            trace_id = str(uuid7())
            thread_id = data.get("thread_id", "web_user_001")
            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "user_id": "web_user",
                    "trace_id": trace_id,
                }
            }
            _trace_id_var.set(trace_id)
            logger.info(f"🧵 thread_id: {thread_id}, trace_id: {trace_id}")

            # 3. 首次出现该 thread_id 时，自动建会话（INSERT IGNORE 避免重复）
            await create_session(thread_id, user_id="web_user")

            # 4. 存用户消息
            await save_message(thread_id, "user", user_message)

            # 5. 通知前端开始处理
            await websocket.send_text(json.dumps({
                "type": "status",
                "content": "🤔 正在处理中..."
            }))

            # 6. 调用 supervisor_agent（非流式）
            # 调用时
            result = await supervisor_agent_module.supervisor_agent.ainvoke(
                {"messages": [{"role": "user", "content": user_message}]},
                config,
            )

            # 7. 提取最终 AI 回复
            full_reply = ""
            for m in reversed(result["messages"]):
                if m.type == "ai" and m.content:
                    full_reply = m.content
                    break

            logger.info(f"📤 Agent 回复: {full_reply}...")

            # 8. 推送给前端
            await websocket.send_text(json.dumps({
                "type": "result",
                "content": full_reply,
            }))

            # 9. 存 AI 回复
            await save_message(thread_id, "assistant", full_reply)

            # 10. 通知本轮结束
            await websocket.send_text(json.dumps({
                "type": "done",
            }))

    except WebSocketDisconnect:
        logger.info("🔴 客户端已断开连接")
    except Exception as e:
        logger.error(f"💥 WebSocket 异常: {e}")
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": f"系统异常: {str(e)}",
            }))
        except Exception:
            pass
