# config.py
import os
import dotenv
from pathlib import Path
from langchain.chat_models import init_chat_model
import logging
import contextvars

_trace_id_var = contextvars.ContextVar("trace_id", default="no-trace")

class TraceIdFilter(logging.Filter):
    def filter(self, record):
        record.trace_id = _trace_id_var.get()
        return True
# 不用 basicConfig，手动配置
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] trace_id=%(trace_id)s %(name)s - %(message)s"
))
handler.addFilter(TraceIdFilter())# Filter 加在 handler 上

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(handler)

dotenv.load_dotenv(Path(__file__).parent / ".env")

# 环境变量校验
_required = ["OPENAI_BASE_URL", "OPENAI_API_KEY", "EMAIL_SENDER",
             "EMAIL_PASSWORD", "SHARE_CALENDER", "CALENDER_BOT_APP_SECRET"]
_missing = [k for k in _required if not os.getenv(k)]
if _missing:
    raise RuntimeError(f"缺少必要的环境变量：{', '.join(_missing)}")

DB_VECTOR = os.getenv("DB_URL") or "postgresql://postgres:postgres@localhost:5432/postgres"
REDIS_URI = os.getenv("REDIS_URI") or "redis://localhost:6379"

model = init_chat_model(
    base_url=os.getenv("OPENAI_BASE_URL"),
    api_key=os.getenv("OPENAI_API_KEY"),
    model_provider="openai",
    model="GLM-4.5-Flash",
    profile={"max_input_tokens": 128000},
    temperature=0.1,
    timeout=120,
)


# os.environ["LANGSMITH_TRACING"] = os.getenv("LANGSMITH_TRACING")
# os.environ["LANGSMITH_API_KEY"] = os.getenv("LANGSMITH_API_KEY")
