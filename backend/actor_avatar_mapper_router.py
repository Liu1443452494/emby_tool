# backend/actor_avatar_mapper_router.py (新文件)

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
import os
import json
from typing import Dict, Any

from log_manager import ui_logger
from models import AppConfig, ScheduledTasksTargetScope
from actor_avatar_mapper_logic import ActorAvatarMapperLogic, ACTOR_AVATAR_MAP_FILE
from task_manager import task_manager
import config as app_config

router = APIRouter()

def get_logic() -> ActorAvatarMapperLogic:
    config = app_config.load_app_config()
    return ActorAvatarMapperLogic(config)

@router.get("/map")
def get_map():
    """获取本地的演员头像映射表内容"""
    if not os.path.exists(ACTOR_AVATAR_MAP_FILE):
        return {} # 如果文件不存在，返回空对象是正常的
    try:
        with open(ACTOR_AVATAR_MAP_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取头像映射表文件失败: {e}")

class TaskRequest(BaseModel):
    scope: ScheduledTasksTargetScope

@router.post("/restore")
def restore_avatars(req: TaskRequest):
    """启动一个任务，从映射表恢复演员头像"""
    logic = get_logic()
    task_id = task_manager.register_task(
        logic.restore_avatars_task,
        "批量恢复演员头像",
        scope=req.scope
    )
    return {"status": "success", "message": "批量恢复演员头像任务已启动。", "task_id": task_id}

@router.post("/upload")
def upload_map():
    """启动一个任务，上传头像映射表到 GitHub"""
    logic = get_logic()
    task_id = task_manager.register_task(
        logic.upload_to_github_task,
        "上传演员头像映射表到GitHub"
    )
    return {"status": "success", "message": "上传任务已启动。", "task_id": task_id}

@router.post("/download")
def download_map():
    """启动一个任务，从 GitHub 下载头像映射表"""
    logic = get_logic()
    task_id = task_manager.register_task(
        logic.download_from_github_task,
        "从GitHub下载演员头像映射表"
    )
    return {"status": "success", "message": "下载任务已启动。", "task_id": task_id}

class SingleRestoreRequest(BaseModel):
    actor_info: Dict[str, Any]
    scope: ScheduledTasksTargetScope

@router.post("/restore-single")
def restore_single_avatar(req: SingleRestoreRequest):
    """启动一个任务，恢复单个演员的头像"""
    logic = get_logic()
    actor_name = req.actor_info.get("actor_name", "未知演员")
    task_id = task_manager.register_task(
        logic.restore_single_avatar_task,
        f"演员头像映射-恢复-{actor_name}",
        actor_info=req.actor_info,
        scope=req.scope
    )
    return {"status": "success", "message": f"为演员【{actor_name}】恢复头像的任务已启动。", "task_id": task_id}