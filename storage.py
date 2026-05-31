# storage.py
from langgraph.checkpoint.redis import AsyncRedisSaver
from langgraph.store.postgres import AsyncPostgresStore
from config import REDIS_URI, DB_VECTOR
import redis.asyncio as aioredis

r = aioredis.Redis.from_url(REDIS_URI, decode_responses=True)
checkpointer = None
store = None
async def init_storage():
    global checkpointer_cm, store_cm, checkpointer, store

    checkpointer_cm = AsyncRedisSaver.from_conn_string(REDIS_URI)
    checkpointer = await checkpointer_cm.__aenter__()
    await checkpointer.asetup()

    store_cm = AsyncPostgresStore.from_conn_string(DB_VECTOR)
    store = await store_cm.__aenter__()
    await store.setup()

async def close_storage():
    """程序退出时调用"""
    if checkpointer_cm:
        await checkpointer_cm.__aexit__(None, None, None)
    if store_cm:
        await store_cm.__aexit__(None, None, None)