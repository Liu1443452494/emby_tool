# backend/upcoming_router.py (完整文件覆盖)

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional

import config as app_config
from models import UpcomingConfig
from upcoming_logic import UpcomingLogic

router = APIRouter()

@router.get("/config")
def get_upcoming_config():
    """获取即将上映功能的配置"""
    config = app_config.load_app_config()
    return config.upcoming_config

@router.post("/config")
def save_upcoming_config(new_config: UpcomingConfig):
    """保存即将上映功能的配置"""
    try:
        current_app_config = app_config.load_app_config()
        current_app_config.upcoming_config = new_config
        app_config.save_app_config(current_app_config)
        
        # --- 新增：保存后更新调度器 ---
        from main import update_upcoming_scheduler
        update_upcoming_scheduler()
        # --- 新增结束 ---
        
        return {"success": True, "message": "设置已保存！"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/list")
def get_upcoming_list(dynamic_filters: Optional[Dict] = None):
    """获取即将上映的媒体列表，支持动态筛选"""
    try:
        config = app_config.load_app_config()
        logic = UpcomingLogic(config)
        return logic.get_upcoming_list(dynamic_filters)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/data")
def get_all_data():
    """获取数据库中所有未过期的项目"""
    config = app_config.load_app_config()
    logic = UpcomingLogic(config)
    return logic.get_all_data()

@router.post("/subscribe")
def subscribe_item(payload: Dict[str, int]):
    """添加一个新的订阅项"""
    tmdb_id = payload.get("tmdb_id")
    if not tmdb_id:
        raise HTTPException(status_code=400, detail="缺少 tmdb_id")
    config = app_config.load_app_config()
    logic = UpcomingLogic(config)
    if logic.update_subscription(tmdb_id, subscribe=True):
        return {"success": True}
    raise HTTPException(status_code=500, detail="订阅失败")

@router.post("/unsubscribe")
def unsubscribe_item(payload: Dict[str, int]):
    """移除一个订阅项"""
    tmdb_id = payload.get("tmdb_id")
    if not tmdb_id:
        raise HTTPException(status_code=400, detail="缺少 tmdb_id")
    config = app_config.load_app_config()
    logic = UpcomingLogic(config)
    if logic.update_subscription(tmdb_id, subscribe=False):
        return {"success": True}
    raise HTTPException(status_code=500, detail="取消订阅失败")


@router.post("/trigger-notification")
def trigger_notification_now():
    """手动触发一次订阅通知检查"""
    try:
        config = app_config.load_app_config()
        logic = UpcomingLogic(config)
        logic.check_and_notify()
        return {"success": True, "message": "订阅通知任务已成功触发！"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/trigger-pruning")
def trigger_pruning_now():
    """手动触发一次过期项目清理"""
    try:
        config = app_config.load_app_config()
        logic = UpcomingLogic(config)
        logic.prune_expired_items()
        return {"success": True, "message": "过期项目清理任务已成功触发！"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))