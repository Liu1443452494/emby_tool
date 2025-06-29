# backend/log_manager.py (修改后)
import logging
import asyncio
import re
from logging import Handler, LogRecord
from typing import List, Dict, Any
from fastapi import WebSocket
from datetime import datetime
import os

# --- 新增：自定义日志格式化器，用于文件和控制台 ---
class CustomLogFormatter(logging.Formatter):
    """
    自定义日志格式化器，用于生成对齐的、带任务类别的日志。
    格式: LEVEL:      TIMESTAMP          - CATEGORY      → MESSAGE
    """
    def format(self, record: LogRecord) -> str:
        level_name = record.levelname
        # 为了对齐，给不同长度的级别名后面加不同数量的空格
        level_str = f"{level_name}:".ljust(9)

        timestamp_str = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
        
        # 从记录中获取任务类别，如果没有则默认为'系统日志'
        task_category = getattr(record, 'task_category', '系统日志')
        # 将任务类别填充到15个字符宽度，中文占位更宽，所以用字节长度近似或固定宽度
        # 这里我们用简单的 ljust，对于大部分场景足够
        category_str = task_category.ljust(12)

        message = record.getMessage()
        
        return f"{level_str} {timestamp_str} - {category_str} → {message}"

# --- 修改：UILogger 以便传递 task_category ---
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

# --- 修改：WebSocketLogHandler 以发送新的结构化数据 ---
class WebSocketLogHandler(Handler):
    def __init__(self):
        super().__init__()
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.get_event_loop()

    def emit(self, record: LogRecord):
        # 只广播需要在前端显示的日志
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

# --- 修改：setup_logging 以使用新的 Formatter ---
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
    
    # 使用新的自定义 Formatter
    log_format = CustomLogFormatter()
    
    # 文件处理器
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    # WebSocket 处理器 (它自己处理格式，不需要 Formatter)
    websocket_handler = WebSocketLogHandler()
    root_logger.addHandler(websocket_handler)

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    root_logger.addHandler(console_handler)
    
    logging.info("日志系统已成功初始化。", extra={'task_category': '系统启动'})