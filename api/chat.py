# api/chat.py
import logging
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import AIMessageChunk, AIMessage
from langchain_core.utils.uuid import uuid7
from langgraph.types import Command

import agents.supervisor_agent as supervisor_agent_module
from config import _trace_id_var
from db import create_session, save_message
from session_manager import session_manager, SessionState

logger = logging.getLogger(__name__)
router = APIRouter()

import json

def safe_json_dumps(obj):
    def default(o):
        if hasattr(o, 'model_dump'):
            return o.model_dump()
        if hasattr(o, '__dict__'):
            return o.__dict__
        return str(o)
    return json.dumps(obj, default=default)

async def _push_tool_status(session_id: str, websocket: WebSocket):
    """会话级别的工具状态推送任务"""
    ctx = await session_manager.get_or_create(session_id)
    q = ctx.queue

    logger.info(f"📤 push_task 启动: session={session_id}")

    try:
        while True:
            # 检查会话状态，如果是 DONE 则退出
            current_ctx = await session_manager.get(session_id)
            if current_ctx and current_ctx.state == SessionState.DONE:
                logger.info(f"📤 push_task 检测到 DONE，退出: session={session_id}")
                break

            try:
                msg = await asyncio.wait_for(q.get(), timeout=1.0)
                try:
                    await websocket.send_text(safe_json_dumps(msg))
                except Exception as e:
                    logger.error(f"📤 推送失败: {e}")
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info(f"📤 push_task 被取消: session={session_id}")
                break
            except Exception as e:
                logger.error(f"📤 push_task 异常: {e}")
                break
    finally:
        logger.info(f"📤 push_task 结束: session={session_id}")


async def _stream_agent(websocket, stream_input, config):
    full_reply = ""
    interrupted = False
    before_model_reply = ""

    async for chunk in supervisor_agent_module.supervisor_agent.astream(
            stream_input,
            config,
            stream_mode=["messages", "updates"],
    ):
        chunk_type, chunk_data = chunk

        if chunk_type == "messages":
            token, metadata = chunk_data

            # 过滤摘要生成阶段的所有 token
            if metadata.get("langgraph_node") == "SummarizationMiddleware.before_model":
                continue

            # 过滤摘要消息本身
            if getattr(token, 'additional_kwargs', {}).get('lc_source') == 'summarization':
                continue

            if isinstance(token, AIMessageChunk) and token.text:
                await websocket.send_text(json.dumps({
                    "type": "token",
                    "content": token.text,
                }))
                full_reply += token.text

        elif chunk_type == "updates":
            logger.info(f"updates chunk: {str(chunk_data)}")
            for source, update in chunk_data.items():
                if source == "SummarizationMiddleware.before_model":
                    full_reply=""
                    await websocket.send_text(json.dumps({
                        "type": "clear_tokens",
                    }))
                    continue
                if source == "__interrupt__":
                    interrupted = True
                    # 🔥 状态流转: STREAMING → WAITING_APPROVAL
                    thread_id = config["configurable"].get("thread_id", "unknown")
                    await session_manager.set_state(thread_id, SessionState.WAITING_APPROVAL)

                    for itr in update:
                        count = len(itr.value.get("action_requests", []))
                        await websocket.send_text(safe_json_dumps({
                            "type": "interrupt",
                            "interrupt_id": itr.id,
                            "data": itr.value,
                            "action_count": count,
                        }))
                elif source == "check_reject_before_model.before_model":
                    if update is None:
                        continue
                    msgs = update.get("messages", [])
                    for msg in msgs:
                        if isinstance(msg, AIMessage) and msg.content:
                            before_model_reply = msg.content
                            await websocket.send_text(safe_json_dumps({
                                "type": "result",
                                "content": msg.content,
                            }))

    return full_reply or before_model_reply, interrupted


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text(safe_json_dumps({
        "type": "info",
        "content": "✅ 已连接到 AI 助手，请开始对话！"
    }))
    thread_id = "unknown"  # 🔥 初始化默认值

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            if data.get("type") == "ping":
                continue

            trace_id = str(uuid7())
            thread_id = data.get("thread_id", "web_user_001")
            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "user_id": "web_user",
                    "trace_id": trace_id,
                },
                "recursion_limit": 30,
            }
            _trace_id_var.set(trace_id)

            # ===== 获取或创建会话上下文 =====
            ctx = await session_manager.get_or_create(thread_id, websocket)
            ctx.config = config

            # ===== 审批决策 =====
            if data.get("type") == "decision":
                decisions = data.get("decisions", [])
                action_count = data.get("action_count", 1)

                logger.info(f"📩 收到审批决策: {decisions} thread_id={thread_id}")

                # 🔥 状态流转: WAITING_APPROVAL → RESUMED → STREAMING
                await session_manager.set_state(thread_id, SessionState.RESUMED)

                if not decisions:
                    decision = data.get("decision", "approve")
                    decisions = [{"type": decision} for _ in range(action_count)]

                full_reply, interrupted = await _stream_agent(
                    websocket,
                    Command(resume={"decisions": decisions}),
                    config,
                )

                # 🔥 恢复 STREAMING 状态
                await session_manager.set_state(thread_id, SessionState.STREAMING)

                if not interrupted:
                    await save_message(thread_id, "assistant", full_reply)
                    await websocket.send_text(safe_json_dumps({"type": "done"}))
                    # 🔥 状态流转: STREAMING → DONE
                    await session_manager.set_state(thread_id, SessionState.DONE)
                continue

            # ===== 普通消息 =====
            user_message = data.get("message", "")
            if not user_message.strip():
                continue

            logger.info(f"📩 收到用户消息: {user_message} thread_id={thread_id}")

            await create_session(thread_id, user_id="web_user")
            await save_message(thread_id, "user", user_message)
            await websocket.send_text(safe_json_dumps({
                "type": "status",
                "content": "🤔 正在处理中..."
            }))

            # ===== 启动 push_task（会话级别） =====
            # 如果已有 push_task，先取消旧的
            if ctx.push_task and not ctx.push_task.done():
                ctx.push_task.cancel()
                try:
                    await ctx.push_task
                except asyncio.CancelledError:
                    pass

            # 🔥 启动新的 push_task
            ctx.push_task = asyncio.create_task(
                _push_tool_status(thread_id, websocket)
            )

            # 🔥 设置状态为 STREAMING
            await session_manager.set_state(thread_id, SessionState.STREAMING)

            full_reply = ""
            interrupted = False

            try:
                if user_message == "/approve":
                    stream_input = Command(resume={"decisions": [{"type": "approve"}]})
                elif user_message == "/reject":
                    stream_input = Command(resume={"decisions": [{"type": "reject"}]})
                else:
                    stream_input = {"messages": [{"role": "user", "content": user_message}]}

                full_reply, interrupted = await _stream_agent(websocket, stream_input, config)

                # 🔥 检查是否有中断
                if interrupted:
                    # 状态已经是 WAITING_APPROVAL（在 _stream_agent 中设置）
                    logger.info(f"⏸️ 流程中断，等待审批: {thread_id}")
                    # 不关闭 push_task，等待审批
                else:
                    # 没有中断，流程正常结束
                    await session_manager.set_state(thread_id, SessionState.DONE)

                    if full_reply:
                        logger.info(f"📤 Agent 回复: {full_reply[:100]}...")
                        await save_message(thread_id, "assistant", full_reply)
                        await websocket.send_text(safe_json_dumps({"type": "done"}))

            finally:
                # 🔥 只在 DONE 状态时才清理 push_task
                current_ctx = await session_manager.get(thread_id)
                if current_ctx and current_ctx.state == SessionState.DONE:
                    if ctx.push_task and not ctx.push_task.done():
                        ctx.push_task.cancel()
                        try:
                            await ctx.push_task
                        except asyncio.CancelledError:
                            pass
                    # 清空队列
                    while not ctx.queue.empty():
                        try:
                            msg = ctx.queue.get_nowait()
                            await websocket.send_text(safe_json_dumps(msg))
                        except asyncio.QueueEmpty:
                            break
                    logger.info(f"📤 清理完成: {thread_id}")

    except WebSocketDisconnect:
        logger.info(f"🔴 客户端已断开连接: {thread_id}")
        # 清理会话
        await session_manager.cleanup(thread_id)
    except Exception as e:
        logger.error(f"💥 WebSocket 异常: {e}")
        try:
            await websocket.send_text(safe_json_dumps({
                "type": "error",
                "content": f"系统异常: {str(e)}",
            }))
        except Exception:
            pass