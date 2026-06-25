#agents/supervisor_agent.py
from langchain.agents import create_agent, AgentState
from langchain.agents.middleware import SummarizationMiddleware, dynamic_prompt, ModelRequest, after_model, \
    before_model, HumanInTheLoopMiddleware
import logging
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from langgraph.types import Command

import storage
from config import model
from middleware import handle_tool_errors


logger = logging.getLogger(__name__)

class SuperState(AgentState):
    calendar_done: bool = False
    email_done: bool = False

@tool
async def schedule_event(request: str, runtime: ToolRuntime) -> str:
    """用自然语言安排日程。

    当用户想要创建、修改、查看空闲时间或查看日历约会时使用此工具。
    处理日期/时间解析、空闲时段检查和事件创建。

    输入：自然语言日程请求（例如："下周二下午2点与设计团队开会"）
    """
    logger.info(f"主agent的schedule_event开启！")
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
            # "You are assisting with the following user inquiry:\n\n"
            # f"{summary_message.content}\n\n"
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

    result = await calendar_agent.ainvoke(
        {
            "messages": [{"role": "user", "content": prompt}],
        }, config=runtime.config,
    )
    logger.info(f"schedule_event的结果:{result}")

    create_event_msg = next(
        (m for m in reversed(result["messages"])
         if isinstance(m, ToolMessage)
         and m.name == "create_calendar_event"
         and getattr(m, "status", "success") != "error"
         and "创建成功" in m.content),
        None
    )

    # reject 的 ToolMessage（status="error"）
    rejected_msg = next(
        (m for m in reversed(result["messages"])
         if isinstance(m, ToolMessage)
         and m.name == "create_calendar_event"
         and getattr(m, "status", "success") == "error"),
        None
    )
    logger.info(f"rejected_msg:{rejected_msg}")
    status = getattr(rejected_msg, "status", "None") if rejected_msg else "None"
    logger.info(f"rejected_msg status: {status}")

    if create_event_msg:
        logger.info(f"✅ 日程已成功创建。{create_event_msg.content}")
        return Command(update={
            "messages": [ToolMessage(
                content=f"✅ 日程已成功创建。{create_event_msg.content}",
                tool_call_id=runtime.tool_call_id,
            )],
            "calendar_done": True,
        })

    if rejected_msg:
        logger.info("🚫 用户已拒绝创建日程。")
        return Command(update={
            "messages": [ToolMessage(
                content="用户已取消日程创建，任务终止，请勿重试。",
                tool_call_id=runtime.tool_call_id,
            )],
            "calendar_done": False,
        }, goto="__end__")

    # 🔥 3. 其他所有情况：直接透传子Agent的最后一条回复
    # 不管是时间已过、参数不全、还是任何子Agent自己处理的情况
    last_ai = next(
        (m for m in reversed(result["messages"])
         if isinstance(m, AIMessage) and getattr(m, "name", "") == "calendar_agent"),
        None
    )

    if last_ai and last_ai.content:
        reply_content = last_ai.content
        logger.info(f"📤 子Agent回复: {reply_content[:100]}...")
        return Command(update={
            "messages": [ToolMessage(
                content=reply_content,
                tool_call_id=runtime.tool_call_id,
            )],
            "calendar_done": False,  # 没创建成功，但消息已经给用户了
        }, goto="__end__")

    # 4. 极端兜底：理论上不会走到这里
    logger.warning("⚠️ 子Agent没有返回任何有效内容")
    return Command(update={
        "messages": [ToolMessage(
            content="日程服务暂时无法处理，请稍后重试或联系管理员。",
            tool_call_id=runtime.tool_call_id,
        )],
        "calendar_done": False,
    }, goto="__end__")

    # if not has_created:
    #     # 🚨 强行阻断！明确告诉主 Agent：因为时间冲突，日程根本没有创建！
    #     return (
    #         f"❌ 日程安排失败！\n"
    #         f"原因：所选时间冲突或不可用。\n"
    #         f"日历检查流水：\n\n{raw_tool_output}\n\n"
    #         f"请告知用户时间冲突，并让用户重新选择时间。"
    #     )

    # 如果成功创建了，再返回正常的流水
    # return raw_tool_output

@tool
async def manage_email(request: str, runtime: ToolRuntime) -> str:
    """用自然语言发送邮件。

    当用户想要发送通知、提醒或任何邮件通信时使用此工具。
    处理收件人提取、主题生成和邮件撰写。

    输入：自然语言邮件请求（例如："给他们发送一封关于会议的提醒邮件"）
    """
    logger.info(f"主agent的manage_email开启！")
    trace_id = runtime.config["configurable"].get("trace_id")
    logger.info(f"manage_email 被调用")

    result = await email_agent.ainvoke({
        "messages": [{"role": "user", "content": request}]
    }, config=runtime.config)
    logger.info(f"manage_email的结果:{result}")
    # Option 1: Return just the confirmation message
    # 检查邮件 Agent 最后是否真的调用了 send_email
    send_email_result = next(
        (m for m in result["messages"]
         if isinstance(m, ToolMessage) and m.name == "send_email"),
        None
    )

    if send_email_result is None:
        return Command(update={
            "messages": [ToolMessage(
                content="❌ 邮件未成功发送，可能缺少必要参数，请重新尝试。",
                tool_call_id=runtime.tool_call_id,
            )],
            "email_done": False,
        })

    return Command(update={
        "messages": [ToolMessage(
            content=f"✅ 邮件已成功发送。{send_email_result.content}",
            tool_call_id=runtime.tool_call_id,
        )],
        "email_done": True,
    })
    # Option 2: Return structured data
    # return json.dumps({
    #     "status": "success",
    #     "event_id": "evt_123",
    #     "summary": result["messages"][-1].text
    # })






@before_model(can_jump_to=["end"])
def check_reject_before_model(state, runtime):
    logger.info("=" * 60)
    logger.info("【check_reject_before_model】开始执行")

    # ==================== 1. 获取消息列表 ====================
    messages = state.get("messages", [])
    logger.info(f"→ 步骤1: 获取消息列表，共 {len(messages)} 条消息")

    # ==================== 2. 查找最后一条 HumanMessage ====================
    logger.info("→ 步骤2: 从后往前查找最后一条 HumanMessage")

    last_human_idx = None
    for i in reversed(range(len(messages))):
        msg = messages[i]
        if isinstance(msg, HumanMessage):
            last_human_idx = i
            logger.info(f"  找到最后一条 HumanMessage，索引: {i}")
            logger.info(f"    内容: {msg.content}...")
            break

    if last_human_idx is None:
        logger.info("  ⚠ 未找到任何 HumanMessage，返回 None")
        logger.info("【check_reject_before_model】结束（无HumanMessage）")
        return None

    logger.info(f"  最后一条 HumanMessage 索引: {last_human_idx}")

    # ==================== 3. 截取最近消息 ====================
    recent_messages = messages[last_human_idx:]
    logger.info(f"→ 步骤3: 截取最后一条 HumanMessage 之后的消息，共 {len(recent_messages)} 条")

    for i, msg in enumerate(recent_messages):
        msg_type = type(msg).__name__
        content_preview = getattr(msg, 'content', '')[:50]
        logger.info(f"    [{i}] {msg_type}: {content_preview}...")

    # ==================== 4. 查找符合条件的 ToolMessage ====================
    logger.info("→ 步骤4: 在截取的消息中从后往前查找符合条件的 ToolMessage")
    logger.info("  条件: ToolMessage, name=schedule_event, content包含'User rejected the tool call'")

    # 统计所有 schedule_event 的 ToolMessage
    tool_msgs = [
        m for m in recent_messages
        if isinstance(m, ToolMessage) and m.name == "schedule_event"
    ]
    logger.info(f"  所有 schedule_event 的 ToolMessage 数量: {len(tool_msgs)}")

    for i, msg in enumerate(tool_msgs, 1):
        has_cancel = "User rejected the tool call" in msg.content
        logger.info(f"    #{i}: content={msg.content[:50]}... 包含取消信号: {has_cancel}")

    # 查找最后一条
    last_tool = next(
        (m for m in reversed(recent_messages)
         if isinstance(m, ToolMessage)
         and m.name == "schedule_event"
         and "User rejected the tool call" in m.content),
        None
    )

    # ==================== 5. 判断是否找到 ====================
    if last_tool is not None:
        logger.info("  ✓ 找到符合条件的 ToolMessage")
        logger.info(f"    content: {last_tool.content}")
        logger.info(f"    status: {getattr(last_tool, 'status', '无')}")

        # ==================== 6. 构造返回结果（跳转到结束） ====================
        logger.info("→ 步骤6: 构造返回结果，跳转到 end")

        response = {
            "messages": [AIMessage(content="好的，已为您取消日程创建。")],
            "jump_to": "end"
        }
        logger.info(f"  响应内容: {response['messages'][0].content}")
        logger.info(f"  跳转目标: {response['jump_to']}")
        logger.info("【check_reject_before_model】结束（跳转结束）")
        return response

    # ==================== 7. 未找到 ====================
    logger.info("→ 步骤7: 未找到符合条件的 ToolMessage，返回 None 继续执行")
    logger.info("【check_reject_before_model】结束（继续）")
    return None

SUPERVISOR_PROMPT = (
    "You are a helpful personal assistant with two specific tools:\n"
    "- schedule_event: ONLY for creating/modifying/canceling calendar events\n"
    "- manage_email: ONLY for sending emails/notifications/reminders\n"
    "\n"
    "CRITICAL: TOOL CALLING RULES (strictly enforce):\n"
    "1. If the user's request is a simple greeting (你好, hi, 嗨), a question about you "
    "   (你是谁, 你能做什么), a farewell, or any general conversation, "
    "   respond directly. DO NOT call ANY tool.\n"
    "2. ONLY call a tool when the user EXPLICITLY asks you to DO something with their "
    "   calendar or email. If you're unsure, respond conversationally and ask for clarification.\n"
    "3. If the user asks for help (help, 帮助, 使用方法), list the things you can help with "
    "   and ask what they need. DO NOT call tools.\n"
    "4. If the user mentions things you cannot do (weather, news, API info, settings, etc.), "
    "   politely say you don't have that capability and redirect to calendar/email tasks.\n"
    "\n"
    "⛔ STRONG RULE: Never call a tool when the user is just ASKING for help or ASKING about you.\n"
    "Tools are for EXECUTING actions, not for answering questions.\n"
    "\n"
    "When you DO call a tool:\n"
    "- If a tool returns 'already complete', DO NOT call it again\n"
    "- When a tool returns a URL/link, include the exact URL in your final response\n"
    "- Use multiple tools in sequence when the user requests multiple actions\n"
    "\n"
    "CONTEXT HANDLING:\n"
    "- If your context begins with 'Here is a summary of the conversation', "
    "that is background context only. NEVER repeat or output the summary content.\n"
    "- Only respond to the user's latest request, using the summary silently as background knowledge.\n"
)
@dynamic_prompt
def change_system_prompt(request: ModelRequest):
    status = []
    if request.state.get("calendar_done", False):
        status.append("- 日程已创建完成，绝对不要再调用 schedule_event。")
    if request.state.get("email_done", False):
        status.append("- 邮件已发送完成，绝对不要再调用 manage_email。")
    if status:
        return SUPERVISOR_PROMPT + "\n\n当前任务状态：\n" + "\n".join(status)
    return SUPERVISOR_PROMPT

supervisor_agent=None
def init_supervisor_agent():
    global supervisor_agent
    supervisor_agent = create_agent(
        model,
        tools=[schedule_event, manage_email],
        middleware=[handle_tool_errors,
                    change_system_prompt,
                    check_reject_before_model,
                    HumanInTheLoopMiddleware(
                        description_prefix="工具执行需要审批",  # 全局默认
                        interrupt_on={
                            # 调用工具时，强制中断并等待人类操作
                            "schedule_event": {
                                # 允许人类进行的操作：批准、编辑、拒绝
                                "allowed_decisions": ["approve", "reject"],
                                "description": "⚠️ 创建日程操作需要审批"  # 覆盖全局 prefix
                            },
                            # 调用工具时，不中断，自动执行
                            "manage_email": {
                                # 允许人类进行的操作：批准、编辑、拒绝
                                "allowed_decisions": ["approve", "reject"],
                                "description": "⚠️ 发邮件操作需要审批"  # 覆盖全局 prefix
                            },
                        }
                    ),
                    SummarizationMiddleware(
                        model=model,
                        # 满足到达模型最大输入 token 的 20 % 或 到达 100 个消息任一条件时触发汇总
                        trigger=[("fraction", 0.2), ("messages", 100)],
                        keep=("messages", 60),
                    ),
                    ],
        checkpointer=storage.checkpointer,
        store=storage.store,
        #system_prompt=SUPERVISOR_PROMPT,
        state_schema=SuperState
    )


from agents.calender_agent import calendar_agent
from agents.email_agent import email_agent