# 🧠 多智能体工具调用系统（LangGraph + LangChain）
## 📌 项目概述
本项目基于 LangGraph 与 LangChain 构建企业级多智能体编排系统，支持工具调用、子智能体协同、幂等操作、链路观测与人机交互流程。

适用于实际自动化业务场景：
- 日程日历编排
- 邮件自动收发
- 多智能体跨角色任务协同

## 🚀 核心特性
### 🧩 多智能体架构
- **调度总管智能体**：任务拆解、流程编排
- **日历智能体**：日程创建与时间管理
- **邮件智能体**：邮件编辑与消息推送

### 🛠 工具能力
- `create_calendar_event`：飞书日历事件创建
- `send_email`：SMTP 协议邮件发送
- `get_not_available_time_slots`：空闲时间冲突校验
- `get_current_datetime`：系统时间获取

### 🔁 幂等防护层
杜绝工具重复执行，核心能力：
- 基于哈希算法生成唯一事件标识
- 任务状态：执行中、已完成、执行失败
- 安全重试机制、重复请求拦截

### 📊 全链路观测
- 全局唯一追踪 ID 透传
- 结构化日志输出
- 中间件执行链路追踪
- 工具调用审计日志

### 🧠 上下文管理
- 对话摘要中间件
- 子智能体上下文注入
- LangGraph 全局共享运行状态

### 👤 人机交互 HITL
- 中断式工具审批流程
- 支持审批、驳回、编辑执行动作
- 敏感操作人工复核执行

### 🔄 异常处理策略
- 业务异常：大模型自主推理恢复
- 致命异常：触发人工介入处理
- 瞬时故障指数退避重试

## 🏗 系统架构
```text
用户请求
    │
    ▼
调度总管智能体
    │
    ├── 日历智能体
    │      ├── 获取当前时间
    │      ├── 校验占用时段
    │      └── 幂等创建日历事件
    │
    └── 邮件智能体
           └── 幂等发送邮件
```

## 🔁 幂等设计规则
每次工具调用生成唯一标识键：
```python
md5(user_id + tool_name + parameters)
```
任务状态流转
- `running`：任务执行中
- `done`：返回缓存结果
- `failed`：允许重试调用

## 📦 使用示例
### 📧 单发邮件
```python
user_request = "Send a test email to xxx@qq.com"
```

### 📅 多步骤组合流程
```python
user_request = """
Schedule a meeting on Wednesday at 10 AM for 1 hour,
and send a reminder email to the design team.
"""
```

## 🧪 项目启动
```bash
python subagent_tutorial.py
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

## 📊 日志样例
```log
trace_id=xxx [send_email] start execution event_key=...
trace_id=xxx idempotent hit event_key=...
trace_id=xxx middleware: handle_tool_errors triggered
```

## 🧠 技术栈
- LangChain
- LangGraph
- GLM-4.5-Flash
- 飞书开放平台 API
- Python SMTP
- ContextVars 链路追踪

## 🔥 项目亮点
具备生产级智能体工程设计能力：
- 多智能体协同编排
- 工具调用幂等保障
- 全链路可观测追踪
- 人机介入可控流程
- 完善健壮异常处理

## 🚀 后续优化方向
- 基于 Redis 实现分布式幂等控制
- 异步并发工具调用（asyncio / httpx）
- 接入 OpenTelemetry 标准观测
- 可视化网页审批控制台
- 消息队列事件驱动架构（Kafka / RabbitMQ）