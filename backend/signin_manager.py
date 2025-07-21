# backend/signin_manager.py (新文件)

import os
import json
import threading
import time
from typing import Dict, List, Any, Optional
from filelock import FileLock


import config as app_config
from log_manager import ui_logger
from models import AppConfig, SigninModulesConfig
from signin_modules.hdhive_signin import HdhiveSignInModule

# --- 数据文件路径 ---
DATA_FILE = os.path.join('/app/data', 'signin_data.json')
LOCK_FILE = os.path.join('/app/data', 'signin_data.json.lock')

class SigninManager:
    def __init__(self):
        self.modules: Dict[str, Any] = {}
        self.signin_data: Dict[str, Any] = self._load_data()
        self._load_modules()

    def _load_data(self) -> Dict[str, Any]:
        """从JSON文件加载数据，带文件锁"""
        if not os.path.exists(DATA_FILE):
            return {}
        try:
            with FileLock(LOCK_FILE, timeout=5):
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            ui_logger.error(f"❌ 读取签到数据文件失败: {e}", task_category="签到管理器")
            return {}

    def _save_data(self):
        """将数据保存到JSON文件，带文件锁"""
        try:
            with FileLock(LOCK_FILE, timeout=5):
                with open(DATA_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.signin_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            ui_logger.error(f"❌ 保存签到数据文件失败: {e}", task_category="签到管理器")

    def _load_modules(self):
        """加载所有签到模块实例"""
        config = app_config.load_app_config()
        signin_config = config.signin_config

        # 加载影巢模块
        hdhive_data = self.signin_data.setdefault(HdhiveSignInModule.module_id, {})
        self.modules[HdhiveSignInModule.module_id] = HdhiveSignInModule(signin_config.hdhive, hdhive_data)
        
        # 未来可在此处加载其他模块
        # another_data = self.signin_data.setdefault(AnotherModule.module_id, {})
        # self.modules[AnotherModule.module_id] = AnotherModule(signin_config.another, another_data)

        ui_logger.info(f"✅ 已成功加载 {len(self.modules)} 个签到模块。", task_category="签到管理器")

    # backend/signin_manager.py (函数替换)

    def get_all_modules_summary(self) -> List[Dict[str, Any]]:
        """获取所有模块的摘要信息列表，用于前端渲染"""
        summaries = []
        for module_id, module_instance in self.modules.items():
            # --- 核心修改：返回完整的配置对象，而不仅仅是部分字段 ---
            summary = {
                "id": module_id,
                "name": module_instance.module_name,
                "config": module_instance.config.model_dump(), # 返回完整的配置模型
                **module_instance.get_summary()
            }
            # --- 修改结束 ---
            summaries.append(summary)
        return summaries

    def get_module_history(self, module_id: str) -> List[Dict[str, Any]]:
        """获取指定模块的签到历史"""
        module_data = self.signin_data.get(module_id, {})
        return module_data.get("history", [])

    def reset_module_data(self, module_id: str) -> bool:
        """重置指定模块的统计数据"""
        if module_id in self.signin_data:
            self.signin_data[module_id] = {
                "history": self.signin_data[module_id].get("history", [])
            }
            self._save_data()
            self._load_modules() # 重新加载模块以更新状态
            ui_logger.info(f"✅ 模块 [{module_id}] 的统计数据已重置。", task_category="签到管理器")
            return True
        return False

    

    def run_signin(self, module_id: str, cancellation_event: threading.Event, task_id: str, task_manager: Any, is_manual_trigger: bool = False):
        """由 TaskManager 调用的签到执行函数"""
        module = self.modules.get(module_id)
        if not module:
            raise ValueError(f"未找到模块: {module_id}")

        task_cat = f"签到-{module.module_name}"

        if not module.config.enabled:
            ui_logger.warning(f"⚠️ 模块 [{module.module_name}] 未启用，跳过执行。", task_category=task_cat)
            return

        # --- 核心修改：仅在非手动触发（即定时任务）时应用随机延迟 ---
        if not is_manual_trigger:
            try:
                delay_range = module.config.random_delay.split('-')
                min_delay = int(delay_range[0])
                max_delay = int(delay_range[1])
                if min_delay < max_delay:
                    import random
                    delay = random.randint(min_delay, max_delay)
                    ui_logger.info(f"⏱️ 定时任务已触发，将随机延迟 {delay} 秒后执行...", task_category=task_cat)
                    time.sleep(delay)
            except Exception as e:
                ui_logger.warning(f"⚠️ 解析随机延迟配置失败 ({module.config.random_delay})，将立即执行。错误: {e}", task_category=task_cat)
        # --- 修改结束 ---

        ui_logger.info(f"▶️ 开始执行模块 [{module.module_name}] 的签到任务...", task_category=task_cat)
        
        result = module.sign()
        
        module_data = self.signin_data.setdefault(module_id, {})
        history = module_data.setdefault("history", [])
        history.insert(0, result)
        
        from datetime import datetime, timedelta
        retention_days = module.config.history_days
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        valid_history = [
            rec for rec in history 
            if datetime.strptime(rec["date"], '%Y-%m-%d %H:%M:%S') >= cutoff_date
        ]
        module_data["history"] = valid_history
        
        if result.get("status") in ["签到成功", "已签到"]:
            module_data["last_signin_time"] = result["date"]

        self._save_data()
        
        status = result.get("status")
        message = result.get("message")
        if status == "签到成功":
            ui_logger.info(f"✅ 任务执行成功！详情: {message}", task_category=task_cat)
        elif status == "已签到":
            ui_logger.info(f"ℹ️ 今日已签到。详情: {message}", task_category=task_cat)
        else:
            ui_logger.error(f"❌ 任务执行失败！详情: {message}", task_category=task_cat)
        
        ui_logger.info(f"🎉 签到任务流程执行完毕。", task_category=task_cat)

# 创建一个单例
signin_manager = SigninManager()