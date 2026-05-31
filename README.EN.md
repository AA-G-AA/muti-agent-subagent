# 🧠 Multi-Agent Tool-Calling System (LangGraph + LangChain)

🌐 Language / 语言：

- 🇨🇳 中文: [README](./README.md)
- 🇺🇸 English: [README_EN.md](./README.EN.md)

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
* PostgreSQL (Long-term memory Store)
* tenacity (Network retry)

## 🔥 Project Highlights (Why is it Production-Grade?)

Moving LLMs from demo toys to enterprise production lines requires engineering design for **data determinism, system idempotency, long-term memory, and link observability**. This project implements the following core designs to address deep-water pain points such as FSM split, model hallucination, and tool infinite-loop concurrency conflicts in multi-agent orchestration:

### 1. Deterministic Rule Gateway —— Eliminating LLM "Hallucinated" Conflicts

* **Business Pain Point**: Traditional Agents rely entirely on LLM reasoning to determine time conflicts. Affected by model hallucination, this easily causes time overlaps and logical dead loops in calendar scheduling.
* **Architectural Design**: The project completely strips away the "initial review right" of generative LLMs over sensitive boundary conditions, building a pure Python hard-coded **time interval geometric interception gateway**.
* **Impact**: Uses the geometric intersection algorithm `max(req_start, slot_start) < min(req_end, slot_end)` for strict mathematical verification, intercepting 100% of schedule overlaps before the tool layer to achieve **deterministic circuit breaking** at the business level.

### 2. Lifecycle Stream Auditor —— Resolving Agent "Split-Personality" Auditing

* **Business Pain Point**: In "Supervisor-SubAgent" collaborations, sub-agents often output natural language text rich with emojis or casual phrasing. Traditional single-message interception mechanisms can easily misinterpret this as a failed tool invocation, triggering false-positive system circuit breaking.
* **Architectural Design**: Reengineered the Supervisor Agent's auditing operator to use a **lifecycle message full-dimensional scanning mechanism** cascaded via `ContextVars`.
* **Impact**: Dynamically captures and purges status streams across agent nodes, resolving FSM conflicts and split-personality issues in the multi-agent collaboration chain to ensure **strong consistency** in pipeline throughput.

### 3. Multi-Dimensional Business Salting Hash —— Distributed Concurrency Idempotency Protection Layer (Idempotent Shield)

* **Business Pain Point**: Generative LLM text is inherently random. If network jitter, front-end user double-clicks, or LLM dead loops cause duplicate tool invocations, traditional text-hash-based deduplication fails completely since a few changed characters alter the hash.
* **Architectural Design**: Developed a custom `@idempotent` decorator using a **core business dimension extraction algorithm**. It extracts `User + Time + Title` for calendar locks and `To_List + Subject` for email locks to calculate a salted MD5 hash, combined with Redis for distributed lease mutual exclusion.
* **Impact**: Establishes a standard FSM lifecycle (`running` lock acquisition / `done` cache hit interception / `failed` auto-release with exponential backoff retries). Even if the LLM changes its phrasing in descriptions, the system precisely blocks duplicates.

### 4. Full-Chain Crash-Proof Architecture & Strong Type Conversion Mechanism

* **Business Pain Point**: During multi-agent context exchanges, complex formats returned by underlying tools (such as JSON strings) can be incorrectly recognized as primitive characters after multi-turn conversation truncation, triggering implicit type slicing errors (Slice Fragmentation Bug).
* **Architectural Design**: Implements a strict type defense mechanism across the entire chain, establishing a closed-loop gateway of `JSON Str ── json.loads() ── Python Native List` at all state transition nodes.
* **Impact**: Eliminates implicit exceptions before they reach tool execution entry points, equipping the system with high fault tolerance and crash-proof data handling capabilities.

---

## 🧠 Multi-Agent Collaboration & Tool Protection Capabilities

* ▪ **Dual Defense Matrix**: First Line of Defense: Python mathematical interval rule gateway ── Second Line of Defense: Redis distributed lease mutual exclusion lock.
* ▪ **Lifecycle Trace Auditing**: Propagates `trace_id` uniformly based on link context, ensuring 100% compatibility with casual natural language sub-agent responses.
* ▪ **Long-Term Preference Memory**: Relies on the LangGraph Store mechanism to achieve non-blocking asynchronous writing of user preferences across sessions.
* ▪ **Human-In-The-Loop (HITL) Safety Sandbox**: Supports layer-level interruption and suspension for sensitive operations (email/calendar modifications), providing controllable human-agent collaboration through online editing, rejection, and re-confirmation.
* ▪ **Full-Chain Async Base**: Built on asyncio + httpx for completely asynchronous toolchains, bypassing the serial blocking performance bottlenecks of traditional AI orchestration.

---

### 📊 Execution Verification

## 🚀 Future Roadmap

* [√] **Distributed Idempotency Control**: Integrate Redis to implement distributed locking and cache expiration self-healing mechanisms.
* [√] **Full-Chain Async Evolution**: Refactor toolchains with asyncio/httpx for non-blocking asynchronous execution.
* [ ] **Persistent Preference Memory**: Introduce the LangGraph Store mechanism to achieve non-blocking asynchronous writing and long-term storage of user preferences.
* [ ] **Separated Front-End Chat (Web-UI)**: Build backend APIs with FastAPI (Async) and utilize WebSocket / SSE (Server-Sent Events) to achieve a ChatGPT-like streaming typewriter conversation effect.
* [ ] **Dynamic Interactive Approval Flow & Lock Management**: Combine LangGraph's HITL mechanism to push an interactive approval card component to the front-end when sensitive tools are triggered, while integrating a Redis key management dashboard to manually release idempotency locks.
* [ ] **Full-Chain Async Latency Tracking (OpenTelemetry)**: Integrate OTel into FastAPI to graphically trace the latency profile across the "User Prompt -> Agent Orchestration -> Tool Invocation -> Model Response" lifecycle, pinning down front-end lag bottlenecks.
* [ ] **High-Concurrency Multi-User Queue (Message Queue Shaving)**: Introduce RabbitMQ / Kafka to handle chat event streams asynchronously, performing peak shaving for high-concurrency requests to ensure Agent system stability under heavy user loads.