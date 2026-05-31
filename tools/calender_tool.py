import hashlib
import logging
from datetime import datetime
import json
import os
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from middleware import idempotent
from errors import *
from utils.feishu import _call_feishu_create_event,get_tenant_access_token

logger = logging.getLogger(__name__)



def generate_calender_event_key(*args, **kwargs):
    """生成calender_event_key"""

    title = kwargs.get("title")
    start_time = kwargs.get("start_time")
    end_time = kwargs.get("end_time")
    runtime = kwargs.get("runtime")
    trace_id = runtime.config["configurable"].get("trace_id")
    user_id = runtime.config["configurable"].get(
        "user_id",
        "default"
    )
    raw = f"""
    create_calendar_event:
    {user_id}:
    {title}:
    {start_time}:
    {end_time}
    """

    key = hashlib.md5(raw.encode()).hexdigest()

    logger.info(f" [calender_event幂等Key] raw={raw} hash={key}")

    return key

@tool
def get_current_datetime() -> str:
    """获取当前日期和时间，返回 ISO 格式时间字符串"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@tool
@idempotent(generate_calender_event_key)
async def create_calendar_event(
        title: str,
        description: str,
        start_time: str,
        end_time: str,
        runtime:ToolRuntime,
        location: str = ""
) -> str:
    """创建飞书日历事件，时间格式：2024-01-15 14:00:00"""

    trace_id = runtime.config["configurable"].get("trace_id")
    logger.info(f"create_calendar_event工具调用...")
    #print(runtime)

    CALENDER_BOT_APP_SECRET = os.getenv("CALENDER_BOT_APP_SECRET")
    SHARE_CALENDER=os.getenv("SHARE_CALENDER")
    if not CALENDER_BOT_APP_SECRET or not SHARE_CALENDER:
        raise RuntimeError(f"trace_id={trace_id} 缺少必要的环境变量：CALENDER_BOT_APP_SECRET 或 SHARE_CALENDER")


    bot_token = await get_tenant_access_token("cli_aa810e229cf8dbc8",CALENDER_BOT_APP_SECRET)
    if not bot_token:
        raise FatalError(f"token 获取失败")
    calendar_id = SHARE_CALENDER
    # if not bot_token or not calendar_id:
    #     raise ValueError("环境变量 CALENDER_BOT_TOKEN机器人令牌 或 SHARE_CALENDER共享日历 未配置")
    try:
        start_obj = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        end_obj = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
        start_ts = int(start_obj.timestamp())
        end_ts = int(end_obj.timestamp())

        # 提取当前请求会议的“开始”和“结束”的 分钟数（方便做数字化比对）
        req_start_min = start_obj.hour * 60 + start_obj.minute
        req_end_min = end_obj.hour * 60 + end_obj.minute

    except ValueError:
        raise BusinessError(f"时间格式错误，请使用：2024-01-15 14:00:00，收到的值：start={start_time}, end={end_time}")
    # 动态获取非空闲时间
    busy_slots = await get_not_available_time_slots()
    #用 json.loads 将其还原为真正的 list
    busy_slots = json.loads(busy_slots)
    logger.info(f"获取到非空闲时间：{busy_slots}")
    #messages = runtime.state.get("messages", [])
    # for msg in reversed(messages):
    #     if msg.type == "tool" and getattr(msg, "name", "") == "get_not_available_time_slots":
    #         try:
    #             # 因为工具返回的是字符串形式的列表，比如 '["09:00", "14:00", "16:00"]'
    #             # 我们用 json.loads 把它安全地还原成 Python 的真正的 list
    #             import json
    #             busy_slots = json.loads(msg.content)
    #             logger.info(f"🛡️ 代码网关：成功从上下文捞出忙碌时段: {busy_slots}")
    #             break
    #         except Exception:
    #             pass

    def is_overlapping(req_start, req_end, slot_str):
        try:
            slot_start_str, slot_end_str = slot_str.split("-")
            sh, sm = map(int, slot_start_str.split(":"))
            eh, em = map(int, slot_end_str.split(":"))

            slot_start_min = sh * 60 + sm
            slot_end_min = eh * 60 + em

            # 🌟 核心数学公式：两个区间有交集的充分必要条件
            return max(req_start, slot_start_min) < min(req_end, slot_end_min)
        except Exception:
            return False
    # ==================== 3. 确定性的硬编码 IF 拦截 ====================
    for slot in busy_slots:
        if is_overlapping(req_start_min, req_end_min, slot):
            logger.warning(f"🛑 [代码网关区间拦截] 检测到时间冲突！请求时段与已存在时段 {slot} 发生重叠！")
            raise BusinessError(f"创建日程失败：您选择的时间段与现有会议 {slot} 冲突，请更换时间。")

    data = {
        "summary": title,
        "description": description,
        "start_time": {"timestamp": str(start_ts), "timezone": "Asia/Shanghai"},
        "end_time": {"timestamp": str(end_ts), "timezone": "Asia/Shanghai"},
        "visibility": "public",
        **({"location": {"name": location}} if location else {})
    }

    result = await _call_feishu_create_event(bot_token, calendar_id, data)

    if result.get("code") == 0:
            event = result["data"]["event"]
            result_str=f"trace_id={trace_id} 日程创建成功，标题：{title}，开始时间：{start_time}，链接：{event.get('app_link')}"

            return result_str
    else:
        # 业务失败，返回给 LLM 处理
        error_msg=f"trace_id={trace_id} 创建失败：{result.get('msg')}"
        #业务失败时，存入 status="failed" (这样下次遇到这个key就会重试，而不是直接返回失败)

        # EVENT_STORE[event_key] = {
        #     "status": "failed",
        #     "result": error_msg
        # }
        # return error_msg
        raise BusinessError(error_msg)


async def get_not_available_time_slots(

) -> str:
    """查询某一天的非空闲（已占用）时段。
    返回结果是一个已被占用的时间段列表。你绝对不能在这些时段内安排任何新日程！
    """
    logger.info("调用获取非空闲时间tool...")
    # 🌟 这里的返回带上明确的区间和“被占用”解释
    occupied_slots = ["09:00-10:00", "14:00-15:00", "16:00-17:00"]
    # 🌟 直接返回真正的 JSON 字符串：'["09:00-10:00", "14:00-15:00", "16:00-17:00"]'
    return json.dumps(occupied_slots)
