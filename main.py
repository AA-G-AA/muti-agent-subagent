# main.py
# FastAPI 启动入口

import asyncio
from contextlib import asynccontextmanager
import logging
import sys
import agents.supervisor_agent as supervisor_agent_module
from agents.supervisor_agent import init_supervisor_agent
from db import init_mysql, close_mysql, init_tables
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.utils.uuid import uuid7
import uvicorn

from api.chat import router
from api.session import router as session_router
from config import _trace_id_var
import storage


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

print("当前策略:", type(asyncio.get_event_loop_policy()))
print("当前循环:", type(asyncio.get_event_loop()))


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    logger.info("🚀 正在初始化 MySQL...")
    await init_mysql()
    logger.info("✅ MySQL 初始化完成")
    logger.info("🚀 正在初始化存储层...")
    logger.info(f"  checkpointer 初始化前: {storage.checkpointer}")
    logger.info(f"  store 初始化前: {storage.store}")
    await storage.init_storage()
    logger.info(f"  checkpointer 初始化后: {storage.checkpointer}")
    logger.info(f"  store 初始化后: {storage.store}")
    logger.info("✅ 存储层初始化完成")
    logger.info("🚀 正在初始化agent...")
    logger.info(f"  agent 初始化前: {supervisor_agent_module.supervisor_agent}")
    init_supervisor_agent()
    logger.info(f"  agent 初始化后: {supervisor_agent_module.supervisor_agent}")

    yield
    # 关闭时
    logger.info("🛑 正在关闭 MySQL...")
    await close_mysql()
    logger.info("🛑 正在关闭存储层...")
    await storage.close_storage()
    logger.info("✅ 存储层已关闭")

app = FastAPI(title="AI 多 Agent 助手ting", lifespan=lifespan)

# 允许 Vue 前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 导入 WebSocket 路由

app.include_router(router)
app.include_router(session_router)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """HTTP 请求从 X-Trace-Id 头取 trace_id，前端没有则自动生成"""
    trace_id = request.headers.get("X-Trace-Id") or str(uuid7())
    _trace_id_var.set(trace_id)
    response = await call_next(request)
    return response


if __name__ == "__main__":
    config = uvicorn.Config(app, host="0.0.0.0", port=6002, loop="asyncio")
    server = uvicorn.Server(config)
    asyncio.run(server.serve())