# backend/media_tagger_router.py (完整文件覆盖)

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
from typing import List, Dict

import config as app_config
from models import MediaTaggerConfig
from task_manager import task_manager
from media_tagger_logic import MediaTaggerLogic

router = APIRouter()

@router.get("/config", response_model=MediaTaggerConfig)
def get_media_tagger_config():
    """获取媒体标签器配置"""
    return app_config.load_app_config().media_tagger_config

@router.post("/config")
def save_media_tagger_config(config: MediaTaggerConfig):
    """保存媒体标签器配置"""
    try:
        # --- 核心修改：导入调度器并增加更新逻辑 ---
        from main import scheduler, trigger_media_tagger_task
        from apscheduler.triggers.cron import CronTrigger

        current_app_config = app_config.load_app_config()
        current_app_config.media_tagger_config = config
        app_config.save_app_config(current_app_config)
        
        job_id = "media_tagger_job"
        if scheduler.running:
            existing_job = scheduler.get_job(job_id)
            if existing_job:
                scheduler.remove_job(job_id)
                logging.info(f"【调度任务】已移除旧的媒体标签器任务。")
            
            if config.enabled and config.cron:
                try:
                    scheduler.add_job(
                        trigger_media_tagger_task,
                        CronTrigger.from_crontab(config.cron),
                        id=job_id,
                        replace_existing=True
                    )
                    logging.info(f"【调度任务】已更新媒体标签器定时任务，新CRON表达式: '{config.cron}'")
                except Exception as e:
                    logging.error(f"【调度任务】更新媒体标签器任务失败: {e}")
                    raise HTTPException(status_code=400, detail=f"CRON表达式无效: {e}")
        # --- 修改结束 ---
        
        return {"success": True, "message": "媒体标签器设置已保存！"}
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"保存媒体标签器设置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存设置时发生错误: {e}")

@router.post("/run")
def run_media_tagger():
    """手动触发一次媒体标签器任务"""
    config = app_config.load_app_config()
    logic = MediaTaggerLogic(config)
    for task in task_manager.get_all_tasks():
        if task['name'] == "媒体标签器-应用规则":
            raise HTTPException(status_code=409, detail=f"已有应用规则任务(ID: {task['id']})正在运行，请勿重复启动。")
    task_id = task_manager.register_task(logic.run_tagging_task, "媒体标签器-应用规则")
    return {"status": "success", "message": "应用规则任务已启动", "task_id": task_id}

class ClearScope(BaseModel):
    mode: str
    library_names: List[str] = []

class ClearAllTagsRequest(BaseModel):
    scope: ClearScope

class RemoveTagsRequest(BaseModel):
    tags: List[str]
    scope: ClearScope

@router.post("/clear-all-tags")
def clear_all_tags(req: ClearAllTagsRequest):
    """触发清空所有标签的任务"""
    config = app_config.load_app_config()
    logic = MediaTaggerLogic(config)
    task_id = task_manager.register_task(
        logic.clear_all_tags_task,
        "清空所有媒体标签",
        scope=req.scope.model_dump()
    )
    return {"status": "success", "message": "清空所有标签任务已启动", "task_id": task_id}

@router.post("/remove-specific-tags")
def remove_specific_tags(req: RemoveTagsRequest):
    """触发移除指定标签的任务"""
    if not req.tags:
        raise HTTPException(status_code=400, detail="要移除的标签列表不能为空。")
    config = app_config.load_app_config()
    logic = MediaTaggerLogic(config)
    task_name = f"移除指定标签 ({', '.join(req.tags)})"
    task_id = task_manager.register_task(
        logic.remove_specific_tags_task,
        task_name,
        tags_to_remove=req.tags,
        scope=req.scope.model_dump()
    )
    return {"status": "success", "message": "移除指定标签任务已启动", "task_id": task_id}