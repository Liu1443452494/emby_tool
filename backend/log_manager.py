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



class WebSocketLogHandler(Handler):
    def __init__(self):
        super().__init__()
        # --- 核心修改：回到在初始化时获取事件循环 ---
        # 我们将确保这个类的实例总是在主线程中创建
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            # 如果在没有事件循环的线程中被错误地初始化，
            # 先获取主线程的事件循环策略，再获取循环实例。
            # 这是为了兼容某些特殊启动场景。
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
        
        # self.loop 此时一定存在且正确
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(asyncio.create_task, broadcaster.broadcast(log_data))




def setup_logging(add_websocket_handler: bool = True):
    LOGS_DIR = "/app/data/logs"
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)
    LOG_FILE = os.path.join(LOGS_DIR, "app.log")

    # 定义日志保留天数常量
    LOG_BACKUP_COUNT = 5

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG) 

    handlers = root_logger.handlers[:]
    for handler in handlers:
        handler.close()
        root_logger.removeHandler(handler)
    
    log_format = CustomLogFormatter()
    
    file_handler = logging.handlers.TimedRotatingFileHandler(
        LOG_FILE, 
        when='D', 
        interval=1, 
        backupCount=LOG_BACKUP_COUNT, 
        encoding='utf-8'
    )
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    if add_websocket_handler:
        websocket_handler = WebSocketLogHandler()
        root_logger.addHandler(websocket_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    root_logger.addHandler(console_handler)
    
    # --- 核心修改：精细化控制第三方库的日志级别 ---
    # 将最底层的 httpcore 设置为 WARNING，以屏蔽大量 DEBUG 日志
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    # 保持 httpx 为 INFO，以便看到有用的请求摘要日志
    logging.getLogger("httpx").setLevel(logging.INFO)
    
    # 调整 uvicorn 的日志级别以获得更简洁的输出
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO) # Access日志可以保留INFO
    # --- 修改结束 ---
    logging.getLogger('PIL').setLevel(logging.INFO)
    if add_websocket_handler:
        ui_logger.info(f"✅ 日志系统已成功初始化 (每日滚动，保留{LOG_BACKUP_COUNT}天)。", task_category='系统启动')