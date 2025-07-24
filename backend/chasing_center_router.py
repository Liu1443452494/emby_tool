# backend/chasing_center_router.py (新文件)

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import List, Dict

from log_manager import ui_logger
from models import ChasingCenterConfig
from chasing_center_logic import ChasingCenterLogic
from task_manager import task_manager
import config as app_config

router = APIRouter()

def get_logic() -> ChasingCenterLogic:
    config = app_config.load_app_config()
    return ChasingCenterLogic(config)

@router.get("/config", response_model=ChasingCenterConfig)
def get_chasing_center_config():
    """获取追更中心的配置"""
    return app_config.load_app_config().chasing_center_config

@router.post("/config")
def save_chasing_center_config(config: ChasingCenterConfig):
    """保存追更中心的配置"""
    try:
        current_app_config = app_config.load_app_config()
        current_app_config.chasing_center_config = config
        app_config.save_app_config(current_app_config)
        # 这里需要一个方法来通知 main.py 中的调度器更新任务
        from main import update_chasing_scheduler
        update_chasing_scheduler()
        return {"status": "success", "message": "追更中心设置已保存！"}
    except Exception as e:
        ui_logger.error(f"❌ 保存追更中心设置失败: {e}", task_category="API-追更中心")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/list")
def get_chasing_list():
    """获取当前追更列表的详细信息"""
    try:
        logic = get_logic()
        # --- 核心修改：调用新的详细信息获取函数 ---
        return logic.get_detailed_chasing_list()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ChasingListUpdateRequest(BaseModel):
    series_id: str
    series_name: str

@router.post("/add")
def add_to_chasing_list(req: ChasingListUpdateRequest):
    logic = get_logic()
    logic.add_to_chasing_list(req.series_id, req.series_name)
    return {"status": "success"}

@router.post("/remove")
def remove_from_chasing_list(req: ChasingListUpdateRequest):
    logic = get_logic()
    logic.remove_from_chasing_list(req.series_id, req.series_name, "用户手动移除")
    return {"status": "success"}

@router.post("/trigger-run")
def trigger_chasing_workflow():
    logic = get_logic()
    task_id = task_manager.register_task(
        logic.run_chasing_workflow_task,
        "手动触发-追更每日维护"
    )
    return {"status": "success", "message": "追更维护任务已手动触发！", "task_id": task_id}