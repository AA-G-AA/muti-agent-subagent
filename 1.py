import uuid
from operator import add
from typing import Annotated, TypedDict
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


class State(TypedDict):
    messages: Annotated[list, add]


def node(state):
    # 子图节点：每次执行给消息列表追加一个 "sub_step"
    return {"messages": ["sub_step"]}


# 初始化基础的图结构
sub = StateGraph(State)
sub.add_node("node", node)
sub.add_edge(START, "node")
sub.add_edge("node", END)


# =====================================================================
# 🔬 深度透视打印函数（核心：提取 channel_values 里的真实状态）
# =====================================================================
def dump_checkpoints(title: str, saver: InMemorySaver, current_config: dict):
    print(f"\n{'='*20} 🌟 {title} 🌟 {'='*20}")
    # 捞出当前 thread_id 下的所有历史快照
    checkpoints = list(saver.list(current_config))

    if not checkpoints:
        print(" ❌ [空] 该 checkpointer 库中没有任何数据记录。")
        return

    # 为了方便看时间线流转，我们逆序打印（从早到晚）
    for i, cp in enumerate(reversed(checkpoints), 1):
        ns = cp.config["configurable"].get("checkpoint_ns", "")
        cp_id = cp.config["configurable"]["checkpoint_id"]

        # 💡 关键：channel_values 才是真正存放应用变量（如 messages）的抽屉
        channel_values = cp.checkpoint.get("channel_values", {})
        messages = channel_values.get("messages", [])

        print(f"步骤 [{i}]")
        print(f"  📍 命名空间 [ns]: '{ns}' " + ("(👈 父图主轴)" if ns == "" else "(👈 子图空间)"))
        print(f"  🆔 状态快照 [id]: {cp_id}")
        print(f"  📦 内部真实数据 [messages]: {messages}")
        print("-" * 50)


# =====================================================================
# ===== 【测试 1】 checkpointer=True (静态空间覆盖模式) =====
# =====================================================================
checkpointer1 = InMemorySaver()
# 强制开启 True，显式使用固定的节点名作为空间
sub_compiled_true = sub.compile(checkpointer=True)

parent_builder1 = StateGraph(State)
parent_builder1.add_node("sub1", sub_compiled_true)
parent_builder1.add_edge(START, "sub1")
parent_builder1.add_edge("sub1", END)
parent_graph1 = parent_builder1.compile(checkpointer=checkpointer1)

config1 = {"configurable": {"thread_id": "test-true-thread"}}

# 模拟连续调用两次，观察静态覆盖现象
print("\n▶️ 启动测试 1 (True)...")
parent_graph1.invoke({"messages": ["hello_1"]}, config1)

dump_checkpoints("测试1：checkpointer=True 内部内容变化", checkpointer1, config1)


# =====================================================================
# ===== 【测试 2】 checkpointer=None (官方推荐：动态多宇宙隔离) =====
# =====================================================================
checkpointer2 = InMemorySaver()
# 子图设为 None，意味着完全把生命周期和空间命名托管给父图的存储库
sub_compiled_none = sub.compile(checkpointer=None)

parent_builder2 = StateGraph(State)
parent_builder2.add_node("sub", sub_compiled_none)
parent_builder2.add_edge(START, "sub")
parent_builder2.add_edge("sub", END)
parent_graph2 = parent_builder2.compile(checkpointer=checkpointer2)

config2 = {"configurable": {"thread_id": "test-none-thread"}}

print("\n▶️ 启动测试 2 (None)...")
parent_graph2.invoke({"messages": ["hello_2"]}, config2)

dump_checkpoints("测试2：checkpointer=None 内部内容变化", checkpointer2, config2)


# =====================================================================
# ===== 【测试 3】 子图用独立的 checkpointer (强行各管各的-信号打断模式) =====
# =====================================================================
checkpointer3_parent = InMemorySaver()
checkpointer3_sub = InMemorySaver()  # 给子图一个完全独立的本子

sub_independent = sub.compile(checkpointer=checkpointer3_sub)

parent_builder3 = StateGraph(State)
parent_builder3.add_node("sub", sub_independent)
parent_builder3.add_edge(START, "sub")
parent_builder3.add_edge("sub", END)
parent_graph3 = parent_builder3.compile(checkpointer=checkpointer3_parent)

config3 = {"configurable": {"thread_id": "test-independent-thread"}}

print("\n▶️ 启动测试 3 (独立存储)...")
parent_graph3.invoke({"messages": ["hello_3"]}, config3)

dump_checkpoints("测试3：父图存储库里看到的内容", checkpointer3_parent, config3)

# 💡 破解为何测试 3 之前子图打印为空的谜题：
# 因为子图用的是自己的数据库，它的 namespace 不是空的。我们必须全量盲查（不带 config 限定）才能抓到它
print(f"\n{'='*20} 🌟 测试3：子图自己存储库里存的内容 🌟 {'='*20}")
all_sub_cps = list(checkpointer3_sub.list({"configurable": {"thread_id": "test-independent-thread", "checkpoint_ns": "sub:*"}})) # 用通配符抓取
# 如果通配符在内存模式下不好抓，直接用空 config 捞出库里所有记录：
all_raw_data = list(checkpointer3_sub.list({}))
for i, cp in enumerate(all_raw_data, 1):
    ns = cp.config["configurable"].get("checkpoint_ns", "")
    messages = cp.checkpoint.get("channel_values", {}).get("messages", [])
    print(f"隐秘步骤 [{i}]")
    print(f"  📍 隐秘命名空间 [ns]: '{ns}'")
    print(f"  📦 隐秘子图内容 [messages]: {messages}")
    print("-" * 50)