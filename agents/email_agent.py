#agents/email_agent.py
from langchain.agents import create_agent

import storage
from config import _trace_id_var, model
from middleware import handle_tool_errors
from tools.email_tool import send_email

EMAIL_AGENT_PROMPT = (
    "You are an email assistant. "
    "Compose professional emails based on natural language requests. "
    "Extract recipient information and craft appropriate subject lines and body text. "
    "Use send_email to send the message. "
    "Always confirm what was sent in your final response."
)

email_agent = create_agent(
    model,
    tools=[send_email],
    middleware=[
        handle_tool_errors,
    ],
    system_prompt=EMAIL_AGENT_PROMPT,
    store=storage.store,
    checkpointer=None,
    name="email_agent"
    # checkpointer=InMemorySaver(),
)