# backend/upcoming_router.py (新文件)

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
from datetime import datetime

import config as app_config
from models import UpcomingSubscriptionItem
from upcoming_logic import UpcomingLogic

router = APIRouter()

@router.get("/config")
def get_upcoming_config():
    """获取即将上映功能的配置"""
    config = app_config.load_app_config()
    return config.upcoming_config

@router.post("/config")
def save_upcoming_config(new_config: Dict[str, Any]):
    """保存即将上映功能的配置"""
    try:
        current_app_config = app_config.load_app_config()
        # 为了模型的验证，我们先更新字典再用整个对象赋值
        config_dict = current_app_config.upcoming_config.model_dump()
        config_dict.update(new_config)
        current_app_config.upcoming_config = config_dict
        
        app_config.save_app_config(current_app_config)
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

@router.get("/subscriptions")
def get_subscriptions():
    """获取用户当前的订阅列表"""
    config = app_config.load_app_config()
    logic = UpcomingLogic(config)
    return logic.get_subscriptions()

@router.post("/subscribe")
def subscribe_item(item: UpcomingSubscriptionItem):
    """添加一个新的订阅项"""
    config = app_config.load_app_config()
    logic = UpcomingLogic(config)
    # 补充订阅时间
    item.subscribed_at = datetime.now(timezone.utc).isoformat()
    if logic.add_subscription(item.model_dump()):
        return {"success": True}
    raise HTTPException(status_code=500, detail="添加订阅失败")

@router.post("/unsubscribe")
def unsubscribe_item(payload: Dict[str, int]):
    """移除一个订阅项"""
    tmdb_id = payload.get("tmdb_id")
    if not tmdb_id:
        raise HTTPException(status_code=400, detail="缺少 tmdb_id")
    config = app_config.load_app_config()
    logic = UpcomingLogic(config)
    if logic.remove_subscription(tmdb_id):
        return {"success": True}
    raise HTTPException(status_code=500, detail="移除订阅失败")