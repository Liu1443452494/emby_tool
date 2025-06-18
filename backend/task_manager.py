# backend/task_manager.py (完整代码)

import asyncio
import uuid
import threading
import logging
import queue
import time
from datetime import datetime
from typing import Dict, List, Callable, Any, Optional
from fastapi import WebSocket
from pydantic import BaseModel

class TaskInfo(BaseModel):
    id: str
    name: str
    status: str
    start_time: str
    progress: int = 0
    total: int = 0
    result: Optional[Any] = None

class TaskBroadcaster:
    def __init__(self):
        self.connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def broadcast(self, data: List[Dict]):
        for connection in self.connections:
            await connection.send_json(data)

class TaskManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.tasks: Dict[str, Dict[str, Any]] = {}
            self.broadcaster = TaskBroadcaster()
            self.update_queue = queue.Queue()
            self.loop = None 
            self.initialized = True

    def _broadcast_update(self):
        self.update_queue.put("UPDATE")

    async def broadcast_consumer(self):
        self.loop = asyncio.get_running_loop()
        logging.info("任务广播消费者的事件循环已成功获取。")
        while True:
            try:
                self.update_queue.get_nowait()
                task_list = self.get_all_tasks()
                if self.loop and not self.loop.is_closed():
                    asyncio.run_coroutine_threadsafe(self.broadcaster.broadcast(task_list), self.loop)
            except queue.Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                logging.error(f"任务广播时发生错误: {e}")
                await asyncio.sleep(1)

    def update_task_progress(self, task_id: str, progress: int, total: int):
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id]['progress'] = progress
                self.tasks[task_id]['total'] = total
        self._broadcast_update()

    # --- 核心修改 3: 新增一个用于实时更新结果的方法 ---
    def update_task_result(self, task_id: str, result: Any):
        """实时更新任务的结果字段，并立即广播。"""
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id]['result'] = result
        self._broadcast_update()

    def _run_task_wrapper(self, task_id: str, target: Callable, *args, **kwargs):
        cancellation_event = self.tasks[task_id]['cancellation_event']
        task_result = None
        final_status = 'completed'

        try:
            task_result = target(*args, cancellation_event=cancellation_event, task_id=task_id, task_manager=self, **kwargs)
            if cancellation_event.is_set():
                final_status = 'cancelled'
                logging.info(f"任务 '{self.tasks[task_id]['name']}' (ID: {task_id}) 已被取消。")
            else:
                logging.info(f"任务 '{self.tasks[task_id]['name']}' (ID: {task_id}) 已成功完成。")
        except Exception as e:
            final_status = 'failed'
            logging.error(f"任务 '{self.tasks[task_id]['name']}' (ID: {task_id}) 失败: {e}", exc_info=True)
        finally:
            with self._lock:
                if task_id in self.tasks:
                    self.tasks[task_id]['status'] = final_status
                    self.tasks[task_id]['result'] = task_result
            
            self._broadcast_update()
            
            def cleanup_task():
                with self._lock:
                    if task_id in self.tasks:
                        del self.tasks[task_id]
                self._broadcast_update()
                logging.info(f"已清理已完成的任务: {task_id}")

            threading.Timer(10.0, cleanup_task).start()

    def register_task(self, target: Callable, name: str, *args, **kwargs) -> str:
        task_id = str(uuid.uuid4())
        cancellation_event = threading.Event()
        with self._lock:
            self.tasks[task_id] = {
                'id': task_id,
                'name': name,
                'status': 'running',
                'start_time': datetime.now().isoformat(),
                'cancellation_event': cancellation_event,
                'progress': 0,
                'total': 0,
                'result': None,
            }
        logging.info(f"注册新任务: '{name}' (ID: {task_id})")
        thread = threading.Thread(target=self._run_task_wrapper, args=(task_id, target, *args), kwargs=kwargs)
        thread.start()
        self._broadcast_update()
        return task_id

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self.tasks and self.tasks[task_id]['status'] == 'running':
                self.tasks[task_id]['cancellation_event'].set()
                self.tasks[task_id]['status'] = 'cancelling'
                logging.info(f"正在取消任务 '{self.tasks[task_id]['name']}' (ID: {task_id})")
                self._broadcast_update()
                return True
        return False

    def get_all_tasks(self) -> List[Dict]:
        with self._lock:
            return [
                {
                    "id": data["id"],
                    "name": data["name"],
                    "status": data["status"],
                    "start_time": data["start_time"],
                    "progress": data["progress"],
                    "total": data["total"],
                    "result": data.get("result")
                }
                for data in self.tasks.values()
            ]

task_manager = TaskManager()