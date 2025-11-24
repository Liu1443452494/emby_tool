# backend/douban_metadata_refresher_router.py (新文件)

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from models import AppConfig, DoubanMetadataRefresherConfig, ScheduledTasksTargetScope
from douban_metadata_refresher_logic import DoubanMetadataRefresherLogic
from task_manager import task_manager
import config as app_config
from log_manager import ui_logger

router = APIRouter()

def get_logic() -> DoubanMetadataRefresherLogic:
    config = app_config.load_app_config()
    return DoubanMetadataRefresherLogic(config)

@router.get("/config", response_model=DoubanMetadataRefresherConfig)
def get_config():
    """获取豆瓣元数据刷新器的配置"""
    return app_config.load_app_config().douban_metadata_refresher_config

@router.post("/config")
def save_config(config: DoubanMetadataRefresherConfig):
    """保存豆瓣元数据刷新器的配置"""
    try:
        current_app_config = app_config.load_app_config()
        current_app_config.douban_metadata_refresher_config = config
        app_config.save_app_config(current_app_config)
        ui_logger.info("✅ [豆瓣元数据刷新] 配置已保存。", task_category="系统配置")
        return {"status": "success", "message": "配置已保存！"}
    except Exception as e:
        ui_logger.error(f"❌ 保存配置失败: {e}", task_category="API-豆瓣元数据刷新")
        raise HTTPException(status_code=500, detail=str(e))

class TaskRequest(BaseModel):
    scope: ScheduledTasksTargetScope
    config: DoubanMetadataRefresherConfig

@router.post("/run")
def run_refresh_task(req: TaskRequest):
    """启动一个任务，刷新豆瓣元数据"""
    logic = get_logic()
    task_id = task_manager.register_task(
        logic.run_refresh_task,
        "豆瓣元数据刷新",
        scope=req.scope,
        config=req.config
    )
    return {"status": "success", "message": "豆瓣元数据刷新任务已启动。", "task_id": task_id}

@router.post("/run-fix")
def run_fix_task(req: TaskRequest):
    """启动一个任务，修复媒体元数据（不更新豆瓣文件）"""
    logic = get_logic()
    task_id = task_manager.register_task(
        logic.run_metadata_fix_task,
        "修复媒体元数据",
        scope=req.scope,
        config=req.config
    )
    return {"status": "success", "message": "修复媒体元数据任务已启动。", "task_id": task_id}