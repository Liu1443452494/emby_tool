# backend/episode_role_sync_router.py (新文件)

import logging
from fastapi import APIRouter, HTTPException
from models import EpisodeRoleSyncConfig
import config as app_config
from log_manager import ui_logger

router = APIRouter()

@router.post("/config")
def save_episode_role_sync_config_api(config: EpisodeRoleSyncConfig):
    """保存剧集角色同步功能的配置"""
    task_cat = "系统配置"
    try:
        ui_logger.info("➡️ 正在保存“剧集角色同步到分集”功能的设置...", task_category=task_cat)
        current_app_config = app_config.load_app_config()
        
        # 更新主配置中的对应部分
        current_app_config.episode_role_sync_config = config
        
        # 保存整个主配置
        app_config.save_app_config(current_app_config)
        
        ui_logger.info("✅ “剧集角色同步到分集”设置保存成功！", task_category=task_cat)
        return {"success": True, "message": "设置已保存！"}
    except Exception as e:
        logging.error(f"保存“剧集角色同步到分集”设置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存设置时发生错误: {e}")