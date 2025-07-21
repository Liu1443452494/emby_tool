# backend/signin_router.py (新文件)

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any

from signin_manager import signin_manager
from task_manager import task_manager
import config as app_config
from models import SigninModulesConfig

router = APIRouter()

@router.get("/modules", response_model=List[Dict[str, Any]])
def get_signin_modules():
    """获取所有签到模块及其摘要信息"""
    return signin_manager.get_all_modules_summary()


@router.post("/config")
def save_signin_config(config: SigninModulesConfig):
    """保存所有签到模块的配置"""
    try:
        current_app_config = app_config.load_app_config()
        current_app_config.signin_config = config
        app_config.save_app_config(current_app_config)
        
        # 重新加载模块以应用新配置
        signin_manager._load_modules()
        
        # --- 核心修改：调用主程序中的调度器更新函数 ---
        from main import update_signin_scheduler
        update_signin_scheduler()
        # --- 修改结束 ---
        
        return {"success": True, "message": "签到模块配置已保存！"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存配置时发生错误: {e}")

@router.post("/{module_id}/trigger")
def trigger_signin_once(module_id: str):
    """手动触发一次指定模块的签到"""
    module = signin_manager.modules.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail=f"未找到ID为 '{module_id}' 的签到模块。")

    task_name = f"手动签到 - {module.module_name}"
    # --- 核心修改：增加 is_manual_trigger=True 参数 ---
    task_id = task_manager.register_task(
        signin_manager.run_signin,
        task_name,
        module_id=module_id,
        is_manual_trigger=True
    )
    # --- 修改结束 ---
    return {"success": True, "message": f"任务 '{task_name}' 已成功触发。", "task_id": task_id}

@router.get("/{module_id}/history", response_model=List[Dict[str, Any]])
def get_signin_history(module_id: str):
    """获取指定模块的签到历史"""
    if module_id not in signin_manager.modules:
        raise HTTPException(status_code=404, detail=f"未找到ID为 '{module_id}' 的签到模块。")
    return signin_manager.get_module_history(module_id)

@router.post("/{module_id}/reset-data")
def reset_signin_data(module_id: str):
    """重置指定模块的统计数据"""
    if signin_manager.reset_module_data(module_id):
        return {"success": True, "message": "模块数据已重置。"}
    else:
        raise HTTPException(status_code=404, detail=f"未找到ID为 '{module_id}' 的签到模块。")