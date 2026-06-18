# ============================================================
# 📌 开发过程中的概念验证文件
# 用途：旧版单文件 Agent 原型 — 最早的 Agent 编排思路
#       后续拆分为 agents/ + tools/ + middleware.py 等模块
# 状态：保留作思路参考，不影响主程序运行
# ============================================================
from functools import wraps

import requests
import os
import dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, wrap_tool_call, SummarizationMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.messages import ToolMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.prebuilt import ToolRuntime
from langgraph.store.memory import InMemoryStore
from email.mime.text import MIMEText
from email.utils import formataddr
import smtplib
from datetime import datetime, timezone, timedelta
import time
from langgraph.types import Command
import logging
from pathlib import Path
from langchain_core.utils.uuid import uuid7

import contextvars


#todo
# 未来计划：
# - Redis 分布式幂等
# - 异步服务化
# - 监控面板
# - 消息队列削峰
_trace_id_var = contextvars.ContextVar("trace_id", default="no-trace")

class TraceIdFilter(logging.Filter):
    def filter(self, record):
        record.trace_id = _trace_id_var.get()
        return True

# 不用 basicConfig，手动配置
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] trace_id=%(trace_id)s %(name)s - %(message)s"
))
handler.addFilter(TraceIdFilter())  # Filter 加在 handler 上

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(handler)

logger = logging.getLogger(__name__)
dotenv.load_dotenv(Path(__file__).parent / ".env")
# 启动时校验必要的环境变量
_required = ["OPENAI_BASE_URL", "OPENAI_API_KEY", "EMAIL_SENDER",
             "EMAIL_PASSWORD", "SHARE_CALENDER", "CALENDER_BOT_APP_SECRET"]
_missing = [k for k in _required if not os.getenv(k)]
if _missing:
    raise RuntimeError(f"缺少必要的环境变量：{', '.join(_missing)}")
model = init_chat_model(
    base_url=os.getenv("OPENAI_BASE_URL"),
    api_key=os.getenv("OPENAI_API_KEY"),
    model_provider="openai",
    model="GLM-4.5-Flash",
    profile={"max_input_tokens": 128000},
    temperature=0.1,
    timeout=120,
)
store = InMemoryStore()
# os.environ["LANGSMITH_TRACING"] = os.getenv("LANGSMITH_TRACING")
# os.environ["LANGSMITH_API_KEY"] = os.getenv("LANGSMITH_API_KEY")

_token_cache = {
    "token": None,
    "expire_at": 0
}
EVENT_STORE = {}
class BusinessError(Exception):
    """飞书业务级失败，返回给 LLM 处理，不缓存成功"""
    pass
class FatalError(Exception):
    """llm修不好只能返回给人工"""
    pass
def idempotent(key_func):
    """幂等装饰器：自动处理 查幂等表 → 执行 → 存结果 的完整流程"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            event_key = key_func(*args, **kwargs)
            # 直接从 kwargs 拿 runtime
            runtime = kwargs.get("runtime")
            tool_name = func.__name__
            trace_id = runtime.config["configurable"].get("trace_id") if runtime else "no-trace"
            logger.info(f"[{tool_name}] 开始执行 event_key={event_key}")

            # 查幂等表
            if event_key in EVENT_STORE:
                cached = EVENT_STORE[event_key]
                if cached["status"] == "done":
                    logger.info(f"[{tool_name}] 幂等命中 event_key={event_key}")
                    return cached["result"]
                elif cached["status"] == "running":
                    now = datetime.now(timezone.utc).timestamp()
                    running_seconds=now - cached["timestamp"]
                    # 任务还在执行中
                    if running_seconds < 180:
                        logger.warning(
                            f"[{tool_name}] 重复执行检测 event_key={event_key}"
                        )
                        raise BusinessError(f"trace_id={trace_id} 该请求正在处理中，请稍后重试")
                    # running 超时
                    logger.warning(
                        f" [{tool_name}] event_key={event_key} "
                        f"运行超时 {running_seconds:.1f}s，认为旧任务失效"
                    )
                    del EVENT_STORE[event_key]
                elif cached["status"] == "failed":
                    logger.info(f" [{tool_name}] 上次失败，重新执行 event_key={event_key}")

            # 标记执行中
            EVENT_STORE[event_key] = {"status": "running","timestamp": datetime.now(timezone.utc).timestamp()}
            logger.info(f"[{tool_name}] 开始执行 event_key={event_key}")

            try:
                result = func(*args, **kwargs)
                EVENT_STORE[event_key] = {"status": "done", "result": result}
                logger.info(f"[{tool_name}] 执行成功 event_key={event_key}")
                return result
            except BusinessError as e:
                EVENT_STORE[event_key] = {"status": "failed"}
                logger.warning(f" [{tool_name}] 业务失败 event_key={event_key} error={e}")
                return str(e)
            except Exception as e:
                EVENT_STORE[event_key] = {"status": "failed"}
                logger.error(f" [{tool_name}] 系统异常 event_key={event_key} error={e}")
                raise

        return wrapper
    return decorator


import hashlib

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

def generate_email_event_key(*args, **kwargs):
    """生成email_event_key"""
    subject = kwargs.get("subject")
    to = kwargs.get("to")
    cc = kwargs.get("cc", [])
    body = kwargs.get("body")
    runtime = kwargs.get("runtime")

    trace_id = runtime.config["configurable"].get("trace_id")
    user_id = runtime.config["configurable"].get("user_id", "default")

    to_sorted = sorted(to) if to else []
    cc_sorted = sorted(cc) if cc else []

    raw = f"""
    email_event:
    {user_id}:
    {to_sorted}:
    {cc_sorted}:
    {subject}:
    {body}
    """

    key = hashlib.md5(raw.encode()).hexdigest()
    logger.info(f"[email_event幂等Key] raw={raw[:50]}... hash={key}")

    return key


def get_tenant_access_token(app_id, app_secret):
    """获取飞书Token"""
    now = time.time()
    # token 还有超过5分钟有效期，直接用缓存
    if _token_cache["token"] and _token_cache["expire_at"] - now > 300:
        logger.debug(f"[飞书Token] 命中缓存，剩余 {_token_cache['expire_at'] - now:.0f} 秒")
        return _token_cache["token"]

    logger.info("[飞书日历机器人Token] 缓存过期，重新获取...")
    try:
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        response = requests.post(
            url,
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=10  # 加个超时防止无限等待
        )
        response.raise_for_status()  # HTTP错误(4xx,5xx)抛异常
        data = response.json()

        _token_cache["token"] = data["tenant_access_token"]
        _token_cache["expire_at"] = now + data.get("expire", 7200)

        logger.info(f"[飞书Token] 获取成功，有效期 {data.get('expire', 7200)} 秒")
        return _token_cache["token"]

    except requests.exceptions.RequestException as e:
        logger.error(f"[飞书Token] 网络请求失败: {e}")
        raise  # 重新抛出，让中间件重试
    except KeyError as e:
        logger.error(f"[飞书Token] 响应格式异常，缺少字段: {e}, 原始响应: {data if 'data' in dir() else 'N/A'}")
        raise
    except Exception as e:
        logger.error(f"[飞书Token] 未知错误: {e}")
        raise

@wrap_tool_call
def handle_tool_errors(request, handler):
    """处理工具执行错误，带指数退避重试"""
    runtime = request.runtime
    trace_id = runtime.config["configurable"]["trace_id"]
    logger.info(f" handle_tool_errors中间件调用")
    max_retries = 2
    last_error = None
    base_delay = 1  # 基础等待秒数


    for attempt in range(max_retries + 1):
        try:
            return handler(request)
        except GraphInterrupt:
            # 🚨 关键：如果是人工审批触发的中断，绝不拦截，直接向上抛出！
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
            last_error = e
            if attempt < max_retries:
                wait_time = base_delay * (2 ** attempt)  # 1s, 2s, 4s...
                logger.info(f"第{attempt + 1}次重试，等待 {wait_time} 秒...")
                time.sleep(wait_time)  # ✅ 非阻塞

    logger.info(f"工具执行失败（已重试{max_retries}次）：{last_error}")
    return ToolMessage(
        content=f"工具执行失败（已重试{max_retries}次）：{last_error}",
        tool_call_id=request.tool_call["id"],
    )
@tool
def get_current_datetime() -> str:
    """获取当前日期和时间，返回 ISO 格式时间字符串"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@tool
@idempotent(generate_calender_event_key)
def create_calendar_event(
        title: str,
        description: str,
        start_time: str,
        end_time: str,
        runtime:ToolRuntime,
        location: str = ""
) -> str:
    """创建飞书日历事件，时间格式：2024-01-15 14:00:00"""
    # user_id = runtime.config["configurable"].get("user_id", "default")
    # event_key=generate_calender_event_key(user_id, title, start_time, end_time)
    #
    # # 查幂等表
    # if event_key in EVENT_STORE:
    #     cached = EVENT_STORE[event_key]
    #     if cached["status"] == "done":
    #         print(f"幂等命中，直接返回缓存: {event_key}")
    #         return cached["result"]
    #
    # # 标记执行中
    # EVENT_STORE[event_key] = {"status": "running"}
    trace_id = runtime.config["configurable"].get("trace_id")
    logger.info(f"create_calendar_event工具调用...")
    #print(runtime)

    CALENDER_BOT_APP_SECRET = os.getenv("CALENDER_BOT_APP_SECRET")
    SHARE_CALENDER=os.getenv("SHARE_CALENDER")
    if not CALENDER_BOT_APP_SECRET or not SHARE_CALENDER:
        raise RuntimeError(f"trace_id={trace_id} 缺少必要的环境变量：CALENDER_BOT_APP_SECRET 或 SHARE_CALENDER")


    bot_token = get_tenant_access_token("cli_aa810e229cf8dbc8",CALENDER_BOT_APP_SECRET)
    if not bot_token:
        raise FatalError(f"trace_id={trace_id}  token 获取失败")
    calendar_id = SHARE_CALENDER
    # if not bot_token or not calendar_id:
    #     raise ValueError("环境变量 CALENDER_BOT_TOKEN机器人令牌 或 SHARE_CALENDER共享日历 未配置")

    try:
        start_obj = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        start_ts = int(start_obj.timestamp())
        end_ts = int(datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S").timestamp())

        #拿到时：分，给空闲时间比对
        target_time_hm = start_obj.strftime("%H:%M")
    except ValueError:
        raise BusinessError(f"trace_id={trace_id} 时间格式错误，请使用：2024-01-15 14:00:00，收到的值：start={start_time}, end={end_time}")
    # 动态获取非空闲时间 (从 Runtime 状态中提取)
    busy_slots = []
    messages = runtime.state.get("messages", [])
    for msg in reversed(messages):
        if msg.type == "tool" and getattr(msg, "name", "") == "get_not_available_time_slots":
            try:
                # 因为工具返回的是字符串形式的列表，比如 '["09:00", "14:00", "16:00"]'
                # 我们用 json.loads 把它安全地还原成 Python 的真正的 list
                import json
                busy_slots = json.loads(msg.content)
                logger.info(f"🛡️ 代码网关：成功从上下文捞出忙碌时段: {busy_slots}")
                break
            except Exception:
                pass
    # ==================== 3. 确定性的硬编码 IF 拦截 ====================
    if target_time_hm in busy_slots:
        logger.warning(
            f"🛑 [代码网关拦截] 检测到时间冲突！目标时间 {target_time_hm} 在忙碌列表中！")
        # 抛出业务错误，交给中间件 return 给大模型，强迫子 Agent 承认失败！
        raise BusinessError(f"创建日程失败：时间段 {target_time_hm} 已被占用，请更换其他时间开会。")

    data = {
        "summary": title,
        "description": description,
        "start_time": {"timestamp": str(start_ts), "timezone": "Asia/Shanghai"},
        "end_time": {"timestamp": str(end_ts), "timezone": "Asia/Shanghai"},
        "visibility": "public",
        **({"location": {"name": location}} if location else {})
    }

    # 系统级错误直接抛出，让中间件处理重试
    response = requests.post(
        f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events",
        json=data,
        headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
        timeout=30
    )
    response.raise_for_status()
    result = response.json()

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



@tool
@idempotent(generate_email_event_key)
def send_email(
    to: list[str],             # 收件人邮箱地址列表
    subject: str,              # 邮件主题
    body: str,                 # 邮件正文
    runtime: ToolRuntime,
    cc: list[str] = []         # 抄送人邮箱地址列表（可选）
) -> str:
    """通过邮件API发送邮件。需要正确格式的邮箱地址。"""
    # 占位实现：实际使用时，这里会调用 SendGrid、Gmail API 等
    # 1. 读取配置
    trace_id = runtime.config["configurable"].get("trace_id")
    sender = os.getenv("EMAIL_SENDER")  # 发件人QQ邮箱
    password = os.getenv("EMAIL_PASSWORD")  # QQ邮箱授权码
    if sender is None or password is None:
        raise FatalError(f"trace_id={trace_id} 缺少必要的环境变量：EMAIL_SENDER 或 EMAIL_PASSWORD")
    # 2. 构建邮件内容
    msg = MIMEText(body, "plain", "utf-8")  # 正文：纯文本，UTF-8编码
    msg["From"] = formataddr(["Agent助手", sender])  # 发件人：昵称 + 邮箱
    msg["To"] = ", ".join(to)  # 收件人
    msg["Subject"] = subject  # 主题
    if cc:
        msg["Cc"] = ", ".join(cc)  # 抄送（如有）
        # 3. 合并所有收件人地址（收件人 + 抄送）
    all_recipients = to + cc
    try:
        # 4. 连接QQ邮箱SMTP服务器（SSL加密，端口465）
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(sender, password)  # 登录（用授权码）
        server.sendmail(sender, all_recipients, msg.as_string())  # 发送
        server.quit()  # 断开连接
        return f"trace_id={trace_id} 邮件已发送 - 主题：{subject}，收件人：{', '.join(to)}"

    except smtplib.SMTPAuthenticationError:
        raise FatalError(f"trace_id={trace_id} 邮件发送失败：QQ邮箱认证失败，请检查授权码是否正确")
    except smtplib.SMTPException as e:
        raise BusinessError(f"trace_id={trace_id} 邮件发送失败：{e}")

@tool
def get_not_available_time_slots(
    attendees: list[str] = [],          # 参会者邮箱地址列表（可选，为空时查所有人的空闲）
    date: str = "",                      # 查询日期，ISO格式："2024-01-15"（可选，为空时查今天）
    duration_minutes: int = 60           # 会议时长/分钟（可选，默认60分钟）
) -> list[str]:
    """查询用户的非空闲时段。这些时段已被占用，不能创建新日程。"""
    # 占位实现：实际使用时，这里会查询日历API
    logger.info("调用获取非空闲时间tool...")
    return ["09:00", "14:00", "16:00"]

CALENDAR_AGENT_PROMPT = (
    "Before scheduling, always call get_current_datetime to know today's date. "
    "You are a calendar scheduling assistant. "
    "ALWAYS call get_not_available_time_slots first to check if the requested time slot is inside the non-available list.\n"
    "you MUST STOP IMMEDIATELY. DO NOT call create_calendar_event. "
    "Directly reply: 'ERROR: Time slot 14:00 is already occupied.'"
)

calendar_agent = create_agent(
    model,
    tools=[create_calendar_event, get_not_available_time_slots,get_current_datetime],
    system_prompt=CALENDAR_AGENT_PROMPT,
    middleware=[
        handle_tool_errors,
        HumanInTheLoopMiddleware(
            interrupt_on={
                "create_calendar_event": True,
                "get_not_available_time_slots": True,
                "get_current_datetime":False},
            description_prefix="calendar_agent的HITL等待批准..."
        )
    ],
    store=store,
    checkpointer=InMemorySaver(),
)

EMAIL_AGENT_PROMPT = (
    "You are an email assistant. "
    "Compose professional emails based on natural language requests. "
    "Extract recipient information and craft appropriate subject lines and body text. "
    "Use send_email to send the message. "
    "Always confirm what was sent in your final response."
)

email_agent = create_agent(
    model,
    tools=[send_email],
    middleware=[
        handle_tool_errors,
        HumanInTheLoopMiddleware(
            interrupt_on={"send_email": True},
            description_prefix="email_agent邮件事件的HITL等待批准...",
        ),

    ],
    system_prompt=EMAIL_AGENT_PROMPT,
    store=store,
    checkpointer=InMemorySaver(),
)
# query = "下周一凌晨2点安排一场1小时的睡觉大赛，描述是看看谁还没睡"
# # 用户用自然语言说了一个日程安排请求
#
# for step in calendar_agent.stream(
#     {"messages": [{"role": "user", "content": query}]}
# ):
#     for update in step.values():
#         for message in update.get("messages", []):
#             message.pretty_print()
# query = "给设计团队发送一封提醒邮件，让他们审阅新的设计稿，收件人邮箱412600993@qq.com"
#
# for step in email_agent.stream(
#     {"messages": [{"role": "user", "content": query}]}
# ):
#     for update in step.values():
#         for message in update.get("messages", []):
#             message.pretty_print()
@tool
def schedule_event(request: str, runtime: ToolRuntime) -> str:
    """用自然语言安排日程。

    当用户想要创建、修改或查看日历约会时使用此工具。
    处理日期/时间解析、空闲时段检查和事件创建。

    输入：自然语言日程请求（例如："下周二下午2点与设计团队开会"）
    """
    messages = runtime.state.get("messages", [])

    summary_message = next(
        (msg for msg in messages if getattr(msg, 'additional_kwargs', {}).get('lc_source') == 'summarization'),
        None
    )

    if summary_message:
        logger.info("📝 摘要内容(注入子agent上下文)")
        prompt = (
            "You are a calendar scheduling assistant. "
            "You ONLY handle calendar and scheduling tasks. "
            "Ignore any email or communication requests.\n\n"
            "You are assisting with the following user inquiry:\n\n"
            f"{summary_message.content}\n\n"
            "You are tasked with the following sub-request:\n\n"
            f"{request}"
        )
    else:
        logger.info("⚠️ 没找到摘要消息")
        original_user_message = next(
            message for message in runtime.state["messages"]
            if isinstance(message, HumanMessage)
        )
        prompt = (
            "You are a calendar scheduling assistant. "
            "You ONLY handle calendar and scheduling tasks. "
            "Ignore any email or communication requests.\n\n"
            "For context, the user's original request was:\n"
            f"{original_user_message.content}\n\n"
            "Your specific task is:\n"
            f"{request}"
        )

    result = calendar_agent.invoke(
        {
            "messages": [{"role": "user", "content": prompt}],
            },config=runtime.config,
    )

    # 1. 检查子 Agent 在最后一步到底调了哪些工具
    # 我们可以通过查看最后一条 AI 消息里是否包含 create_calendar_event 的 tool_calls
    last_ai_msg = next(
        (m for m in reversed(result["messages"]) if m.type == "ai"),
        None
    )

    # 2. 如果最后没有调用任何工具，或者调用的工具里没有 create_calendar_event
    has_created = False
    if last_ai_msg and getattr(last_ai_msg, "tool_calls", None):
        has_created = any(tc["name"] == "create_calendar_event" for tc in last_ai_msg.tool_calls)

    # 3. 提取所有的工具执行原始返回
    tool_msgs = [m.content for m in result["messages"] if isinstance(m, ToolMessage)]
    raw_tool_output = "\n".join(tool_msgs)

    # if not has_created:
    #     # 🚨 强行阻断！明确告诉主 Agent：因为时间冲突，日程根本没有创建！
    #     return (
    #         f"❌ 日程安排失败！\n"
    #         f"原因：所选时间冲突或不可用。\n"
    #         f"日历检查流水：\n{raw_tool_output}\n"
    #         f"请告知用户时间冲突，并让用户重新选择时间。"
    #     )

    # 如果成功创建了，再返回正常的流水
    return raw_tool_output


@tool
def manage_email(request: str,runtime:ToolRuntime) -> str:
    """用自然语言发送邮件。

    当用户想要发送通知、提醒或任何邮件通信时使用此工具。
    处理收件人提取、主题生成和邮件撰写。

    输入：自然语言邮件请求（例如："给他们发送一封关于会议的提醒邮件"）
    """
    trace_id = runtime.config["configurable"].get("trace_id")
    logger.info(f"manage_email 被调用")

    result = email_agent.invoke({
        "messages": [{"role": "user", "content": request}]
    },config=runtime.config)
    # Option 1: Return just the confirmation message
    return result["messages"][-1].content
    # Option 2: Return structured data
    # return json.dumps({
    #     "status": "success",
    #     "event_id": "evt_123",
    #     "summary": result["messages"][-1].text
    # })


SUPERVISOR_PROMPT = (
    "You are a helpful personal assistant. "
    "You can schedule calendar events and send emails. "
    "Break down user requests into appropriate tool calls and coordinate the results. "
    "When a request involves multiple actions, use multiple tools in sequence."
)

supervisor_agent = create_agent(
    model,
    tools=[schedule_event, manage_email],
    middleware=[handle_tool_errors,
                SummarizationMiddleware(
                    model=model,
                    #满足到达模型最大输入 token 的 20 % 或 到达 100 个消息任一条件时触发汇总
                    trigger=[("fraction", 0.2), ("messages", 100)],
                    keep=("messages",60),
                ),
                HumanInTheLoopMiddleware(
                    interrupt_on={"schedule_event": True, "manage_email": True},
                    description_prefix="主agent的HITL..."
                )
    ],
    checkpointer=InMemorySaver(),
    system_prompt=SUPERVISOR_PROMPT,
)

if __name__ == "__main__":
    user_request = (
        "安排一场会议，明天14点，和财务团队，时长1小时，会议主题财务会议，描述提交新的财务报表，地点在311会议室。"
        "同时给他们发一封提醒邮件，让他们赶快提交新的财务报表。收件邮箱是412600993@qq.com"
    )

    config = {"configurable": {"thread_id": "8", "user_id": "user_123", "trace_id": str(uuid7())}}
    _trace_id_var.set(config["configurable"]["trace_id"])

    print(f"🚀 开始测试多级智能体系统，Trace ID: {config['configurable']['trace_id']}")
    print(f"原始请求: {user_request}\n" + "=" * 60)

    # 初始状态：第一次启动输入原始消息
    current_input = {"messages": [{"role": "user", "content": user_request}]}

    while True:
        interrupts = []

        # 执行图流
        for step in supervisor_agent.stream(current_input, config):
            for update in step.values():
                if update is None:
                    continue
                if isinstance(update, dict):
                    # 打印正常消息流
                    for message in update.get("messages", []):
                        message.pretty_print()
                else:
                    # 捕获到了中断信号（可能是主 Agent 的，也可能是子 Agent 的）
                    interrupt_ = update[0]
                    interrupts.append(interrupt_)
                    print(f"\n🛑 【系统触发中断】 中断 ID: {interrupt_.id}")

        # 如果运行结束且没有任何中断，说明整个多 Agent 链路彻底走完
        if not interrupts:
            print("\n🎉 所有任务处理完毕，退出工作流。")
            break

        # 统一处理这一轮收集到的所有中断
        print("\n" + "-" * 20 + " 正在处理本轮中断详情 " + "-" * 20)
        resume = {}

        for interrupt_ in interrupts:
            action_requests = interrupt_.value.get("action_requests", [])
            decisions = []

            for request in action_requests:
                tool_name = request["name"]
                description = request.get("description", "无描述")
                args = request.get("args", {})

                print(f"👉 待审批操作 -> 工具: 【{tool_name}】")
                print(f"   描述: {description}")
                print(f"   参数: {args}")

                # ----------- 自动化模拟审批逻辑 -----------
                if tool_name in ["schedule_event", "manage_email","get_not_available_time_slots"]:
                    print(f"   [🟢 自动化审批]：发现主 Agent 工具调用请求【{tool_name}】，自动予以【批准】")
                    decisions.append({"type": "approve"})

                elif tool_name == "create_calendar_event":
                    print(f"   [🟢 自动化审批]：发现子 Agent 敏感动作【创建飞书日程】，自动予以【批准】")
                    decisions.append({"type": "approve"})

                elif tool_name == "send_email":
                    # 演示在子 Agent 拦截时，动态篡改邮件主题！
                    print(f"   [✍️ 自动化改写]：发现子 Agent 敏感动作【发送邮件】")
                    edited_action = request.copy()
                    edited_action["args"]["subject"] = f"【重要提醒】{args.get('subject', '')}"
                    print(f"   [🟢 自动化审批]：已将邮件主题篡改为: {edited_action['args']['subject']}，并予以【放行】")
                    decisions.append({"type": "edit", "edited_action": edited_action})

                else:
                    print(f"   [🔴 自动化拦截]：未知危险操作，自动予以【拒绝】")
                    decisions.append({"type": "reject"})

            # 记录当前中断 ID 的审批决策
            resume[interrupt_.id] = {"decisions": decisions}

        print("-" * 50 + "\n")
        # 下一轮的输入直接变成包含审批决策的 Command 对象
        current_input = Command(resume=resume)
# if __name__ == "__main__":
#     # Example: User request requiring both calendar and email coordination
#     user_request = (
#         "安排一场会议，周三10点，和设计团队，时长1小时，会议主题简短会议，描述提交新的设计稿，地点在311会议室"
#         "同时给他们发一封提醒邮件，让他们赶快提交新的设计稿。收件邮箱是412600993@qq.com"
#     )
#
#     config = {"configurable": {"thread_id": "6","user_id": "user_123","trace_id":str(uuid.uuid4())}}
#     _trace_id_var.set(config["configurable"]["trace_id"])  # ← 加这行
#     interrupts = []
#
#     # 第一步：收集所有中断
#     for step in supervisor_agent.stream(
#             {"messages": [{"role": "user", "content": user_request}]},
#             config,
#     ):
#         for update in step.values():
#             if update is None:
#                 continue
#             if isinstance(update, dict):
#                 for message in update.get("messages", []):
#                     message.pretty_print()
#             else:
#                 interrupt_ = update[0]
#                 interrupts.append(interrupt_)
#                 print(f"\nINTERRUPTED中断: {interrupt_.id}")
#
#     # 第二步：循环结束后，统一查看所有中断详情
#     print("\n" + "=" * 60)
#     print("所有中断详情：")
#     for interrupt_ in interrupts:
#         for request in interrupt_.value["action_requests"]:
#             print(f"中断 ID: {interrupt_.id}")
#             print(f"{request['description']}\n")
#
#     #审批
#     resume={}
#     for interrupt_ in interrupts:
#         # 获取这个中断的所有待审批动作
#         action_requests = interrupt_.value["action_requests"]
#
#         decisions = []
#         for request in action_requests:
#             tool_name = request["name"]
#             if tool_name == "manage_email":
#                 # 编辑邮件：修改主题
#                 # edited_action = request.copy()
#                 # print("edited_action未修改时:")
#                 # print(edited_action)
#                 # edited_action["args"]["subject"] = "oi!！"
#                 # decisions.append({"type": "edit", "edited_action": edited_action})
#                 # print("edited_action修改后:")
#                 # print(edited_action)
#                 decisions.append({"type": "approve"})
#             elif tool_name == "schedule_event":
#                 # 批准创建日历事件
#                 decisions.append({
#                     "type": "approve",
#                 })
#             else:
#                 # 其他工具默认拒绝
#                 decisions.append({"type": "reject"})
#
#             # 把 decisions 按中断 ID 存入 resume 字典
#             resume[interrupt_.id] = {"decisions": decisions}
#
#     interrupts = []
#     for step in supervisor_agent.stream(
#             Command(resume=resume),
#             config,
#     ):
#         for update in step.values():
#             if update is None:
#                 continue
#             if isinstance(update, dict):
#                 for message in update.get("messages", []):
#                     message.pretty_print()
#             else:
#                 interrupt_ = update[0]
#                 interrupts.append(interrupt_)
#                 print(f"\nINTERRUPTED: {interrupt_.id}")
# if __name__ == "__main__":
#     config = {
#         "configurable": {
#             "thread_id": "test-idempotent",
#             "user_id": "user_123",
#             "trace_id": str(uuid.uuid4())
#         }
#     }
#     _trace_id_var.set(config["configurable"]["trace_id"])
#
#     request = "给412600993@qq.com发送邮件，主题：幂等测试，正文：测试幂等性"
#
#     print("\n========== 第一次调用 ==========")
#     result1 = email_agent.invoke(
#         {"messages": [{"role": "user", "content": request}]},
#         config=config
#     )
#     print(result1["messages"][-1].content)
#
#     print("\n========== EVENT_STORE 状态 ==========")
#     for k, v in EVENT_STORE.items():
#         print(f"{k[:16]}... status={v['status']}")
#
#     print("\n========== 第二次调用（测试幂等） ==========")
#     result2 = email_agent.invoke(
#         {"messages": [{"role": "user", "content": request}]},
#         config=config
#     )
#     print(result2["messages"][-1].content)
#
#     print("\n========== 验证：幂等命中应该在日志里出现 ==========")
#     print("看日志里有没有：[send_email] 幂等命中")
