#utils/feishu.py
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging
import sys
from pathlib import Path


sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import REDIS_URI, _trace_id_var
from storage import r


logger = logging.getLogger(__name__)

@retry(
    stop=stop_after_attempt(3),           # 最多重试3次
    wait=wait_exponential(min=1, max=5),  # 指数退避：1s, 2s, 4s
    retry=retry_if_exception_type(httpx.RequestError),  # 只重试网络错误
    before_sleep=lambda retry_state: logger.warning(
        f"[飞书Token] 网络请求失败，第 {retry_state.attempt_number} 次重试，"
        f"等待 {retry_state.next_action.sleep:.1f}s "
        f"trace_id={_trace_id_var.get()}"
    )
)
async def get_tenant_access_token(app_id, app_secret):
    """获取飞书Token"""
    token =await r.get("feishu_token")

    # token 还有超过5分钟有效期，直接用缓存
    if token:
        ttl=await r.ttl("feishu_token")
        logger.debug(f"[飞书Token] 命中缓存，剩余 {ttl} 秒")
        return token

    logger.info("[飞书日历机器人Token] 缓存过期，重新获取...")
    # 🌟 进阶细节：为了防止高并发下 10 个工具同时刷新 Token 导致击穿飞书限频，
    # 我们可以利用 Redis 的单线程特性加个简易的分布式锁拦截一下
    async with r.lock("lock:refresh_feishu_token",timeout=10):
        # 再次双重检查，防止排队期间前一个线程已经拿到了
        token = await r.get("feishu_token")
        if token:
            return token
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    json={"app_id": app_id, "app_secret": app_secret},
                    timeout=10
                )

                response.raise_for_status()  # HTTP错误(4xx,5xx)抛异常
                data = response.json()

                token = data["tenant_access_token"]
                expire = data.get("expire", 7200)
                await r.setex("feishu_token", expire - 300, token)

                logger.info(f"[飞书Token] 获取成功，有效期 {data.get('expire', 7200)} 秒")
                return token

        except httpx.RequestError as e:
            logger.error(f"[飞书Token] 网络请求失败: {e}")
            raise  # 重新抛出，让中间件重试
        except KeyError as e:
            logger.error(f"[飞书Token] 响应格式异常，缺少字段: {e}, 原始响应: {data if 'data' in dir() else 'N/A'}")
            raise
        except Exception as e:
            logger.error(f"[飞书Token] 未知错误: {e}")
            raise
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=5),
    retry=retry_if_exception_type(httpx.RequestError),
    before_sleep=lambda retry_state: logger.warning(
        f"[飞书创建日程] 网络失败，第{retry_state.attempt_number}次重试 "
        f"trace_id={_trace_id_var.get()}"
    )
)
async def _call_feishu_create_event(bot_token, calendar_id, data):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events",
            json=data,
            headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        return response.json()