"""
============================================================
🧠 长期记忆子 Agent - 纯 Python 异步后台 Worker
完全摆脱 LangChain Agent 封装，直接调用底层 API

设计哲学：
  - 子 Agent 不是 Tool，不是 LangGraph 节点
  - 它就是后台默默干活的纯 Python 函数
  - 主 Agent 只需投递 (user_id, human_msg, ai_msg) 快照
  - Redis Streams 负责持久化排队、ACK 和多 Worker 扩展
============================================================
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Optional, Dict, Any

from pydantic import BaseModel, field_validator

from config import verifier_model, memory_model

logger = logging.getLogger(__name__)

# =========================
# 常量定义
# =========================
MEMORY_FIELD_MAP = {
    "name": {
        "domain": "profile",
        "key": "name",
        "strategy": "overwrite",
        "reason": "用户明确表达自己的姓名",
    },
    "city": {
        "domain": "profile",
        "key": "city",
        "strategy": "overwrite",
        "reason": "用户明确表达自己的常驻城市",
    },
    "occupation": {
        "domain": "profile",
        "key": "occupation",
        "strategy": "overwrite",
        "reason": "用户明确表达自己的职业",
    },
    "food_preference": {
        "domain": "preferences",
        "key": "food",
        "strategy": "merge",
        "reason": "用户表达了长期饮食偏好",
    },
    "food_avoid": {
        "domain": "constraints",
        "key": "food_avoid",
        "strategy": "merge",
        "reason": "用户表达了饮食禁忌或过敏信息",
    },
}

ALLOWED_MEMORY_KEYS = set(MEMORY_FIELD_MAP)

MEMORY_EXTRACT_PROMPT = """你是记忆提取器，只从用户消息中提取长期事实，不进行任何对话。

【提取规则】：
1. 将复合内容拆解为单品名词，但保留天然整体（如"冰淇淋""蛋炒饭"不拆分）
2. 同类多项内容用中文逗号分隔，例如："哈密瓜, 馕, 葡萄"
3. 只提取有长期记忆价值的信息，忽略临时性、一次性内容

【允许提取的类型】：
允许字段：name, city, food_preference, occupation

【输出格式】：
无记忆 → {"has_memory": false, "memories": null}
有记忆 → {"has_memory": true, "memories": {"food_preference": "哈密瓜, 馕", "city": "北京"}}

【示例】：
用户："我喜欢吃哈密瓜和馕，住在北京"
→ {"has_memory": true, "memories": {"food_preference": "哈密瓜, 馕", "city": "北京"}}

用户："今天天气真好"
→ {"has_memory": false, "memories": null}

用户："我对花生过敏"
→ {"has_memory": true, "memories": {"food_avoid": "花生"}}"""

GREETING_PATTERN = re.compile(
    r"^(你好|您好|hi|hello|hey|早上好|晚上好|下午好)[!！。.~～\s]*$",
    re.IGNORECASE,
)
QUESTION_PATTERN = re.compile(
    r"(什么|哪个|哪些|哪里|哪儿|怎么|怎样|如何|多少|谁|几|是不是|能不能|可不可以|吗[?？]?$|[?？]$|怎么样)"
)


# =========================
# 数据结构
# =========================
class MemoryOutput(BaseModel):
    has_memory: bool = False
    memories: Optional[Dict[str, Any]] = None

    @field_validator("memories", mode="before")
    @classmethod
    def clean_memories(cls, v):
        if not v:
            return v
        clean = {}
        for k, val in v.items():
            if k not in ALLOWED_MEMORY_KEYS:
                continue
            if val is None:
                continue
            if isinstance(val, list):
                val = ",".join(str(item).strip() for item in val if item is not None and str(item).strip())
            clean[k] = val
        return clean


@dataclass
class MemoryTask:
    """后台记忆任务的数据快照"""
    user_id: str
    human_msg: str
    ai_msg: str
    thread_id: str = ""

    def to_stream_fields(self) -> Dict[str, str]:
        return {
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "human_msg": self.human_msg,
            "ai_msg": self.ai_msg,
        }

    @classmethod
    def from_stream_fields(cls, fields: Dict[str, Any]) -> "MemoryTask":
        def read(name: str) -> str:
            value = fields.get(name, "")
            if isinstance(value, bytes):
                return value.decode("utf-8")
            return str(value)

        return cls(
            user_id=read("user_id"),
            thread_id=read("thread_id"),
            human_msg=read("human_msg"),
            ai_msg=read("ai_msg"),
        )


# =========================
# Redis Streams 队列配置
# =========================
MEMORY_STREAM_KEY = "memory:tasks"
MEMORY_CONSUMER_GROUP = "memory-workers"
MEMORY_DEFAULT_CONSUMER = "memory-worker-1"


async def ensure_memory_stream_group(redis_client):
    """确保 Redis Stream 消费者组存在。"""
    try:
        await redis_client.xgroup_create(
            MEMORY_STREAM_KEY,
            MEMORY_CONSUMER_GROUP,
            id="0",
            mkstream=True,
        )
        logger.info(
            "✅ Redis Stream 消费者组已创建: stream=%s group=%s",
            MEMORY_STREAM_KEY,
            MEMORY_CONSUMER_GROUP,
        )
    except Exception as e:
        if "BUSYGROUP" in str(e):
            return
        raise


async def enqueue_memory_task(redis_client, task: MemoryTask) -> str:
    """把记忆任务写入 Redis Stream，供后台 worker 异步消费。"""
    message_id = await redis_client.xadd(MEMORY_STREAM_KEY, task.to_stream_fields())
    logger.info(
        "📥 已投递长期记忆任务: message_id=%s user_id=%s thread_id=%s",
        message_id,
        task.user_id,
        task.thread_id,
    )
    return message_id


# =========================
# 工具函数（从 long_term_agent.py 移植）
# =========================
def parse_memory_output(content: str) -> MemoryOutput:
    """解析 LLM 输出并转换为 MemoryOutput"""
    cleaned = re.sub(r"```json|```", "", content).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return MemoryOutput(has_memory=False, memories=None)

    data = json.loads(match.group())
    if not isinstance(data, dict) or not data:
        return MemoryOutput(has_memory=False, memories=None)
    if "has_memory" not in data:
        return MemoryOutput(has_memory=False, memories=None)
    return MemoryOutput(**data)


def has_fact_statement(text: str) -> bool:
    """判断是否为陈述事实的句子"""
    if re.search(r"我在[^，。!！?？吗哪个什么怎]", text):
        return True
    return any(marker in text for marker in ("我叫", "我是", "我喜欢", "我住在", "我的职业", "我从事"))


def get_fast_skip_reason(text: str) -> Optional[str]:
    """快速判断是否跳过记忆提取"""
    text = text.strip()
    if not text:
        return "empty message"
    if has_fact_statement(text):
        return None
    if GREETING_PATTERN.match(text):
        return "greeting"
    if QUESTION_PATTERN.search(text):
        return "question"
    return None


def get_field_value(existing, key: str):
    """从 store 记录中读取字段值"""
    if not existing:
        return None
    value = existing.value
    if isinstance(value, dict):
        if "value" in value:
            return value.get("value")
        return value.get(key)
    if isinstance(value, str) and existing.key == key:
        return value
    return None


def build_memory_record(raw_value, reason: str, evidence: str):
    """构建存储记录"""
    return {
        "value": raw_value,
        "reason": reason,
        "evidence": evidence,
    }


def merge(old, value: str):
    """合并记忆值（去重）"""
    old_list = old if isinstance(old, list) else [old] if old else []
    new_items = [i.strip() for i in re.split(r"[，,]", value) if i.strip()]

    for item in new_items:
        if any((item in old_el or old_el in item) for old_el in old_list):
            continue
        old_list.append(item)
    return old_list


def memory_policy(strategy: str, value: str, existing, key: str):
    """记忆策略引擎"""
    old = get_field_value(existing, key)

    if isinstance(old, list) and value in old:
        return {"action": "skip"}
    if old == value:
        return {"action": "skip"}

    if strategy == "overwrite":
        return {"action": "write"}
    if strategy == "merge":
        if not old:
            return {"action": "write"}
        if isinstance(old, list) and value in old:
            return {"action": "skip"}
        if old == value:
            return {"action": "skip"}
        return {"action": "merge"}

    return {"action": "write"}


def normalize(text: str):
    """标准化文本用于匹配"""
    return re.sub(r'[，,、\s]', '', text)


async def llm_verify_score(user_message, aimessage, key, value, match_ratio=None) -> float:
    """用 LLM 验证记忆真实性"""
    prompt = f"""你是记忆验证专家。判断用户是否表达了该信息作为长期事实。

用户说：{user_message}
AI回复说：{aimessage}
提取的信息：{key} = {value}
原文匹配度：{match_ratio if match_ratio is not None else "未计算"}

判断标准：
1. 用户明确说"我喜欢/我住在/我是/我在..." → 长期事实 → 输出 1
2. 用户陈述了关于自己的持久性信息（职业、城市、饮食偏好等） → 输出 1
3. 信息是临时场景提到的（今天天气、这次行程、偶然事件） → 输出 0
4. 不确定 → 输出 0

只输出一个数字 0 或 1："""

    resp = await verifier_model.ainvoke([
        {"role": "user", "content": prompt}
    ])
    try:
        return float(resp.content.strip())
    except:
        return 0.0


async def verify_memory(user_message, aimessage, key, value):
    """验证记忆的完整流程"""
    logger.info("=" * 50)
    logger.info("📋 验证记忆")
    logger.info("-" * 50)
    logger.info(f"👤 用户原话: {user_message}")
    logger.info(f"🏷️ 字段: {key}")
    logger.info(f"📝 提取值: {value}")

    items = [v.strip() for v in re.split(r"[，,]", value) if v.strip()]
    norm_msg = normalize(user_message)
    norm_items = [normalize(i) for i in items]

    match_count = sum(1 for i in norm_items if i in norm_msg)
    match_ratio = match_count / max(len(norm_items), 1)
    logger.info(f"[MATCH] ratio={match_ratio}")

    if match_ratio < 0.4:
        return {"pass": False, "score": 0.0, "reason": "low_match"}

    score = await llm_verify_score(user_message, aimessage, key, value, match_ratio)
    return {"pass": score >= 0.6, "score": score, "reason": "llm_score"}


def final_decision(policy_action, verify_result):
    """最终决策"""
    if policy_action == "skip":
        return False
    return verify_result["pass"]


# ============================================================
# 🎯 核心：后台记忆子 Agent Worker
# ============================================================
async def process_memory_task(task: MemoryTask, store_instance):
    """处理单个长期记忆任务：提取、验证、合并并写入 LangGraph Store。"""
    user_id = task.user_id
    conversation = task.human_msg
    aimessage = task.ai_msg

    logger.info(f"⚡ [MemoryWorker] 开始处理用户 {user_id} 的长期记忆...")

    # ---- 1. 快速跳过检测（问候语/纯提问不走 LLM） ----
    fast_skip = get_fast_skip_reason(conversation)
    if fast_skip:
        logger.info(f"[MemoryWorker] 用户 {user_id} 快速跳过: {fast_skip}")
        return

    # ---- 2. 调用记忆提取模型 ----
    response = await memory_model.ainvoke([
        {"role": "system", "content": MEMORY_EXTRACT_PROMPT},
        {"role": "user", "content": conversation},
    ])
    result = parse_memory_output(response.content)

    if not result or not result.has_memory or not result.memories:
        logger.info(f"[MemoryWorker] 用户 {user_id} 本次对话无长期事实，略过。")
        return

    logger.info(f"[MemoryWorker] 提取到记忆: {result.memories}")

    # ---- 3. 遍历提取到的字段，执行 Policy 和 Verify ----
    touched_namespaces = set()

    for key, value in result.memories.items():
        field_cfg = MEMORY_FIELD_MAP.get(key)
        if not field_cfg:
            continue

        if value is None:
            continue
        value = str(value).strip()
        if not value:
            continue

        domain = field_cfg["domain"]
        store_key = field_cfg["key"]
        strategy = field_cfg["strategy"]
        reason = field_cfg["reason"]
        namespace = (user_id, domain)
        touched_namespaces.add(namespace)

        # 3.1 读取现有记忆 + Policy 判断
        existing = await store_instance.aget(namespace, store_key)
        policy = memory_policy(strategy, value, existing, store_key)

        logger.info(f"[MemoryWorker] Policy[{domain}.{store_key}]: {policy}")

        if policy["action"] == "skip":
            continue

        # 3.2 验证记忆真实性
        try:
            verify = await verify_memory(conversation, aimessage, f"{domain}.{store_key}", value)
        except Exception as e:
            logger.error(f"[MemoryWorker] 验证异常: {e}")
            continue

        logger.info(f"[MemoryWorker] Verify[{domain}.{store_key}]: {verify}")

        # 3.3 最终决策
        if not final_decision(policy["action"], verify):
            logger.info(f"[MemoryWorker] 最终决策拒绝: {domain}.{store_key}")
            continue

        # 3.4 写入数据库
        old = get_field_value(existing, store_key)
        if policy["action"] == "merge":
            new_value = merge(old, value)
        else:
            new_value = value

        stored = build_memory_record(new_value, reason, conversation)
        await store_instance.aput(namespace, store_key, stored, index=["value"])

        logger.info(f"💾 [MemoryWorker] 成功为用户 {user_id} 持久化记忆: {domain}.{store_key} = {stored}")

    # ---- 4. 打印完整记忆（调试用） ----
    logger.info(f"\n📚 用户 {user_id} 当前完整记忆:")
    for namespace in touched_namespaces:
        items = await store_instance.asearch(namespace)
        logger.info(f"   namespace={namespace}")
        for item in items:
            logger.info(f"      {item.key}: {item.value}")


async def memory_sub_agent_worker(
    redis_client,
    store_instance,
    consumer_name: str = MEMORY_DEFAULT_CONSUMER,
    block_ms: int = 5000,
):
    """
    后台常驻的长期记忆消费者。

    使用 Redis Streams 替代进程内 asyncio.Queue：
      1. 从 memory:tasks 消费 (user_id, human_msg, ai_msg) 快照
      2. 调 memory_model 提取事实
      3. Policy 判断 + Verify 验证
      4. 直接操作 store 写入 PostgreSQL
      5. 成功后 XACK；失败则不 ACK，保留在 pending 中等待后续重试策略处理
    """
    logger.info("=" * 60)
    logger.info("🧠 Redis Streams 长期记忆 Worker 已启动: consumer=%s", consumer_name)
    logger.info("=" * 60)

    await ensure_memory_stream_group(redis_client)

    while True:
        messages = await redis_client.xreadgroup(
            groupname=MEMORY_CONSUMER_GROUP,
            consumername=consumer_name,
            streams={MEMORY_STREAM_KEY: ">"},
            count=1,
            block=block_ms,
        )

        if not messages:
            continue

        for _, stream_messages in messages:
            for message_id, fields in stream_messages:
                task = MemoryTask.from_stream_fields(fields)
                try:
                    await process_memory_task(task, store_instance)
                    await redis_client.xack(MEMORY_STREAM_KEY, MEMORY_CONSUMER_GROUP, message_id)
                    logger.info("✅ 长期记忆任务已 ACK: message_id=%s", message_id)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(
                        "❌ 长期记忆任务失败，暂不 ACK: message_id=%s error=%s",
                        message_id,
                        e,
                        exc_info=True,
                    )
