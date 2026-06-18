# ============================================================
# 📌 开发过程中的概念验证文件
# 用途：WebSocket 简单连通性测试（端口 6001）
# 状态：保留作思路参考，不影响主程序运行
# ============================================================

import asyncio
import uvicorn
from fastapi import FastAPI, WebSocket, APIRouter

app = FastAPI()
router = APIRouter()

@router.websocket('/ws/chat')
async def ws(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text('{"test": "ok"}')
    while True:
        data = await websocket.receive_text()
        await websocket.send_text('{"reply": "收到了: "}')

app.include_router(router)
uvicorn.run(app, host='0.0.0.0', port=6001)