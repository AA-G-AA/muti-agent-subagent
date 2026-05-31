#middleware.py
import json
from functools import wraps
from datetime import datetime, timezone, timedelta
import asyncio
import logging

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt

from storage import r
from errors import *


logger = logging.getLogger(__name__)
def idempotent(key_func):
    """异步 Redis 原子幂等装饰器（带自旋排队等待，不浪费 Token）"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            event_key = key_func(*args, **kwargs)
            redis_key = f'idempotent:{event_key}'
            runtime = kwargs.get("runtime")
            tool_name = func.__name__
            trace_id = runtime.config["configurable"].get("trace_id") if runtime else "no-trace"

            logger.info(f"[{tool_name}] 尝试抢锁 redis_key={redis_key}")

            # --------------------------------------------------------
            # 核心改动：一上来就原子抢锁！把判断和写入合为一步,自旋排队大循环（最多等 5 次，每次睡 1 秒）
            # --------------------------------------------------------
            # nx=True: 只有 key 不存在时才能设置成功，返回 True。如果已经存在，直接返回 False。
            # ex=180: 自带 3 分钟超时强行解锁，绝对防止核心业务卡死导致的死锁。
            max_wait_attempts = 5
            lock_success=False
            for attempt in range(max_wait_attempts):
                now_ts = datetime.now(timezone.utc).timestamp()
                # 抢锁
                lock_success = await r.set(
                    redis_key,
                    json.dumps({"status": "running", "timestamp": now_ts}),
                    nx=True,
                    ex=180
                )
                # 情况 B：抢锁成功，直接出循环去执行核心业务
                if lock_success:
                    break

                # --------------------------------------------------------
                # 情况 A：抢锁失败 (lock_success == False)
                # 说明有人在跑，或者已经跑完了。我们进去精细化检查
                # --------------------------------------------------------


                cached_raw = await r.get(redis_key)
                #高并发可能get时,前一个任务就过期了
                # 优化：如果恰好前一个任务过期蒸发了，不直接报错！
                # 原地眯 1 秒，直接通过 continue 进入下一次循环，下一轮直接变成“抢锁成功的开拓者”
                if not cached_raw:
                    if attempt < max_wait_attempts - 1:
                        logger.info(f"[{tool_name}] ⏳ 锁刚好过期，等待下轮重新抢锁...")
                        await asyncio.sleep(1)
                        continue
                    else:
                        raise BusinessError(f"trace_id={trace_id} 锁并发冲突过于剧烈，请稍后重试")
                cached=json.loads(cached_raw)
                status = cached.get("status")
                if status == "done":
                    logger.info(f"[{tool_name}] 🎯 幂等命中，直接返回缓存结果")
                    return cached["result"]

                elif status == "running":
                    # 前一个人还在拼命跑。如果是最后一次尝试了，实在等不到了，才抛错
                    if attempt == max_wait_attempts - 1:
                        logger.warning(f"[{tool_name}] ❌ 彻底超时：重复请求处理中，不再等待")
                        raise BusinessError(f"trace_id={trace_id} 该请求正在处理中，请稍后重试")

                    # 如果还没到最后一次，我们选择“原地 1 秒”，然后自动进入下一次循环去抢锁
                    logger.info(f"[{tool_name}] ⏳ 前置任务运行中，原地排队等待 1 秒... (第 {attempt + 1} 次)")
                    await asyncio.sleep(1)
                    continue

                elif status == "failed":
                    #优化2：合并并理顺failed逻辑
                    # 上次别人失败了，既然我这一轮没抢到当前轮次的锁（说明有别人正在重新冲锋）
                    # 那我也等等看这一轮的新冲锋者能不能成功。如果是最后一次了，直接抛错让大模型重新发起
                    if attempt == max_wait_attempts - 1:
                        logger.warning(f"[{tool_name}] ❌ 拦截：前置任务失败，且排队重试超时")
                        raise BusinessError(f"上次执行失败，且排队超时")
                    logger.info(f"[{tool_name}] ⏳ 发现前置任务曾失败，等待当前并发轮次结果 1 秒...")
                    await asyncio.sleep(1)
                    continue

            # --------------------------------------------------------
            # 情况 B：抢锁成功 (lock_success == True)
            # 全场只有你一个人拿到了特权，开始执行核心业务
            # --------------------------------------------------------
            logger.info(f"[{tool_name}] 🔒 抢锁成功，开始执行业务核心逻辑")
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                await r.set(redis_key, json.dumps({"status": "done", "result": result}), ex=3600)
                logger.info(f"[{tool_name}] ✅ 执行成功，结果已写入缓存")
                return result

            except BusinessError as e:
                # 💡 业务已知异常（比如大模型参数传错了）：冷却 3 秒足够了
                # 方便大模型迅速修正参数后，在下一轮对话里能立刻重新调通工具
                await r.set(redis_key, json.dumps({"status": "failed"}), ex=3)
                logger.warning(f"[{tool_name}] ⚠️ 业务失败: error={e}")
                return str(e)

            except Exception as e:
                #系统未知崩溃（比如断网、第三方服务器宕机）：维持 10 秒
                # 启动长达 5 分钟的熔断保护，防止大模型疯狂轰炸死去的接口
                await r.set(redis_key, json.dumps({"status": "failed"}), ex=10)
                logger.error(f"[{tool_name}] 💥 系统崩溃: error={e}")
                raise

        return wrapper
    return decorator

@wrap_tool_call
async def handle_tool_errors(request, handler):
    """处理工具执行错误，带指数退避重试"""
    runtime = request.runtime
    trace_id = runtime.config["configurable"]["trace_id"]
    logger.info(f" handle_tool_errors中间件调用")

    try:
        return await handler(request)
    except GraphInterrupt:
        # 如果是人工审批触发的中断，绝不拦截，直接向上抛出！
        logger.info(f"检测到 LangGraph 中断信号，放行给主图引擎。")
        raise
    except BusinessError as e:
        #业务错误llm修
        logger.info(f"业务错误：{e}，请修正后重试")
        return ToolMessage(
            content=f"业务错误：{e}，请修正后重试",
            tool_call_id=request.tool_call["id"],
        )
    except FatalError as e:
        #致命错误重试没用 系统配置错误 只能给人工
        logger.error(f"致命错误: {e}")
        return ToolMessage(
            content=(
                f"系统出现致命错误：{e}。\n"
                f"该问题无法自动修复，请联系人工处理。"
            ),
            tool_call_id=request.tool_call["id"],
        )

    except Exception as e:
        logger.error(f"工具执行失败：{e}")
        return ToolMessage(
            content=f"工具执行异常，请检查配置或稍后重试。详情: {str(e)}",
            tool_call_id=request.tool_call["id"],
        )