
# 🧠 Multi-Agent Tool-Calling System (LangGraph + LangChain)

🌐 Language / 语言：

* 🇺🇸 English: [README](https://www.google.com/search?q=./README.md)
* 🇨🇳 中文: [README.zh-CN.md](https://www.google.com/search?q=./README.zh-CN.md)

## 📌 Project Overview

This project is a production-grade Multi-Agent orchestration system built on **LangGraph** and **LangChain**. Deeply integrated with a **Redis distributed lock**, it implements deterministic idempotency protection for tool calling, hard-coded code gateway interception, full-link observability, and Human-In-The-Loop (HITL) workflows.

**Applicable Real-world Automation Scenarios:**

* Enterprise-level intelligent calendar & schedule arrangement.
* Automated email workflow processing & semantic-de-noising debt collection.
* Cross-platform distributed Multi-Agent collaborative task scheduling.

## 🚀 Features

### 🧩 Multi-Agent Architecture

* **Supervisor Agent**: Responsible for dynamic task decomposition, routing distribution, and global workflow orchestration.
* **Calendar Agent**: Focuses on schedule planning, busy/free status analysis, and precise calendar event writing.
* **Email Agent**: Focuses on email body polishing, recipient list composition, and asynchronous delivery.

### 🛠 Tools & Hard-coded Defense System

* `Calendar` — Interfaces with the Feishu (Lark) Calendar API to create events (**Built-in Python deterministic interval interception gateway**).
* `send_email` — An asynchronous email delivery tool based on the SMTP protocol.
* `get_current_datetime` — Provides the system's real-time ISO timestamp as a baseline to eliminate LLM hallucinations.
* `get_not_available_time_slots` — (Internal Defense Function) Dynamically fetches the latest busy time slots and returns a pure Python list for seamless deserialization at the tool layer.

### 🔁 Distributed Idempotency Protection Layer

Powered by a custom `@idempotent` decorator to fully intercept duplicate tool invocations caused by network jitter, user double-clicks, or LLM dead loops:

* **Dynamic Hashing Strategy**: Generates a unique MD5 key based on specific business dimensions (e.g., `User + Time + Title`), blocking interference from the randomness of generative LLM text.
* **Finite State Machine Lifecycle**: Supports `running` (lock acquired & executing), `done` (cache hit, direct return), and `failed` (failed execution, auto-released for retries).
* **Cascade Cleanup Mechanism**: Supports delete actions to actively erase corresponding Redis idempotency locks, ensuring strong consistency with the real world.

### 📊 Observability & Operations Auditing

* Universal propagation of **trace_id** across the entire call chain (cascaded via ContextVars).
* Strict **Tool Operation Auditing Logs**: Scans the full lifecycle messages of the Supervisor Agent to prevent a sub-agent's natural language responses from breaking successful workflows.
* Middleware-level (`handle_tool_errors`) cascade execution trajectory tracking.

### 🧠 Context Management

* Conversation summary middleware to dynamically prune the context window.
* Relies on **LangGraph State** to achieve transparent shared-state communication between multiple agents.

### 👤 Human-In-The-Loop (HITL)

* Interrupted tool approval mechanism, supporting online approval, rejection, and dynamic editing for sensitive operations (e.g., sending emails, batch calendar modifications).

### 🔄 Exception Handling Schemes

* **Business Error (`BusinessError`)**: Propagated upward to the LLM, triggering the model's autonomous reasoning for clarification or retries (e.g., prompting the user to change a conflicting time).
* **Fatal Error (`FatalError`)**: Terminates the pipeline immediately and triggers manual intervention.

## 🏗 System Architecture & Execution Flow

```text
               User Request
                    │
                    ▼
          Supervisor Agent
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
  Calendar Agent           Email Agent
        │                       │
 (Code Gateway Defense)   (SMTP Async Delivery)
  ├── Get Current Time     └── 🔑 Redis Idempotent Lock
  ├── 🛡️ Real-time Conflict Interception
  └── 🔑 Redis Idempotent Creation

```

## 🔁 Idempotency & Gateway Design Rules

### 1. Core Hashing Formula

For every tool invocation, the middleware calculates an MD5 hash based on **core business dimensions**:

```python
# Calendar Lock: Locks the time interval; LLM description tweaks won't bypass the lock
md5(user_id + title + start_time + end_time)

# Email Lock: Locks the recipients and the subject
md5(user_id + to_list + cc_list + subject + body)

```

### 2. Dual-Defense Workflow

1. **First Line of Defense (Code Gateway)**: The tool internally fetches busy time slots, deserializes them safely using `json.loads()`, and runs a mathematical check via the intersection formula: `max(req_start, slot_start) < min(req_end, slot_end)`. If they overlap, a `BusinessError` is raised immediately.
2. **Second Line of Defense (Redis Lock)**: After passing the gateway, the middleware attempts to acquire the lock (`r.set(redis_key, ..., nx=True)`). If successful, it runs the core logic; if it hits an existing lock, it intercepts the call and returns the cached result.

## 📦 Usage Examples

### 📅 Multi-Step Composite Workflow Test

```python
user_request = """
Set up a 1-hour meeting with the finance team at 3:00 PM tomorrow. 
The subject is "Finance Meeting", the description is "Submit new financial reports", 
and the location is Room 311. 
Also, send a reminder email to xxxx@qq.com asking them to hurry up and submit the new reports.
"""

```

## 🧪 Getting Started

```bash
python sub.py

```

## ⚙️ Environment Variables Configuration

```env
EMAIL_SENDER=xxx@qq.com
EMAIL_PASSWORD=xxx

CALENDER_BOT_APP_SECRET=xxx
SHARE_CALENDER=xxx

OPENAI_GLM_API_KEY=xxx
OPENAI_GLM_BASE_URL=xxx

```

## 📊 Real Audit Log Snippet

```log
trace_id=... [create_calendar_event] Attempting to acquire lock redis_key=idempotent:3963f769ea...
trace_id=... [create_calendar_event] 🎯 Idempotency hit, returning cached result directly
trace_id=... agents.supervisor_agent - Last AI message from calendar_agent...
trace_id=... 🛡️ Code Gateway: Successfully extracted busy slots from context: ["09:00-10:00", "14:00-15:00"]

```

## 🧠 Tech Stack

* **LangChain & LangGraph (v0.2+)**
* **GLM-4.5-Flash** (Compatible call via OpenAI Adapter)
* **Redis** (Core component for distributed locking and result caching)
* Feishu Calendar Open API (Tenant Access Token Bot Authentication)
* Python SMTP / asyncio / httpx

## 🔥 Project Highlights (Why is it Production-Grade?)

1. **Eliminating LLM "Hallucinated" Conflicts**: Time conflict detection is stripped away from the LLM and offloaded to a deterministic Python code gateway, ensuring 100% interception of overlapping schedules.
2. **Resolving Agent "Split-Personality" Auditing**: The supervisor's audit uses full-lifecycle chain scanning. Even if a sub-agent reports back in casual natural language, it won't trigger a false-positive "tool not called" hard-circuit break.
3. **Crash-Proof Data Type Design**: Strictly enforces `JSON str ── json.loads ── Python List` conversions across the data pipeline, completely wiping out character slicing bugs and implicit exception swallowing.

### 📊 Execution Verification

## 🚀 Future Roadmap

* [√] **Distributed Idempotency Control**: Integrate Redis to implement distributed locking and cache expiration self-healing mechanisms.
* [√] **Full-Chain Async Evolution**: Refactor toolchains with asyncio/httpx for non-blocking asynchronous execution.
* [ ] **Persistent Preference Memory**: Introduce the LangGraph Store mechanism to achieve non-blocking asynchronous writing and long-term storage of user preferences.
* [ ] **Separated Front-End Chat (Web-UI)**: Build backend APIs with FastAPI (Async) and utilize WebSocket / SSE (Server-Sent Events) to achieve a ChatGPT-like streaming typewriter conversation effect.
* [ ] **Dynamic Interactive Approval Flow & Lock Management**: Combine LangGraph's HITL mechanism to push an interactive approval card component to the front-end when sensitive tools are triggered, while integrating a Redis key management dashboard to manually release idempotency locks.
* [ ] **Full-Chain Async Latency Tracking (OpenTelemetry)**：Integrate OTel into FastAPI to graphically trace the latency profile across the "User Prompt -> Agent Orchestration -> Tool Invocation -> Model Response" lifecycle, pinning down front-end lag bottlenecks.
* [ ] **High-Concurrency Multi-User Queue (Message Queue Shaving)**: Introduce RabbitMQ / Kafka to handle chat event streams asynchronously, performing peak shaving for high-concurrency requests to ensure Agent system stability under heavy user loads.

---