# backend/poster_manager_router.py

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import List, Dict

from log_manager import ui_logger
from models import AppConfig, PosterManagerConfig, ScheduledTasksTargetScope
from poster_manager_logic import PosterManagerLogic
from task_manager import task_manager
import config as app_config

router = APIRouter()

def get_logic() -> PosterManagerLogic:
    config = app_config.load_app_config()
    return PosterManagerLogic(config)

@router.get("/config", response_model=PosterManagerConfig)
def get_poster_manager_config():
    """获取海报管理器的配置"""
    return app_config.load_app_config().poster_manager_config

@router.post("/config")
def save_poster_manager_config(config: PosterManagerConfig):
    """保存海报管理器的配置"""
    try:
        current_app_config = app_config.load_app_config()
        current_app_config.poster_manager_config = config
        app_config.save_app_config(current_app_config)
        return {"status": "success", "message": "海报管理器设置已保存！"}
    except Exception as e:
        ui_logger.error(f"保存海报管理器设置失败: {e}", task_category="API-海报管理")
        raise HTTPException(status_code=500, detail=str(e))

# backend/poster_manager_router.py (函数替换)

@router.get("/stats")
def get_stats(force_refresh: bool = False):
    """获取状态仪表盘的数据"""
    try:
        logic = get_logic()
        # --- 核心修改：将 force_refresh 参数传递给 logic 层 ---
        return logic.get_stats(force_refresh)
    except Exception as e:
        ui_logger.error(f"获取状态概览失败: {e}", task_category="API-海报管理")
        raise HTTPException(status_code=500, detail=str(e))

class BackupRequest(BaseModel):
    scope: ScheduledTasksTargetScope
    content_types: List[str]
    overwrite: bool

@router.post("/start-backup")
def start_backup(req: BackupRequest = Body(...)):
    """启动一个任务，将本地缓存的图片备份到 GitHub"""
    logic = get_logic()
    if not logic.pm_config.local_cache_path:
        raise HTTPException(status_code=400, detail="未配置本地缓存路径，无法启动备份。")
    if not logic.pm_config.github_repos:
        raise HTTPException(status_code=400, detail="未配置任何 GitHub 仓库，无法启动备份。")
    
    task_name = f"海报备份 ({req.scope.mode})"
    task_id = task_manager.register_task(
        logic.start_backup_task,
        task_name,
        scope=req.scope,
        content_types=req.content_types,
        overwrite=req.overwrite
    )
    return {"status": "success", "message": "海报备份任务已启动。", "task_id": task_id}

class RestoreRequest(BaseModel):
    scope: ScheduledTasksTargetScope
    content_types: List[str]

@router.post("/start-restore")
def start_restore(req: RestoreRequest = Body(...)):
    """启动一个任务，从 GitHub 备份恢复图片到 Emby"""
    logic = get_logic()
    if not logic.pm_config.github_repos:
        raise HTTPException(status_code=400, detail="未配置任何 GitHub 仓库，无法启动恢复。")
    
    task_name = f"海报恢复 ({req.scope.mode})"
    task_id = task_manager.register_task(
        logic.start_restore_task,
        task_name,
        scope=req.scope,
        content_types=req.content_types
    )
    return {"status": "success", "message": "海报恢复任务已启动。", "task_id": task_id}

@router.get("/item-details/{item_id}")
def get_single_item_details(item_id: str):
    """获取单个媒体项的图片详情"""
    try:
        logic = get_logic()
        return logic.get_single_item_details(item_id)
    except Exception as e:
        ui_logger.error(f"获取单项详情失败 (ID: {item_id}): {e}", task_category="API-海报管理")
        raise HTTPException(status_code=500, detail=str(e))

class SingleImageRequest(BaseModel):
    item_id: str
    image_type: str

@router.post("/backup-single")
def backup_single_image(req: SingleImageRequest):
    """备份单张图片"""
    try:
        logic = get_logic()
        logic.backup_single_image(req.item_id, req.image_type)
        return {"status": "success", "message": "单体备份成功！"}
    except Exception as e:
        ui_logger.error(f"单体备份失败 (ID: {req.item_id}, 类型: {req.image_type}): {e}", task_category="API-海报管理")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/delete-single")
def delete_single_image(req: SingleImageRequest):
    """删除单张备份图片"""
    try:
        logic = get_logic()
        logic.delete_single_image(req.item_id, req.image_type)
        return {"status": "success", "message": "单体删除成功！"}
    except Exception as e:
        ui_logger.error(f"单体删除失败 (ID: {req.item_id}, 类型: {req.image_type}): {e}", task_category="API-海报管理")
        raise HTTPException(status_code=500, detail=str(e))