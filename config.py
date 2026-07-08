# config.py
import os
import dotenv
from pathlib import Path
from langchain.chat_models import init_chat_model
import logging
import contextvars

from langchain_ollama import OllamaEmbeddings

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

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
MYSQL_DB = os.getenv("MYSQL_DB", "muti_agent")

model = init_chat_model(
    base_url=os.getenv("OPENAI_BASE_URL"),
    api_key=os.getenv("OPENAI_API_KEY"),
    model_provider="openai",
    model="deepseek-v4-flash",
    profile={"max_input_tokens": 128000},
    temperature=0.1,
    timeout=120,
)
verifier_model = init_chat_model(
    base_url=os.getenv("OPENAI_BASE_URL"),
    api_key=os.getenv("OPENAI_API_KEY"),
    model_provider="openai",
    model="deepseek-v4-flash",
    temperature=0.1,
    timeout=120,
)
memory_model = init_chat_model(
    base_url=os.getenv("OPENAI_BASE_URL"),
    api_key=os.getenv("OPENAI_API_KEY"),
    model_provider="openai",
    model="deepseek-v4-flash",
    temperature=0.1,
    timeout=120,
)
embedding = OllamaEmbeddings(
    model="bge-m3:latest",
    base_url="http://localhost:11434",
)
# ===== Mock 模式 =====
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"

if MOCK_MODE:
    from langchain_core.language_models import FakeListChatModel
    model = FakeListChatModel(responses=["你好！我是你的 AI 助手。"])
    print("🧪 Mock 模式启动")
# os.environ["LANGSMITH_TRACING"] = os.getenv("LANGSMITH_TRACING")
# os.environ["LANGSMITH_API_KEY"] = os.getenv("LANGSMITH_API_KEY")
