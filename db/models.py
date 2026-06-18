# db/models.py
import logging
from db import get_pool

logger = logging.getLogger(__name__)

CREATE_SESSIONS_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL DEFAULT 'default',
    title VARCHAR(255) NOT NULL DEFAULT '新对话',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

CREATE_MESSAGES_SQL = """
CREATE TABLE IF NOT EXISTS messages (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    thread_id VARCHAR(64) NOT NULL,
    role ENUM('user', 'assistant') NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_thread_id (thread_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


async def init_tables():
    """初始化表（如果不存在则创建）"""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 检查 sessions 表是否存在
            await cur.execute("""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                AND table_name = 'sessions'
            """)
            exists = (await cur.fetchone())[0] > 0

            if exists:
                logger.info("📦 表已存在，跳过初始化")
                return

            # 表不存在才建表
            await cur.execute(CREATE_SESSIONS_SQL)
            await cur.execute(CREATE_MESSAGES_SQL)
            logger.info("✅ MySQL 表初始化完成")