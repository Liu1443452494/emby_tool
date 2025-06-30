# backend/log_manager.py (修改后)
import logging
import asyncio
import re
from logging import Handler, LogRecord
from typing import List, Dict, Any
from fastapi import WebSocket
from datetime import datetime
import os

# --- 核心修改：优化自定义日志格式化器 ---
class CustomLogFormatter(logging.Formatter):
    """
    自定义日志格式化器，用于生成对齐的、带任务类别的日志。
    格式: LEVEL:    TIMESTAMP          - CATEGORY        → MESSAGE
    """
    def format(self, record: LogRecord) -> str:
        level_name = record.levelname
        # 为了对齐，给不同长度的级别名后面加不同数量的空格
        level_str = f"{level_name}:".ljust(9) # 例如 "DEBUG:" 是7个字符，"INFO:" 是5个，ljust(9) 保证右侧对齐

        timestamp_str = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
        
        # 从记录中获取任务类别，如果没有则默认为'系统日志'
        task_category = getattr(record, 'task_category', '系统日志')
        # 将任务类别填充到固定的宽度，以保证对齐
        category_str = task_category.ljust(25)

        message = record.getMessage()
        
        return f"{level_str} {timestamp_str} - {category_str} → {message}"

# --- UILogger 保持不变 ---
class UILogger:
    """
    一个简单的包装器，用于发送需要在前端显示的日志。
    """
    def __init__(self, logger_name='root'):
        self.logger = logging.getLogger(logger_name)

    def info(self, msg, *args, task_category: str = "系统日志", **kwargs):
        self.logger.info(msg, *args, extra={'show_on_frontend': True, 'task_category': task_category}, **kwargs)
    
    def warning(self, msg, *args, task_category: str = "系统日志", **kwargs):
        self.logger.warning(msg, *args, extra={'show_on_frontend': True, 'task_category': task_category}, **kwargs)

    def error(self, msg, *args, task_category: str = "系统日志", **kwargs):
        self.logger.error(msg, *args, extra={'show_on_frontend': True, 'task_category': task_category}, **kwargs)

    def debug(self, msg, *args, task_category: str = "系统日志", **kwargs):
        self.logger.debug(msg, *args, extra={'show_on_frontend': True, 'task_category': task_category}, **kwargs)


ui_logger = UILogger()

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

# --- WebSocketLogHandler 保持不变 ---
class WebSocketLogHandler(Handler):
    def __init__(self):
        super().__init__()
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.get_event_loop()

    def emit(self, record: LogRecord):
        if not getattr(record, 'show_on_frontend', False):
            return

        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S,%f')[:-3],
            "level": record.levelname,
            "category": getattr(record, 'task_category', '系统日志'),
            "message": record.getMessage()
        }
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(asyncio.create_task, broadcaster.broadcast(log_data))

# --- setup_logging 保持不变，因为它已经使用了新的 Formatter ---
def setup_logging():
    DATA_DIR = "/app/data"
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    LOG_FILE = os.path.join(DATA_DIR, "app.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG) 

    if root_logger.hasHandlers():
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
    
    log_format = CustomLogFormatter()
    
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    websocket_handler = WebSocketLogHandler()
    root_logger.addHandler(websocket_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    root_logger.addHandler(console_handler)
    
    logging.info("日志系统已成功初始化。", extra={'task_category': '系统启动'})