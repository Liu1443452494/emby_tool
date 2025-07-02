# backend/episode_renamer_router.py (新文件)

import os
import json
from fastapi import APIRouter, HTTPException, Body
from typing import List, Dict
from filelock import FileLock, Timeout

from log_manager import ui_logger
from models import AppConfig, EpisodeRenamerConfig
from episode_renamer_logic import EpisodeRenamerLogic, RENAME_LOG_FILE
from task_manager import task_manager
import config as app_config

router = APIRouter()

def get_logic() -> EpisodeRenamerLogic:
    config = app_config.load_app_config()
    return EpisodeRenamerLogic(config)

@router.post("/config")
def save_episode_renamer_config(config: EpisodeRenamerConfig):
    """保存剧集文件重命名器的配置"""
    try:
        current_app_config = app_config.load_app_config()
        current_app_config.episode_renamer_config = config
        app_config.save_app_config(current_app_config)
        return {"status": "success", "message": "设置已保存！"}
    except Exception as e:
        ui_logger.error(f"保存剧集重命名器设置失败: {e}", task_category="API-重命名器")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/logs")
def get_rename_logs() -> List[Dict]:
    """获取所有状态的重命名日志"""
    if not os.path.exists(RENAME_LOG_FILE):
        return []
    try:
        with FileLock(RENAME_LOG_FILE + ".lock", timeout=5):
            with open(RENAME_LOG_FILE, 'r', encoding='utf-8') as f:
                all_logs = json.load(f)
        # 直接返回所有日志，让前端根据 status 字段进行分类
        return all_logs
    except (IOError, json.JSONDecodeError, Timeout) as e:
        ui_logger.error(f"读取重命名日志文件失败: {e}", task_category="API-重命名器")
        return []

@router.post("/logs/clear-completed")
def clear_completed_logs():
    """从日志文件中移除已完成的记录"""
    if not os.path.exists(RENAME_LOG_FILE):
        return {"status": "success", "message": "日志文件不存在，无需清理。"}
    try:
        with FileLock(RENAME_LOG_FILE + ".lock", timeout=10):
            with open(RENAME_LOG_FILE, 'r', encoding='utf-8') as f:
                all_logs = json.load(f)
            
            pending_logs = [log for log in all_logs if log.get('status') != 'completed']
            
            with open(RENAME_LOG_FILE, 'w', encoding='utf-8') as f:
                json.dump(pending_logs, f, indent=4, ensure_ascii=False)
        
        return {"status": "success", "message": "已成功清理已完成的日志记录。"}
    except Exception as e:
        ui_logger.error(f"清理日志文件失败: {e}", task_category="API-重命名器")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.delete("/logs/clear-all")
def clear_all_logs():
    """清空所有日志记录"""
    try:
        with FileLock(RENAME_LOG_FILE + ".lock", timeout=10):
            if os.path.exists(RENAME_LOG_FILE):
                os.remove(RENAME_LOG_FILE)
        return {"status": "success", "message": "所有日志记录已成功清空。"}
    except Exception as e:
        ui_logger.error(f"清空所有日志文件失败: {e}", task_category="API-重命名器")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/apply-clouddrive-rename")
def apply_clouddrive_rename(log_entries: List[Dict] = Body(...)):
    """启动一个任务来重命名网盘文件"""
    if not log_entries:
        raise HTTPException(status_code=400, detail="必须提供要处理的日志条目。")
    
    logic = get_logic()
    task_name = f"网盘文件重命名 (共 {len(log_entries)} 项)"
    task_id = task_manager.register_task(
        logic.apply_clouddrive_rename_task,
        task_name,
        log_entries
    )
    return {"status": "success", "message": "网盘文件重命名任务已启动。", "task_id": task_id}

@router.post("/manual-scan/{series_id}")
def manual_scan(series_id: str):
    """启动一个任务来手动扫描指定剧集"""
    logic = get_logic()
    task_name = f"手动扫描重命名 (ID: {series_id})"
    task_id = task_manager.register_task(
        logic.manual_scan_for_rename_task,
        task_name,
        series_id
    )
    return {"status": "success", "message": "手动扫描任务已启动。", "task_id": task_id}