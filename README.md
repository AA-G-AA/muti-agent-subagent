
# 🧠 多智能体工具调用系统（LangGraph + LangChain）

🌐 Language / 语言：

- 🇨🇳 中文: [README](./README.md)
- 🇺🇸 English: [README_EN.md](./README.EN.md)

## 📌 项目概述

本项目基于 **LangGraph** 与 **LangChain** 构建多智能体（Multi-Agent）编排系统，结合 **Redis 分布式锁** 实现了工具调用的幂等防护、代码网关拦截、全链路日志追踪与人机交互流程（HITL）。

适用场景：

* 基于飞书日历的日程自动排布
* 邮件自动发送与通知
* 多智能体协同调度

## 🚀 功能特性

### 🧩 多智能体架构

* **主调度 Agent (Supervisor)**：拆解用户请求，分派任务给子 Agent，汇总结果。
* **日历 Agent (Calendar Agent)**：处理日程查询、忙闲判断、创建飞书日历事件。
* **邮件 Agent (Email Agent)**：负责邮件撰写、收件人提取、SMTP 发送。

### 🛠 工具与防御机制

* `create_calendar_event` — 调用飞书 API 创建日历事件（内置 Python 区间拦截检查冲突）。
* `send_email` — 基于 SMTP 的邮件发送工具，支持抄送和附件。SMTP 同步操作通过 `asyncio.to_thread` 丢到线程池，不阻塞事件循环。
* `get_current_datetime` — 获取当前时间，防止 LLM 对日期产生幻觉。
* `get_not_available_time_slots` — 内部函数，返回已被占用的时段列表供代码网关比对。
* 飞书 Token 获取使用**双重检查锁模式**：先查 Redis 缓存，有则直接返回；没有则抢分布式锁，抢到后再次检查缓存，只有真正过期才去刷新 API。高并发下仅 1 个请求刷新 Token，其余等锁释放后读缓存，避免击穿飞书限频。

### 🔁 分布式幂等锁

 `@idempotent` 装饰器，防止因网络重试、重复点击或 LLM 重复调用导致的工具多次执行：

* **基于业务维度哈希**：取 `User + Time + Title` 等关键字段计算 MD5，LLM 改描述不影响幂等性。
* **三种状态管理**：`running`（执行中）、`done`（已缓存，直接返回）、`failed`（失败，允许重试）。
* **关联清理**：删除会话时同步清理对应的 Redis 锁。

### 📊 日志追踪

* 全链路 **trace_id** 贯穿每次请求（基于 ContextVars），方便定位问题。
* 工具调用日志记录完整入参和返回值，便于审计。
* 中间件 `handle_tool_errors` 记录错误堆栈和重试信息。

### 🧠 上下文管理

* 对话内容摘要中间件，动态裁剪上下文窗口。
* 依托 **LangGraph State** 实现多智能体之间的状态共享。

### 👤 人机交互 (HITL)

* 敏感操作（发邮件、创建日程）可触发审批中断，支持通过、驳回或修改参数后放行。

### 🔌 前端连接管理

* WebSocket 每 30 秒发送心跳保活（`type: ping`），防止 NAT 超时断连。
* 断线后自动重连（5 秒间隔），用户无感。

### 🔄 异常处理方案

* **业务异常 (BusinessError)**：向上传递给 LLM，触发大模型自主推理解释或重试（如提示用户更换冲突时间）。
* **致命异常 (FatalError)**：终止流水，触发人工介入。

## 🏗 系统架构与执行流

```text
               用户请求
                  │
                  ▼
            主调度 Agent (Supervisor)
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
    日历 Agent           邮件 Agent
        │                   │
  (代码网关防御)             (SMTP 异步投递)
   ├── 获取当前时间          └── 🔑 Redis 幂等防重锁
   ├── 🛡️ 实时冲突拦截
   └── 🔑 Redis 幂等创建

```

## 🔁 幂等与网关设计规则

### 1. 核心哈希公式

每次调用工具，中间件会根据**核心业务维度**计算 MD5：

```python
# 日历锁：锁死时间段，大模型改描述不影响拦截
md5(user_id + title + start_time + end_time)

# 邮件锁：锁死收件人与主题（to_list 做了 sorted()，LLM 排列顺序不影响幂等性）
md5(user_id + sorted(to_list) + sorted(cc_list) + subject + body)
```

### 2. 双重防御网工作流

1. **第一道防线（代码网关）**：工具内部强行拉取忙碌时段，使用 `json.loads()` 安全反序列化，通过交集公式 `max(req_start, slot_start) < min(req_end, slot_end)` 进行数学判定，重叠则直接抛出 `BusinessError`。
2. **第二道防线（Redis 锁）**：通过网关后，中间件尝试抢锁（`r.set(redis_key, ..., nx=True)`）。抢锁成功执行核心逻辑；命中则直接截断并吐出缓存结果。

## 📦 使用示例

### 📅 多步骤复合业务流程测试

```python
user_request = """
明天15点与财务团队开会，时长1小时，会议主题财务会议，
描述提交新的财务报表，地点在311会议室。
同时给xxxx@qq.com发送一封提醒邮件，让他们赶快提交新的财务报表。
"""

```

## 🧪 项目启动

```bash
python main.py
```

## ⚙️ 环境变量配置

```env
EMAIL_SENDER=xxx@qq.com
EMAIL_PASSWORD=xxx

CALENDER_BOT_APP_SECRET=xxx
SHARE_CALENDER=xxx

OPENAI_API_KEY=xxx
OPENAI_BASE_URL=xxx

```

## 📁 项目结构

```
├── main.py                  # 后端入口 (FastAPI + WebSocket)
├── config.py                # 全局配置 + 日志 + 环境变量
├── middleware.py             # 幂等装饰器 + 错误处理中间件
├── storage.py               # Redis + PostgreSQL 连接管理
├── errors.py                # 自定义异常 (BusinessError / FatalError)
├── agents/
│   ├── supervisor_agent.py  # 主调度 Agent
│   ├── calender_agent.py    # 日历 Agent
│   └── email_agent.py       # 邮件 Agent
├── tools/
│   ├── calender_tool.py     # 飞书日历工具 + 代码网关
│   └── email_tool.py        # QQ邮箱发送工具（含附件支持）
├── api/
│   ├── chat.py              # WebSocket 聊天接口
│   └── session.py           # 会话 CRUD API
├── db/
│   ├── mysql.py             # MySQL 连接池
│   ├── models.py            # 建表语句
│   └── crud.py              # 数据库操作
├── utils/
│   └── feishu.py            # 飞书 Token（双重检查锁）+ 事件 API
└── frontend/                # Vue 3 前端（心跳保活 + 自动重连）
```

> 根目录下的 `sub.py`、`1.py`、`subagent_tutorial1.py`、`test.py` 是开发过程中的思路验证文件，加了注释说明用途，保留作为演进参考。

## 📊 真实操作审计日志片段

```log
trace_id=... [create_calendar_event] 尝试抢锁 redis_key=idempotent:3963f769ea...
trace_id=... [create_calendar_event] 🎯 幂等命中，直接返回缓存结果
trace_id=... agents.supervisor_agent - calender_agent最后一条ai消息...
trace_id=... 🛡️ 代码网关：成功从上下文捞出忙碌时段: ["09:00-10:00", "14:00-15:00"]

```

## 🧠 技术栈

* **LangChain & LangGraph (v0.2+)**
* **GLM-4.5-Flash** (基于 OpenAI 适配器兼容调用)
* **Redis** (分布式锁与结果缓存基础组件)
* 飞书日历开放接口 (Tenant Access Token 机器人认证)
* Python SMTP / asyncio / httpx
* PostgreSQL (长期记忆 Store)
* tenacity (网络重试)

## 🔥 项目亮点

在开发过程中遇到了一些典型问题，以下是针对这些问题的设计和解决方案：

### 1. 代码网关：用数学公式代替 LLM 判断时间冲突

**问题**：LLM 判断时间冲突时经常出错，明明时间已被占用，它仍会调用创建接口。

**做法**：不在 prompt 里让 LLM 判断，而是在 `create_calendar_event` 工具中硬编码一个区间交集公式：

```python
def is_overlapping(req_start, req_end, slot_str):
    slot_start, slot_end = parse(slot_str)
    return max(req_start, slot_start) < min(req_end, slot_end)
```

请求时间与已占时间有重叠，直接抛出 `BusinessError`，LLM 无法绕过。

### 2. 子 Agent 结果校验：检查工具是否真的被调用了

**问题**：子 Agent 有时输出了一大段文字说"已创建成功"，实际上根本没调用工具。Supervisor 容易误判。

**做法**：在 `schedule_event` 工具返回前，扫描子 Agent 的所有消息，检查最后一条 AI 消息中是否有 `create_calendar_event` 的 tool_calls。如果没调用，返回空结果让 Supervisor 察觉异常。

### 3. Redis 分布式幂等锁：重复请求只执行一次

**问题**：网络抖动、用户重复点击或 LLM 死循环会导致同一请求被执行多次，邮件收了多份、日程建了多个。

**做法**：用 `@idempotent` 装饰器包装工具函数，基于 `User + Time + Title` 等核心字段计算 MD5 作为 Redis 锁的 key。重复请求自旋等待（最多 5 次），直接返回第一次执行的结果，不重复调用工具。LLM 改描述措辞不影响幂等性，因为哈希只取关键字段，且收件人列表做了 `sorted()` 排序。

**额外细节**：
- 幂等锁状态的过期时间**差异化**：业务异常（参数传错）冷却 3 秒让 LLM 快速重试；系统崩溃（断网/宕机）冷却 10 秒做熔断保护。
- 错误处理中间件 `handle_tool_errors` 识别 `GraphInterrupt` 信号（HITL 审批中断）时**透传不拦截**，放行给上层图引擎处理，避免审批卡死。

### 4. 强类型转换：防止大模型截断破坏数据结构

**问题**：子 Agent 返回的 JSON 字符串经过多轮对话后，大模型可能只截取部分内容，导致 `json.loads()` 失败。

**做法**：在关键节点用 `json.loads()` 做显式反序列化，并在代码网关中直接调用内部函数获取数据，不经过 LLM 的文本生成，从源头保证数据格式正确。

---

## 🧠 系统能力小结

* **双重防御**：代码网关（数学公式） + Redis 幂等锁，两层防护防止异常操作。
* **全链路 trace_id**：每次请求一个 trace_id，便于日志检索和问题定位。
* **HITL 审批**：敏感操作触发中断，支持人工确认、修改或驳回。
* **全异步**：asyncio + httpx + aiomysql，工具调用不阻塞事件循环。

---


### 📊 运行实测
![结果](./imgs/result.png)


## 🚀 后续计划

* [x] Redis 分布式幂等锁
* [x] asyncio 异步工具链
* [ ] 用户偏好长期记忆（LangGraph Store）
* [ ] 前端流式打字效果
* [ ] 敏感操作前端审批卡片
* [ ] OpenTelemetry 全链路监控
* [ ] 消息队列削峰
---