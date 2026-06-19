#agents/supervisor_agent.py
import logging
from langchain.agents import create_agent, AgentState
from langchain.agents.middleware import SummarizationMiddleware, dynamic_prompt, ModelRequest
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

# 🌟 1. 彻底干掉 .. 改为干干净净的绝对导入
import storage
from config import _trace_id_var, model
from middleware import handle_tool_errors
from tools.calender_tool import create_calendar_event,get_current_datetime
from tools.email_tool import send_email

logger = logging.getLogger(__name__)

class SuperState(AgentState):
    calendar_done: bool = False
    email_done: bool = False

@tool
async def schedule_event(request: str, runtime: ToolRuntime) -> str:
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

    # 1. 检查子 Agent 在最后一步到底调了哪些工具
    # 我们可以通过查看最后一条 AI 消息里是否包含 create_calendar_event 的 tool_calls
    last_ai_msg = next(
        (m for m in reversed(result["messages"]) if m.type == "ai"),
        None
    )
    logger.info(f"calender_agent最后一条ai消息：{last_ai_msg} \n")
    # 2. 如果最后没有调用任何工具，或者调用的工具里没有 create_calendar_event
    # has_created = False
    # if last_ai_msg and getattr(last_ai_msg, "tool_calls", None):
    #     has_created = any(tc["name"] == "create_calendar_event" for tc in last_ai_msg.tool_calls)
    create_event_msg = next(
        (m for m in reversed(result["messages"])
         if isinstance(m, ToolMessage) and m.name == "create_calendar_event"),
        None
    )
    if create_event_msg is None:
        logger.info(f"❌ 日程未成功创建，可能时间冲突或参数缺失，请重新尝试。")
        return Command(update={
            "messages": [
                ToolMessage(
                    content="❌ 日程未成功创建，可能时间冲突或参数缺失，请重新尝试。",
                    tool_call_id=runtime.tool_call_id,
                )
            ],
            "calendar_done": False,
        })
    logger.info(f"✅ 日程已成功创建。{create_event_msg.content}")
    return Command(update={
        "messages": [
            ToolMessage(
                content=f"✅ 日程已成功创建。{create_event_msg.content}",
                tool_call_id=runtime.tool_call_id,
            )
        ],
        "calendar_done": True,
    })


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


SUPERVISOR_PROMPT = (
    "You are a helpful personal assistant. "
    "You can schedule calendar events and send emails. "
    "Break down user requests into appropriate tool calls and coordinate the results. "
    "When a request involves multiple actions, use multiple tools in sequence. "
    "\n\nCRITICAL RULE: If a tool returns a message confirming the task is already "
    "complete (e.g., containing '已完成' or '无需重复'), you MUST NOT call that same "
    "tool again with the same request. Instead, summarize the results and respond "
    "directly to the user."
    "\n\nIMPORTANT: When a tool result contains a URL/link (e.g. calendar event link), "
    "you MUST include that exact URL verbatim in your final response to the user. "
    "Do NOT omit, shorten, or paraphrase the link."
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