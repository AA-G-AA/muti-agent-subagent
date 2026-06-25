import time
from collections import defaultdict

import uvicorn
from fastapi import FastAPI, WebSocket, APIRouter
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.messages import AIMessageChunk, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from config import model
from langgraph.types import Command, Interrupt, interrupt


# ============ 1. 工具函数 ============
def get_weather(city: str) -> str:
    """获取天气"""


    # 2. 细粒度中断：直接暂停，向前端要正确的城市名
    print(f"\n[工具内部拦截] 发现城市名: {city}，触发中断...")

    # 这里的 correct_city 会接收到后面 Command(resume=...) 传进来的值
    sp = interrupt({
        "question": f"您输入的是 '{city}'，请审批！",
        "options": ["reject", "approve"]
    })

    # 3. 用户选择了新的城市，直接用新城市执行逻辑
    print(f"\n[工具内部恢复] 收到用户决策: {sp}")

    # 判断用户的选择
    if sp == "reject":
        return f"用户拒绝了查询 '{city}' 的天气请求。"
    else:
        return f"It's always sunny in {city}!"



def get_user() -> str:
    """获取用户名"""
    return "李华"

# ============ 2. 缓冲区 ============
class Buffer:
    def __init__(self, size: int = 20):
        self.buffer = []
        self.size = size

    def add(self, text: str):
        self.buffer.append(text)
        if len(self.buffer) >= self.size:
            return self.flush()
        return None

    def flush(self):
        if self.buffer:
            chunk = "".join(self.buffer)
            self.buffer.clear()
            return chunk
        return None


# ============ 3. 渲染函数 ============
def render_chunk(token: AIMessageChunk, buffer: Buffer):
    """处理消息块"""
    if token.text:
        result = buffer.add(token.text)
        if result:
            print(result, end="|", flush=True)  # 批量输出

    if token.tool_call_chunks:
        buffer.flush()  # 工具调用前刷新
        print(f"\n[工具调用] {token.tool_call_chunks}")


def render_update(message):
    """处理更新"""
    if isinstance(message, AIMessage) and message.tool_calls:
        print(f"\n[工具调用完成] {message.tool_calls}")
    if isinstance(message, ToolMessage):
        print(f"\n[工具结果] {message.content}")


def _render_message_chunk(token: AIMessageChunk) -> None:
    if token.text:
        print(token.text, end="|",flush=True)
    if token.tool_call_chunks:
        print("tool_call_chunks")
        print(token.tool_call_chunks)
def _render_interrupt(interrupt: Interrupt) -> None:
    # interrupts = interrupt.value
    # for request in interrupts["action_requests"]:
    #     print("看看interrupt的描述")
    #     print(request)
    #     print(request["description"])
    info = interrupt.value
    print("\n[收到自定义中断提示]")
    print(f"问题: {info.get('question')}")
    print(f"选项: {info.get('options')}")

# ============ 4. 主程序 ============
def main():
    # 创建 Agent
    weather_agent = create_agent(
        model=model,
        tools=[get_weather],
        name="weather_agent",
    )
    user_agent = create_agent(
        model=model,
        tools=[get_user],
        name="user_agent",
    )

    @tool
    def call_weather_agent(query: str) -> str:
        """Query the weather agent."""
        result = weather_agent.invoke({
            "messages": [{"role": "user", "content": query}]
        })
        combined = "\n".join([msg.text for msg in result["messages"][-2:]])
        return combined

    @tool
    def call_user_agent(query: str) -> str:
        """Query the user agent."""
        result = user_agent.invoke({
            "messages": [{"role": "user", "content": query}]
        })
        combined = "\n".join([msg.text for msg in result["messages"][-2:]])
        return combined

    agent = create_agent(
        model,
        name="supervisor_agent",
        tools=[call_weather_agent,call_user_agent],
        middleware=[
            #HumanInTheLoopMiddleware(interrupt_on={"get_weather": True,"get_user": True}),
        ],
        store=InMemoryStore(),
        checkpointer=InMemorySaver(),
    )


    config = {"configurable": {"thread_id": "test-1"}}

    # 用户输入
    input_message = {"role": "user", "content": "我的用户名是？SF的天气怎么样?"}
    last_output_agent = None

    print(f"用户: {input_message['content']}\n")
    print("AI: ", end="")

    # 缓冲区
    buffer = Buffer(size=10)
    full_message = None
    agent_buffers = defaultdict(list)

    interrupts=[]

    # 流式处理
    for chunk in agent.stream(
            {"messages": [input_message]},
            stream_mode=["messages", "updates"],
            version="v2",
            config=config,
    ):
    #     if chunk["type"] == "messages":
    #         token, _ = chunk["data"]
    #         if isinstance(token, AIMessageChunk):
    #             render_chunk(token, buffer)
    #             # 聚合完整消息
    #             full_message = token if full_message is None else full_message + token
    #             if token.chunk_position == "last":
    #                 print()
    #                 print("-----------last------------")
    #                 print(token)
    #                 model_name = token.response_metadata.get('model_name', 'N/A')
    #                 print(f"\n模型名称：{model_name}")
    #                 model_provider = token.response_metadata.get('model_provider', 'N/A')
    #                 print(f"\n模型提供商：{model_provider}")
    #                 if hasattr(token, 'usage_metadata') and token.usage_metadata:
    #
    #                     token_usage = token.usage_metadata
    #                     print(f"\n[本轮Token使用] 输入: {token_usage.get('input_tokens', 0)}, "
    #                           f"输出: {token_usage.get('output_tokens', 0)}, "
    #                           f"总计: {token_usage.get('total_tokens', 0)}")
    #                     print(f"\nToken使用细节：")
    #                     input_token_details=token_usage.get("input_token_details",{})
    #                     output_token_details=token_usage.get("output_token_details",{})
    #                     print(f"input_token_details: {input_token_details}")
    #                     print(f"output_token_details: {output_token_details}")
    #
    #
    #
    #     elif chunk["type"] == "updates":
    #
    #         for source, update in chunk["data"].items():
    #
    #             if source == "model":
    #                 last_msg = update["messages"][-1]
    #
    #                 print("updates流里的usage_metadata:", getattr(last_msg, "usage_metadata", None))
    #
    #             if source == "tools":
    #                 render_update(update["messages"][-1])
    #
    # # 清空剩余缓冲区
    # remaining = buffer.flush()
    # if remaining:
    #     print(remaining, end="", flush=True)
        if chunk["type"] == "messages":
            token, metadata = chunk["data"]
            # 如果拿不到子 Agent 名字，说明是顶层 Supervisor
            agent_name = metadata.get("lc_agent_name", "supervisor_agent")

            if isinstance(token, AIMessageChunk) and token.text:
                # 🌟 只有当说话的 Agent 切换时，才换行打印它的名字
                if agent_name != last_output_agent:
                    print(f"\n\n🤖 {agent_name}: ", end="", flush=True)
                    last_output_agent = agent_name

                # 实时打字机输出 Token
                print(token.text, end="", flush=True)

        elif chunk["type"] == "updates":
            for source, update in chunk["data"].items():
                print("source:", source)
                print("update:", update)
                if source in ("model", "tools"):
                    render_update(update["messages"][-1])
                if source == "__interrupt__":
                    print("interrupt启动！")
                    interrupts.extend(update)
                    print(f"interrupts:{interrupts}")
                    for itr in update:
                        _render_interrupt(itr)

    print("\n\n⏸️ 第一轮结束\n")

    # ===== 关键：如果没有 interrupt，说明没触发审批，直接结束 =====
    if not interrupts:
        print("没有触发任何中断，流程已正常结束")
        return

    # ===== 构造决策 =====
    def _get_interrupt_decisions(interrupt: Interrupt) -> list[dict]:
        return [
            {
                "type": "edit",
                "edited_action": {
                    "name": "get_weather",
                    "args": {"city": "Boston, U.K."},
                },
            }
            if "sf" in request["description"].lower()
            else {"type": "approve"}
            for request in interrupt.value["action_requests"]
        ]
    decisions = {}
    for itr in interrupts:
        # decisions[itr.id] = {
        #     "decisions": _get_interrupt_decisions(itr),
        # }
        decisions[itr.id] = "approve"

    print(f"构造的决策: {decisions}\n")
    # ===== 第二次 stream：用 Command(resume=...) 恢复 =====
    print("▶️ 恢复执行...\n")
    for chunk in agent.stream(
            Command(resume=decisions),
            config=config,  # 必须用同一个 thread_id
            stream_mode=["messages", "updates"],
            version="v2",
    ):
        if chunk["type"] == "messages":
            token, _ = chunk["data"]
            if isinstance(token, AIMessageChunk) and token.text:
                _render_message_chunk(token)

        elif chunk["type"] == "updates":
            for source, update in chunk["data"].items():
                if source in ("model", "tools"):
                    render_update(update["messages"][-1])

    print("\n\n✅ 完成")



if __name__ == "__main__":
    main()