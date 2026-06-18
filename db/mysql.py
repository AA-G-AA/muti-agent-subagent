# db/mysql.py
import aiomysql
from config import MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB

pool = None

async def init_mysql():
    global pool
    pool = await aiomysql.create_pool(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        db=MYSQL_DB,
        charset='utf8mb4',
        autocommit=True,
        minsize=3,  # 启动时预热 3 个连接
        maxsize=46,  # 最大 46 个并发连接
    )

async def close_mysql():
    global pool
    if pool:
        pool.close()
        await pool.wait_closed()

def get_pool():
    if pool is None:
        raise RuntimeError("MySQL 连接池未初始化，请先调用 init_mysql()")
    return pool