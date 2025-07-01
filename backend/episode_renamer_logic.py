import logging
import os
import re
import json
import threading
from datetime import datetime
from typing import List, Iterable, Optional, Dict

from log_manager import ui_logger
from models import AppConfig
from task_manager import TaskManager

# 用于存储重命名记录的 JSON 文件路径
RENAME_LOG_FILE = os.path.join('/app/data', 'rename_log.json')

class EpisodeRenamerLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.server_config = app_config.server_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        # 暂时不使用 session，因为我们只调用一次
        # from proxy_manager import ProxyManager
        # self.proxy_manager = ProxyManager(app_config)

    @staticmethod
    def _is_generic_episode_title(text: str) -> bool:
        """判断是否为通用、无意义的标题，如 'Episode 5', '第 5 集'"""
        if not text:
            return True
        # 匹配 "Episode 5", "第5集", "第 5 集" 等格式
        pattern = re.compile(r'^(第\s*\d+\s*集|Episode\s*\d+)$', re.IGNORECASE)
        return bool(pattern.match(text.strip()))

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """清理文件名中的非法字符"""
        # Windows 和 Linux/macOS 的非法字符
        return re.sub(r'[\\/*?:"<>|]', '_', name)

    def _get_episode_details(self, episode_id: str) -> Optional[Dict]:
        """获取单个分集的详细信息"""
        import requests
        try:
            url = f"{self.base_url}/Users/{self.user_id}/Items/{episode_id}"
            params = {**self.params, "Fields": "Path,Name"}
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"【剧集重命名】获取分集详情 (ID: {episode_id}) 失败: {e}")
            return None

    def _extract_title_from_filename(self, filename: str) -> Optional[str]:
        """从文件名中提取标题部分"""
        # 正则表达式匹配 SXXEXX - [标题] - [后缀] 的格式
        # 它会捕获 SXXEXX 和 -ADWeb (或任何后缀) 之间的所有内容
        match = re.search(r'S\d{2}E\d{2}\s*-\s*(.*?)\s*-\s*\w+$', filename, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _rename_associated_files(self, old_base_path: str, new_base_path: str, task_cat: str) -> bool:
        """重命名 .strm, .nfo, 和 -thumb.jpg 文件"""
        renamed_any = False
        # 定义文件后缀和对应的旧新路径
        file_types = {
            '.strm': (f"{old_base_path}.strm", f"{new_base_path}.strm"),
            '.nfo': (f"{old_base_path}.nfo", f"{new_base_path}.nfo"),
            '-thumb.jpg': (f"{old_base_path}-thumb.jpg", f"{new_base_path}-thumb.jpg")
        }

        for ext, (old_path, new_path) in file_types.items():
            if os.path.exists(old_path):
                try:
                    os.rename(old_path, new_path)
                    ui_logger.info(f"     - 成功重命名: {os.path.basename(old_path)} -> {os.path.basename(new_path)}", task_category=task_cat)
                    renamed_any = True
                except OSError as e:
                    ui_logger.error(f"     - 重命名文件失败: {old_path} -> {new_path}。错误: {e}", task_category=task_cat)
            else:
                ui_logger.debug(f"     - 文件不存在，跳过: {os.path.basename(old_path)}", task_category=task_cat)
        
        return renamed_any

    def _log_rename_operation(self, episode_id: str, old_path: str, new_path: str, task_cat: str):
        """将重命名操作记录到 JSON 文件中"""
        from filelock import FileLock, Timeout
        
        log_entry = {
            "episode_id": episode_id,
            "original_full_path": old_path,
            "new_full_path": new_path,
            "timestamp": datetime.now().isoformat(),
            "status": "local_renamed"
        }

        lock_path = RENAME_LOG_FILE + ".lock"
        try:
            with FileLock(lock_path, timeout=10):
                if os.path.exists(RENAME_LOG_FILE):
                    with open(RENAME_LOG_FILE, 'r', encoding='utf-8') as f:
                        logs = json.load(f)
                else:
                    logs = []
                
                logs.append(log_entry)
                
                with open(RENAME_LOG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(logs, f, indent=4, ensure_ascii=False)
                
                ui_logger.info(f"     - 已成功将本次操作写入日志: {RENAME_LOG_FILE}", task_category=task_cat)

        except Timeout:
            ui_logger.error(f"     - 获取日志文件锁超时，无法记录本次重命名操作！", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"     - 写入重命名日志时发生错误: {e}", task_category=task_cat)

    def run_rename_for_episodes(self, episode_ids: Iterable[str], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager, task_category: str):
        """为指定的剧集分集ID列表执行重命名任务"""
        episode_ids_list = list(episode_ids)
        total_episodes = len(episode_ids_list)
        
        ui_logger.info(f"任务启动，共需处理 {total_episodes} 个剧集分集。", task_category=task_category)
        
        if task_manager and task_id:
            task_manager.update_task_progress(task_id, 0, total_episodes)

        if total_episodes == 0:
            ui_logger.info("没有需要处理的剧集分集，任务结束。", task_category=task_category)
            return {"renamed_count": 0}

        renamed_count = 0
        for index, episode_id in enumerate(episode_ids_list):
            if cancellation_event.is_set():
                ui_logger.warning("任务被用户取消。", task_category=task_category)
                break
            
            if task_manager and task_id:
                task_manager.update_task_progress(task_id, index + 1, total_episodes)

            details = self._get_episode_details(episode_id)
            if not details:
                continue

            emby_path = details.get("Path")
            emby_title = details.get("Name")

            if not emby_path or not emby_title:
                ui_logger.debug(f"  -> 跳过分集 {episode_id}，缺少路径或标题信息。", task_category=task_category)
                continue

            if self._is_generic_episode_title(emby_title):
                ui_logger.debug(f"  -> 跳过分集 {episode_id}，Emby 标题 '{emby_title}' 是通用标题。", task_category=task_category)
                continue

            dir_name = os.path.dirname(emby_path)
            base_filename, ext = os.path.splitext(os.path.basename(emby_path))
            
            # 提取文件名中的旧标题
            old_title_in_filename = self._extract_title_from_filename(base_filename)
            if old_title_in_filename is None:
                ui_logger.debug(f"  -> 跳过文件 '{base_filename}'，无法从中解析出标题部分。", task_category=task_category)
                continue

            # 清理 Emby 标题以用作新文件名
            new_title_for_filename = self._sanitize_filename(emby_title)

            if old_title_in_filename.lower() == new_title_for_filename.lower():
                ui_logger.debug(f"  -> 跳过文件 '{base_filename}'，文件名中的标题已是最新。", task_category=task_category)
                continue

            ui_logger.info(f"  -> 检测到需要重命名的分集: {base_filename}", task_category=task_category)
            ui_logger.info(f"     - 旧标题: '{old_title_in_filename}' -> 新标题: '{new_title_for_filename}'", task_category=task_category)

            # 构建新的基本文件名（不含后缀）
            new_base_filename = base_filename.replace(old_title_in_filename, new_title_for_filename)
            
            # 构建旧的和新的文件基础路径（不含后缀）
            old_base_path = os.path.join(dir_name, base_filename)
            new_base_path = os.path.join(dir_name, new_base_filename)

            if self._rename_associated_files(old_base_path, new_base_path, task_category):
                renamed_count += 1
                # 记录原始 .strm 文件的路径变化
                self._log_rename_operation(episode_id, f"{old_base_path}.strm", f"{new_base_path}.strm", task_category)

        ui_logger.info(f"任务执行完毕。共成功重命名了 {renamed_count} 组文件。", task_category=task_category)
        return {"renamed_count": renamed_count}