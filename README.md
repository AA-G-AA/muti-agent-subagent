🧠 Multi-Agent Tool-Calling System (LangGraph + LangChain)
📌 Overview
This project is a production-style multi-agent orchestration system built with LangGraph and LangChain.
It supports tool execution, sub-agent coordination, idempotent operations, observability, and human-in-the-loop workflows.
The system is designed for real-world automation scenarios such as:
Calendar scheduling
Email automation
Task coordination across multiple agents
🚀 Features
🧩 Multi-Agent Architecture
Supervisor Agent: Task decomposition and orchestration
Calendar Agent: Scheduling and calendar operations
Email Agent: Email composition and delivery
🛠 Tool System
create_calendar_event – Feishu Calendar integration
send_email – SMTP-based email sending
get_not_available_time_slots – Conflict detection
get_current_datetime – Time utilities
🔁 Idempotency Layer
Prevents duplicate execution of tool calls.
Key capabilities:
Deterministic event key generation (hash-based)
Execution states: running, done, failed
Safe retry handling
Duplicate request suppression
📊 Observability
End-to-end trace_id propagation
Structured logging support
Middleware-level execution tracing
Tool invocation audit logs
🧠 Context Management
Conversation summarization middleware
Sub-agent context injection
Shared runtime state via LangGraph
👤 Human-in-the-Loop (HITL)
Interrupt-based tool approval workflow
Approve / reject / edit execution actions
Safe execution for sensitive operations
🔄 Error Handling Strategy
BusinessError: Recoverable via LLM reasoning
FatalError: Requires manual intervention
Exponential backoff retry middleware for transient failures
🏗 Architecture
plaintext
User Request
     │
     ▼
Supervisor Agent
     │
     ├── Calendar Agent
     │      ├── get_current_datetime
     │      ├── get_not_available_time_slots
     │      └── create_calendar_event (idempotent)
     │
     └── Email Agent
            └── send_email (idempotent)
🔁 Idempotency Design
Each tool invocation generates a deterministic key:
plaintext
md5(user_id + tool_name + parameters)
Execution States
running → task in progress
done → cached result returned
failed → retry allowed
📦 Example Usage
📧 Send Email
python
运行
user_request = "Send a test email to xxx@qq.com"
📅 Multi-Step Workflow
python
运行
user_request = """
Schedule a meeting on Wednesday at 10 AM for 1 hour,
and send a reminder email to the design team.
"""
🧪 Run the Project
bash
运行
python subagent_tutorial.py
⚙️ Environment Variables
env
EMAIL_SENDER=xxx@qq.com
EMAIL_PASSWORD=xxx

CALENDER_BOT_APP_SECRET=xxx
SHARE_CALENDER=xxx

OPENAI_GLM_API_KEY=xxx
OPENAI_GLM_BASE_URL=xxx
📊 Logging Example
log
trace_id=xxx [send_email] start execution event_key=...
trace_id=xxx idempotent hit event_key=...
trace_id=xxx middleware: handle_tool_errors triggered
🧠 Tech Stack
LangChain
LangGraph
GLM-4.5-Flash
Feishu Open API
Python SMTP
ContextVars for tracing
🔥 Highlights
This system demonstrates production-grade agent design:
Multi-agent orchestration
Idempotent tool execution
End-to-end traceability
Human-in-the-loop control flow
Robust error handling strategy
🚀 Future Improvements
Redis-based distributed idempotency
Async tool execution (asyncio / httpx)
OpenTelemetry integration
Web-based approval dashboard
Event-driven architecture (Kafka / RabbitMQ)