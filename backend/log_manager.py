# backend/log_manager.py (修改后)
import logging
import asyncio
from logging import Handler, LogRecord
from typing import List
from fastapi import WebSocket
from datetime import datetime
import os # 引入 os

class LogBroadcaster:
    def __init__(self):
        self.connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def broadcast(self, data: dict):
        for connection in self.connections:
            await connection.send_json(data)

broadcaster = LogBroadcaster()

class WebSocketLogHandler(Handler):
    def __init__(self):
        super().__init__()
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.get_event_loop()

    def emit(self, record: LogRecord):
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S,%f')[:-3],
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage()
        }
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(asyncio.create_task, broadcaster.broadcast(log_data))

def setup_logging():
    # --- 核心修改：将日志文件路径指向 /app/data ---
    DATA_DIR = "/app/data"
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    LOG_FILE = os.path.join(DATA_DIR, "app.log")
    # --- 结束修改 ---

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG) 

    if root_logger.hasHandlers():
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

    log_format_str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    log_format = logging.Formatter(log_format_str)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    websocket_handler = WebSocketLogHandler()
    root_logger.addHandler(websocket_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    root_logger.addHandler(console_handler)

    logging.info("日志系统已成功初始化。")