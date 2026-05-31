
# 🧠 多智能体工具调用系统（LangGraph + LangChain）

🌐 Language / 语言：

- 🇨🇳 中文: [README](./README.md)
- 🇺🇸 English: [README.EN.md](./README.EN.md)

## 📌 项目概述

本项目基于 **LangGraph** 与 **LangChain** 打造生产级多智能体（Multi-Agent）编排系统，深度结合 **Redis 分布式锁** 实现了工具调用的确定性幂等防护、硬编码代码网关拦截、全链路观测与人机交互流程（HITL）。

适用实际自动化业务场景：

* 企业级日程日历智能排布
* 自动化邮件流处理与语义脱敏催收
* 跨平台多智能体分布式协同调度

## 🚀 功能特性

### 🧩 多智能体架构

* **调度总管智能体 (Supervisor)**：负责复杂任务的动态拆解、路由分发与全局流程统筹。
* **日历智能体 (Calendar Agent)**：专注日程规划、忙闲状态分析与日历精确写入。
* **邮件智能体 (Email Agent)**：专注邮件正文润色、收件人列表编排与异步投递。

### 🛠 工具与硬编码防御体系

* `Calendar` — 对接飞书日历 API 创建事件（**内置 Python 确定性区间拦截网关**）。
* `send_email` — 基于 SMTP 协议的异步邮件投递工具。
* `get_current_datetime` — 提供系统实时 ISO 时间基准，消除大模型幻觉。
* `get_not_available_time_slots` — （内部防御函数）动态拉取最新忙碌时段，返回纯 Python 列表，与工具层无缝反序列化。

### 🔁 分布式幂等防护层

 `@idempotent` 装饰器，全面拦截因网络抖动、用户重复点击或大模型死循环导致的工具重发：

* **动态哈希策略**：基于特定业务维度（如 `User + Time + Title`）生成唯一 MD5 密钥，阻断生成式 LLM 文本随机性带来的干扰。
* **状态机生命周期**：支持 `running`（抢锁执行中）、`done`（命中缓存直接返回）、`failed`（失败自动释放，允许重试）。
* **联动清理机制**：支持删除动作主动反向擦除 Redis 幂等锁，实现现实世界状态的强一致性。

### 📊 可观测能力与操作审计

* 全链路 **trace_id** 上下文统一传递（基于 ContextVars 级联）。
* 严密的**工具操作审计日志**：主助理全生命周期消息扫描，防止子 Agent 大白话回话误伤成功流水。
* 中间件层级（`handle_tool_errors`）级联执行轨迹追踪。

### 🧠 上下文管理

* 对话内容摘要中间件，动态裁剪上下文窗口。
* 依托 **LangGraph State** 实现多智能体之间透明的共享运行状态通信。

### 👤 人机交互流程 (HITL)

* 中断式工具审批机制，支持敏感操作（如发邮件、批量改日程）的线上审批、驳回与动态编辑修改。

### 🔄 异常处理方案

* **业务异常 (BusinessError)**：向上传递给 LLM，触发大模型自主推理解释或重试（如提示用户更换冲突时间）。
* **致命异常 (FatalError)**：终止流水，触发人工介入。

## 🏗 系统架构与执行流

```text
               用户请求
                  │
                  ▼
            调度总管智能体 (Supervisor)
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
    日历智能体           邮件智能体
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

# 邮件锁：锁死收件人与主题
md5(user_id + to_list + cc_list + subject + body)

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
python sub.py

```

## ⚙️ 环境变量配置

```env
EMAIL_SENDER=xxx@qq.com
EMAIL_PASSWORD=xxx

CALENDER_BOT_APP_SECRET=xxx
SHARE_CALENDER=xxx

OPENAI_GLM_API_KEY=xxx
OPENAI_GLM_BASE_URL=xxx

```

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

## 🔥 项目亮点（为什么说它是生产级？）

1. **杜绝大模型“脑补”冲突**：时间冲突不用大模型判断，下沉到 Python 确定性代码网关，100% 拦截时间重叠。
2. **完美解决智能体精神分裂**：主助理审计改用全生命周期链路扫描，子智能体用大白话邀功也不会触发“工具未调用”的硬熔断。
3. **数据类型防砸设计**：数据流转全链路严格进行 `JSON str ── json.loads ── Python List` 转换，杜绝了字符切片拆分和隐式异常吞噬。

### 📊 运行实测
![结果](./imgs/result.png)


## 🚀 后续优化方向

* [√] 接入 Redis 实现分布式幂等控制与过期自愈机制
* [√] 基于 asyncio/httpx 实现全链路异步非阻塞工具链调用
* [ ] 引入 LangGraph Store 实现异步非阻塞的用户偏好(Preference)长效记忆
* [ ] **前后端分离聊天交互 (Web-UI)**：基于 FastAPI (Async) 搭建后端接口，利用 WebSocket / SSE (Server-Sent Events) 技术实现流式（Streaming）对话效果。
* [ ] **动态交互审批流与锁管理**：结合 LangGraph 的 HITL 机制，当触发敏感工具时，通过异步接口向前端推送【审批卡片组件】；同时在后台集成 Redis 键值管理，支持手动释放幂等锁。
* [ ] **全链路异步耗时监控 (OpenTelemetry)**：在 FastAPI 中集成 OTel 监控，对“用户提问-Agent编排-工具调用-模型响应”的全生命周期进行图形化耗时追踪，精准定位前端卡顿瓶颈。
* [ ] **高并发多用户队列 (消息队列削峰)**：引入 RabbitMQ / Kafka 异步处理聊天事件流，对高并发请求进行排队削峰，保障多用户同时在线聊天时 Agent 系统的稳定性。
---