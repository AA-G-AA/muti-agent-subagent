import json
import sys
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from functools import wraps
import storage
import redis
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
from langgraph.checkpoint.redis import AsyncRedisSaver
import contextvars
from langgraph.store.postgres import AsyncPostgresStore
import asyncio
import httpx
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, retry_if_not_exception_type
from errors import *
from storage import *
from config import _trace_id_var, model
from utils.feishu import _call_feishu_create_event,get_tenant_access_token
logger = logging.getLogger(__name__)



from middleware import idempotent,handle_tool_errors

import hashlib

from tools.email_tool import *
from tools.calender_tool import *
# def generate_calender_event_key(*args, **kwargs):
#     """生成calender_event_key"""
#
#     title = kwargs.get("title")
#     start_time = kwargs.get("start_time")
#     end_time = kwargs.get("end_time")
#     runtime = kwargs.get("runtime")
#     trace_id = runtime.config["configurable"].get("trace_id")
#     user_id = runtime.config["configurable"].get(
#         "user_id",
#         "default"
#     )
#     raw = f"""
#     create_calendar_event:
#     {user_id}:
#     {title}:
#     {start_time}:
#     {end_time}
#     """
#
#     key = hashlib.md5(raw.encode()).hexdigest()
#
#     logger.info(f" [calender_event幂等Key] raw={raw} hash={key}")
#
#     return key
#
# def generate_email_event_key(*args, **kwargs):
#     """生成email_event_key"""
#     subject = kwargs.get("subject")
#     to = kwargs.get("to")
#     cc = kwargs.get("cc", [])
#     body = kwargs.get("body")
#     runtime = kwargs.get("runtime")
#
#     trace_id = runtime.config["configurable"].get("trace_id")
#     user_id = runtime.config["configurable"].get("user_id", "default")
#
#     to_sorted = sorted(to) if to else []
#     cc_sorted = sorted(cc) if cc else []
#
#     raw = f"""
#     email_event:
#     {user_id}:
#     {to_sorted}:
#     {cc_sorted}:
#     {subject}:
#     {body}
#     """
#
#     key = hashlib.md5(raw.encode()).hexdigest()
#     logger.info(f"[email_event幂等Key] raw={raw[:50]}... hash={key}")
#
#     return key



# @tool
# def get_current_datetime() -> str:
#     """获取当前日期和时间，返回 ISO 格式时间字符串"""
#     return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# @tool
# @idempotent(generate_calender_event_key)
# async def create_calendar_event(
#         title: str,
#         description: str,
#         start_time: str,
#         end_time: str,
#         runtime:ToolRuntime,
#         location: str = ""
# ) -> str:
#     """创建飞书日历事件，时间格式：2024-01-15 14:00:00"""
#
#     trace_id = runtime.config["configurable"].get("trace_id")
#     logger.info(f"create_calendar_event工具调用...")
#     #print(runtime)
#
#     CALENDER_BOT_APP_SECRET = os.getenv("CALENDER_BOT_APP_SECRET")
#     SHARE_CALENDER=os.getenv("SHARE_CALENDER")
#     if not CALENDER_BOT_APP_SECRET or not SHARE_CALENDER:
#         raise RuntimeError(f"trace_id={trace_id} 缺少必要的环境变量：CALENDER_BOT_APP_SECRET 或 SHARE_CALENDER")
#
#
#     bot_token = await get_tenant_access_token("cli_aa810e229cf8dbc8",CALENDER_BOT_APP_SECRET)
#     if not bot_token:
#         raise FatalError(f"token 获取失败")
#     calendar_id = SHARE_CALENDER
#     # if not bot_token or not calendar_id:
#     #     raise ValueError("环境变量 CALENDER_BOT_TOKEN机器人令牌 或 SHARE_CALENDER共享日历 未配置")
#     try:
#         start_obj = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
#         start_ts = int(start_obj.timestamp())
#         end_ts = int(datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S").timestamp())
#
#         #拿到时：分，给空闲时间比对
#         target_time_hm = start_obj.strftime("%H:%M")
#     except ValueError:
#         raise BusinessError(f"时间格式错误，请使用：2024-01-15 14:00:00，收到的值：start={start_time}, end={end_time}")
#     # 动态获取非空闲时间 (从 Runtime 状态中提取)
#     busy_slots = []
#     messages = runtime.state.get("messages", [])
#     for msg in reversed(messages):
#         if msg.type == "tool" and getattr(msg, "name", "") == "get_not_available_time_slots":
#             try:
#                 # 因为工具返回的是字符串形式的列表，比如 '["09:00", "14:00", "16:00"]'
#                 # 我们用 json.loads 把它安全地还原成 Python 的真正的 list
#                 import json
#                 busy_slots = json.loads(msg.content)
#                 logger.info(f"🛡️ 代码网关：成功从上下文捞出忙碌时段: {busy_slots}")
#                 break
#             except Exception:
#                 pass
#     # ==================== 3. 确定性的硬编码 IF 拦截 ====================
#     if target_time_hm in busy_slots:
#         logger.warning(
#             f"🛑 [代码网关拦截] 检测到时间冲突！目标时间 {target_time_hm} 在忙碌列表中！")
#         # 抛出业务错误，交给中间件 return 给大模型，强迫子 Agent 承认失败！
#         raise BusinessError(f"创建日程失败：时间段 {target_time_hm} 已被占用，请更换其他时间开会。")
#
#     data = {
#         "summary": title,
#         "description": description,
#         "start_time": {"timestamp": str(start_ts), "timezone": "Asia/Shanghai"},
#         "end_time": {"timestamp": str(end_ts), "timezone": "Asia/Shanghai"},
#         "visibility": "public",
#         **({"location": {"name": location}} if location else {})
#     }
#
#     result = await _call_feishu_create_event(bot_token, calendar_id, data)
#
#     if result.get("code") == 0:
#             event = result["data"]["event"]
#             result_str=f"trace_id={trace_id} 日程创建成功，标题：{title}，开始时间：{start_time}，链接：{event.get('app_link')}"
#
#             return result_str
#     else:
#         # 业务失败，返回给 LLM 处理
#         error_msg=f"trace_id={trace_id} 创建失败：{result.get('msg')}"
#         #业务失败时，存入 status="failed" (这样下次遇到这个key就会重试，而不是直接返回失败)
#
#         # EVENT_STORE[event_key] = {
#         #     "status": "failed",
#         #     "result": error_msg
#         # }
#         # return error_msg
#         raise BusinessError(error_msg)

async def main():

    # CALENDAR_AGENT_PROMPT = (
    #     "Before scheduling, always call get_current_datetime to know today's date. "
    #     "You are a calendar scheduling assistant. "
    #     "ALWAYS call get_not_available_time_slots first to check if the requested time slot is inside the non-available list.\n"
    #     "you MUST STOP IMMEDIATELY. DO NOT call create_calendar_event. "
    #     "Directly reply: 'ERROR: Time slot 14:00 is already occupied.'"
    # )
    #
    # calendar_agent = create_agent(
    #     model,
    #     tools=[create_calendar_event, get_not_available_time_slots, get_current_datetime],
    #     system_prompt=CALENDAR_AGENT_PROMPT,
    #     middleware=[
    #         handle_tool_errors,
    #
    #     ],
    #     store=storage.store,
    #     checkpointer=None,
    # )
    from agents.supervisor_agent import supervisor_agent

    # @tool
    # async def schedule_event(request: str, runtime: ToolRuntime) -> str:
    #     """用自然语言安排日程。
    #
    #     当用户想要创建、修改或查看日历约会时使用此工具。
    #     处理日期/时间解析、空闲时段检查和事件创建。
    #
    #     输入：自然语言日程请求（例如："下周二下午2点与设计团队开会"）
    #     """
    #     messages = runtime.state.get("messages", [])
    #
    #     summary_message = next(
    #         (msg for msg in messages if getattr(msg, 'additional_kwargs', {}).get('lc_source') == 'summarization'),
    #         None
    #     )
    #
    #     if summary_message:
    #         logger.info("📝 摘要内容(注入子agent上下文)")
    #         prompt = (
    #             "You are a calendar scheduling assistant. "
    #             "You ONLY handle calendar and scheduling tasks. "
    #             "Ignore any email or communication requests.\n\n"
    #             "You are assisting with the following user inquiry:\n\n"
    #             f"{summary_message.content}\n\n"
    #             "You are tasked with the following sub-request:\n\n"
    #             f"{request}"
    #         )
    #     else:
    #         logger.info("⚠️ 没找到摘要消息")
    #         original_user_message = next(
    #             message for message in runtime.state["messages"]
    #             if isinstance(message, HumanMessage)
    #         )
    #         prompt = (
    #             "You are a calendar scheduling assistant. "
    #             "You ONLY handle calendar and scheduling tasks. "
    #             "Ignore any email or communication requests.\n\n"
    #             "For context, the user's original request was:\n"
    #             f"{original_user_message.content}\n\n"
    #             "Your specific task is:\n"
    #             f"{request}"
    #         )
    #
    #     result = await calendar_agent.ainvoke(
    #         {
    #             "messages": [{"role": "user", "content": prompt}],
    #         }, config=runtime.config,
    #     )
    #
    #     # 1. 检查子 Agent 在最后一步到底调了哪些工具
    #     # 我们可以通过查看最后一条 AI 消息里是否包含 create_calendar_event 的 tool_calls
    #     last_ai_msg = next(
    #         (m for m in reversed(result["messages"]) if m.type == "ai"),
    #         None
    #     )
    #     # 2. 如果最后没有调用任何工具，或者调用的工具里没有 create_calendar_event
    #     has_created = False
    #     if last_ai_msg and getattr(last_ai_msg, "tool_calls", None):
    #         has_created = any(tc["name"] == "create_calendar_event" for tc in last_ai_msg.tool_calls)
    #     # 3. 提取所有的工具执行原始返回
    #     tool_msgs = [m.content for m in result["messages"] if isinstance(m, ToolMessage)]
    #     raw_tool_output = "\n".join(tool_msgs)
    #
    #     # if not has_created:
    #     #     # 🚨 强行阻断！明确告诉主 Agent：因为时间冲突，日程根本没有创建！
    #     #     return (
    #     #         f"❌ 日程安排失败！\n"
    #     #         f"原因：所选时间冲突或不可用。\n"
    #     #         f"日历检查流水：\n{raw_tool_output}\n"
    #     #         f"请告知用户时间冲突，并让用户重新选择时间。"
    #     #     )
    #
    #     # 如果成功创建了，再返回正常的流水
    #     return raw_tool_output
    #
    # @tool
    # async def manage_email(request: str, runtime: ToolRuntime) -> str:
    #     """用自然语言发送邮件。
    #
    #     当用户想要发送通知、提醒或任何邮件通信时使用此工具。
    #     处理收件人提取、主题生成和邮件撰写。
    #
    #     输入：自然语言邮件请求（例如："给他们发送一封关于会议的提醒邮件"）
    #     """
    #     trace_id = runtime.config["configurable"].get("trace_id")
    #     logger.info(f"manage_email 被调用")
    #
    #     result = await email_agent.ainvoke({
    #         "messages": [{"role": "user", "content": request}]
    #     }, config=runtime.config)
    #     # Option 1: Return just the confirmation message
    #     return result["messages"][-1].content
    #     # Option 2: Return structured data
    #     # return json.dumps({
    #     #     "status": "success",
    #     #     "event_id": "evt_123",
    #     #     "summary": result["messages"][-1].text
    #     # })
    #
    #
    #
    #
    # SUPERVISOR_PROMPT = (
    #     "You are a helpful personal assistant. "
    #     "You can schedule calendar events and send emails. "
    #     "Break down user requests into appropriate tool calls and coordinate the results. "
    #     "When a request involves multiple actions, use multiple tools in sequence."
    # )
    #
    # supervisor_agent = create_agent(
    #     model,
    #     tools=[schedule_event, manage_email],
    #     middleware=[handle_tool_errors,
    #                 SummarizationMiddleware(
    #                     model=model,
    #                     # 满足到达模型最大输入 token 的 20 % 或 到达 100 个消息任一条件时触发汇总
    #                     trigger=[("fraction", 0.2), ("messages", 100)],
    #                     keep=("messages", 60),
    #                 ),
    #
    #                 ],
    #     checkpointer=storage.checkpointer,
    #     store=storage.store,
    #     system_prompt=SUPERVISOR_PROMPT,
    # )

    user_request = (
        "安排一场会议，明天15点，和财务团队，时长1小时，会议主题财务会议，描述提交新的财务报表，地点在311会议室。"
        "同时给他们发一封提醒邮件，让他们赶快提交新的财务报表。收件邮箱是412600993@qq.com"
    )

    config = {"configurable": {"thread_id": "8", "user_id": "user_123", "trace_id": str(uuid7())}}
    _trace_id_var.set(config["configurable"]["trace_id"])
    print(f"🚀 开始测试，Trace ID: {config['configurable']['trace_id']}")
    current_input = {"messages": [{"role": "user", "content": user_request}]}

    while True:
        interrupts = []

        # 改回 astream，不需要 to_thread 了
        async for step in supervisor_agent.astream(current_input, config):
            for update in step.values():
                if update is None:
                    continue
                if isinstance(update, dict):
                    for message in update.get("messages", []):
                        message.pretty_print()
                else:
                    interrupt_ = update[0]
                    interrupts.append(interrupt_)
                    print(f"\n🛑 中断 ID: {interrupt_.id}")



        if not interrupts:
            print("\n🎉 所有任务处理完毕。")
            break

        resume = {}
        for interrupt_ in interrupts:
            action_requests = interrupt_.value.get("action_requests", [])
            decisions = []
            for request in action_requests:
                tool_name = request["name"]
                args = request.get("args", {})
                if tool_name in ["schedule_event", "manage_email", "get_not_available_time_slots"]:
                    decisions.append({"type": "approve"})
                elif tool_name == "create_calendar_event":
                    decisions.append({"type": "approve"})
                elif tool_name == "send_email":
                    edited_action = request.copy()
                    edited_action["args"]["subject"] = f"【重要提醒】{args.get('subject', '')}"
                    decisions.append({"type": "edit", "edited_action": edited_action})
                else:
                    decisions.append({"type": "reject"})
            resume[interrupt_.id] = {"decisions": decisions}

        current_input = Command(resume=resume)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == "__main__":
    asyncio.run(main())
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
