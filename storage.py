import logging
import asyncio

import redis.asyncio as aioredis
from langgraph.checkpoint.redis import AsyncRedisSaver
from langgraph.store.postgres import AsyncPostgresStore

from config import REDIS_URI, DB_VECTOR

logger = logging.getLogger(__name__)

_checkpointer_cm = None
_store_cm = None
checkpointer = None
store = None
r = None


async def init_storage():
    global _checkpointer_cm, _store_cm, checkpointer, store, r

    logger.info("🔌 正在连接 Redis...")
    r = aioredis.Redis.from_url(REDIS_URI, decode_responses=True)

    _checkpointer_cm = AsyncRedisSaver.from_conn_string(REDIS_URI)
    checkpointer = await _checkpointer_cm.__aenter__()
    await checkpointer.asetup()
    logger.info(f"✅ Redis checkpointer 初始化完成: {checkpointer}")

    logger.info("🔌 正在连接 PostgreSQL...")
    _store_cm = AsyncPostgresStore.from_conn_string(DB_VECTOR)
    store = await _store_cm.__aenter__()
    await store.setup()
    logger.info(f"✅ PostgreSQL store 初始化完成: {store}")


async def close_storage():
    logger.info("🛑 正在关闭 Redis checkpointer...")
    if _checkpointer_cm:
        await _checkpointer_cm.__aexit__(None, None, None)
        logger.info("✅ Redis checkpointer 已关闭")

    logger.info("🛑 正在关闭 PostgreSQL store...")
    if _store_cm:
        await _store_cm.__aexit__(None, None, None)
        logger.info("✅ PostgreSQL store 已关闭")