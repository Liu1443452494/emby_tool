# backend/actor_role_mapper_router.py (新文件)

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field
from typing import List, Dict
import os
import json
from log_manager import ui_logger
from models import AppConfig, ScheduledTasksTargetScope
from actor_role_mapper_logic import ActorRoleMapperLogic, ACTOR_ROLE_MAP_FILE
from task_manager import task_manager
import config as app_config

router = APIRouter()

def get_logic() -> ActorRoleMapperLogic:
    config = app_config.load_app_config()
    return ActorRoleMapperLogic(config)

@router.get("/map")
def get_map():
    """获取本地的演员角色映射表内容"""
    if not os.path.exists(ACTOR_ROLE_MAP_FILE):
        raise HTTPException(status_code=404, detail="本地映射表文件不存在。")
    try:
        with open(ACTOR_ROLE_MAP_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取映射表文件失败: {e}")

class TaskRequest(BaseModel):
    scope: ScheduledTasksTargetScope
    # --- 新增行 ---
    actor_limit: int = Field(default=50, ge=1, description="每个媒体项处理的演员数量上限")

@router.post("/generate")
def generate_map(req: TaskRequest):
    """启动一个任务，生成演员角色映射表"""
    logic = get_logic()
    task_id = task_manager.register_task(
        logic.generate_map_task,
        "生成演员角色映射表",
        scope=req.scope,
        # --- 新增行 ---
        actor_limit=req.actor_limit
    )
    return {"status": "success", "message": "生成映射表任务已启动。", "task_id": task_id}

@router.post("/upload")
def upload_map():
    """启动一个任务，上传映射表到 GitHub"""
    logic = get_logic()
    task_id = task_manager.register_task(
        logic.upload_to_github_task,
        "上传映射表到GitHub"
    )
    return {"status": "success", "message": "上传任务已启动。", "task_id": task_id}

@router.post("/download")
def download_map():
    """启动一个任务，从 GitHub 下载映射表"""
    logic = get_logic()
    task_id = task_manager.register_task(
        logic.download_from_github_task,
        "从GitHub下载映射表"
    )
    return {"status": "success", "message": "下载任务已启动。", "task_id": task_id}

@router.post("/restore")
def restore_map(req: TaskRequest):
    """启动一个任务，从映射表恢复演员角色"""
    logic = get_logic()
    task_id = task_manager.register_task(
        logic.restore_roles_from_map_task,
        "批量恢复演员角色",
        scope=req.scope
    )
    return {"status": "success", "message": "批量恢复演员角色任务已启动。", "task_id": task_id}


@router.get("/media/{item_id}/actors")
def get_media_actors(item_id: str):
    """获取指定媒体项下的所有演员及其头像信息"""
    try:
        logic = get_logic()
        # --- 核心修改：调用 actor_role_mapper_logic 自己的方法，而不是 tmdb_logic 的 ---
        details = logic._get_emby_item_details(item_id, fields="People")
        people = details.get("People", [])
        actors = [
            {
                "Name": p.get("Name"),
                "Id": p.get("Id"),
                "PrimaryImageTag": p.get("PrimaryImageTag")
            }
            for p in people if p.get("Type") == "Actor"
        ]
        return actors
    except Exception as e:
        # --- 核心修改：增加日志记录，以便追踪错误 ---
        ui_logger.error(f"❌ 在 /media/{item_id}/actors 接口获取演员列表失败: {e}", task_category="API-角色映射", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取演员列表失败: {e}")
    
class SingleMapRequest(BaseModel):
    map_data: Dict

@router.post("/restore-single")
def restore_single_map(req: SingleMapRequest):
    """启动一个任务，恢复单条映射关系"""
    logic = get_logic()
    title = req.map_data.get("title", "未知作品")
    task_id = task_manager.register_task(
        logic.restore_single_map_task,
        f"恢复演员角色 - {title}",
        single_map_data=req.map_data
    )
    return {"status": "success", "message": f"为《{title}》恢复角色的任务已启动。", "task_id": task_id}

@router.post("/update-single-map")
def update_single_map_file_route(req: SingleMapRequest):
    """更新 actor_role_map.json 文件中的单条记录"""
    try:
        logic = get_logic()
        return logic.update_single_map_file(req.map_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))