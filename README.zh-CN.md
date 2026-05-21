# 🧠 多智能体工具调用系统（LangGraph + LangChain）
中文版：README.zh-CN.md

## 📌 项目概述
本项目基于**LangGraph**与**LangChain**打造生产级多智能体编排系统，支持工具调用、子智能体协同、幂等操作、链路观测与人机交互流程。

适用实际自动化业务场景：
- 日程日历排布
- 邮件自动化处理
- 多智能体协同任务调度

## 🚀 功能特性
### 🧩 多智能体架构
- **调度总管智能体**：任务拆解与流程统筹
- **日历智能体**：日程规划与日历操作
- **邮件智能体**：邮件撰写与消息发送

### 🛠 工具体系
- `create_calendar_event` — 对接飞书日历创建事件
- `send_email` — 基于SMTP协议发送邮件
- `get_not_available_time_slots` — 时间冲突检测
- `get_current_datetime` — 获取系统当前时间

### 🔁 幂等防护层
避免工具重复执行，核心能力：
- 基于哈希算法生成唯一事件标识
- 任务状态：执行中、已完成、执行失败
- 安全重试机制
- 拦截重复请求

### 📊 可观测能力
- 全链路**trace_id**统一传递
- 标准化结构化日志
- 中间件层级执行轨迹追踪
- 工具调用操作审计日志

### 🧠 上下文管理
- 对话内容摘要中间件
- 子智能体上下文注入
- 依托**LangGraph**共享运行状态

### 👤 人机交互流程(HITL)
- 中断式工具审批机制
- 支持执行动作审批、驳回、编辑修改
- 敏感操作安全管控执行

### 🔄 异常处理方案
- **业务异常**：依靠大模型推理自主恢复
- **致命异常**：触发人工介入处理
- 瞬时故障采用指数退避重试策略

## 🏗 系统架构
```text
用户请求
     │
     ▼
调度总管智能体
     │
     ├── 日历智能体
     │      ├── 获取当前时间
     │      ├── 检测占用时段
     │      └── 幂等创建日历事件
     │
     └── 邮件智能体
            └── 幂等发送邮件
```

## 🔁 幂等设计规则
每次调用工具都会生成唯一标识密钥：
```python
md5(user_id + tool_name + parameters)
```

**执行状态说明**
- running → 任务正在运行
- done → 返回缓存结果
- failed → 允许重新尝试调用

## 📦 使用示例
### 📧 发送邮件
```python
user_request = "向xxx@qq.com发送测试邮件"
```

### 📅 多步骤业务流程
```python
user_request = """
周三上午十点召开一小时会议，
并向设计团队发送会议提醒邮件。
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

## 📊 日志示例
```log
trace_id=xxx [send_email] 开始执行 event_key=...
trace_id=xxx 命中幂等缓存 event_key=...
trace_id=xxx 中间件：触发工具异常处理
```

## 🧠 技术栈
- **LangChain**
- **LangGraph**
- **GLM-4.5-Flash**
- 飞书开放接口
- Python SMTP
- ContextVars 链路追踪

## 🔥 项目亮点
具备**生产级**智能体工程设计水准：
- 多智能体协同编排
- 工具调用幂等性保障
- 全流程可追溯查询
- 可干预式人机交互流程
- 稳定可靠的异常处理机制

## 🚀 后续优化方向
- 接入Redis实现分布式幂等控制
- 基于asyncio/httpx实现异步工具调用
- 集成OpenTelemetry标准化监控
- 搭建网页版审批管理面板
- 基于Kafka/RabbitMQ搭建事件驱动架构