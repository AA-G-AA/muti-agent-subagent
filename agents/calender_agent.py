#agents/calender_agent.py
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware

import storage
from config import _trace_id_var, model
from middleware import handle_tool_errors
from tools.calender_tool import create_calendar_event, get_current_datetime,get_not_available_time_slots

CALENDAR_AGENT_PROMPT = (
    "You are a DOER calendar assistant. EVERY user request "
    "involving time (meetings, meals, reminders, tasks) MUST be scheduled as a "
    "calendar event. Do not refuse personal events like 'eating dinner'.\n\n"

    "【CRITICAL WORKFLOW】\n"
    "1. Before scheduling anything, always call 'get_current_datetime' to know what today's date is.\n"
    "2. Before calling 'create_calendar_event', you MUST ALWAYS call 'get_not_available_time_slots' to check the busy slots for attendees.\n\n"

    "【CONFLICT RESOLUTION RULES】\n"
    "- Carefully parse the user's requested time slot (e.g., '明天14点' means '14:00-15:00' if duration is 60m).\n"
    "- Compare the requested slot with the results from 'get_not_available_time_slots'.\n"
    "- If the requested time overlaps WITH ANY PART of the non-available slots, YOU MUST STOP IMMEDIATELY!\n"
    "- DO NOT call 'create_calendar_event' under any circumstances if a conflict is detected.\n"
    "- Instead, directly abort and reply to the user: '❌ ERROR: The requested time slot [Insert Requested Time] conflicts with an existing meeting.'\n\n"

    "Remember: Saving the user from meeting conflicts is your highest priority. Do not be a yes-man."
)
calendar_agent = create_agent(
    model,
    tools=[create_calendar_event, get_current_datetime],
    system_prompt=CALENDAR_AGENT_PROMPT,
    middleware=[
        handle_tool_errors,
        # HumanInTheLoopMiddleware(
        #     description_prefix="工具执行需要审批",  # 全局默认
        #     interrupt_on={
        #         # 调用工具时，强制中断并等待人类操作
        #         "create_calendar_event": {
        #             # 允许人类进行的操作：批准、编辑、拒绝
        #             "allowed_decisions": ["approve", "reject"],
        #             "description": "⚠️ 创建日程操作需要审批"  # 覆盖全局 prefix
        #         },
        #         # 调用工具时，不中断，自动执行
        #         "get_current_datetime": False,
        #     }
        # ),
    ],
    store=storage.store,
    checkpointer=None,
    name="calendar_agent"
)
