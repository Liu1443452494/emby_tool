# backend/episode_renamer_logic.py (提供完整文件)

import logging
import os
import re
import json
import threading
import time
from datetime import datetime
from typing import List, Iterable, Optional, Dict, Tuple
from filelock import FileLock, Timeout

from log_manager import ui_logger
from models import AppConfig, EpisodeRenamerConfig
from task_manager import TaskManager

# 用于存储重命名记录的 JSON 文件路径
RENAME_LOG_FILE = os.path.join('/app/data', 'rename_log.json')

class EpisodeRenamerLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.server_config = app_config.server_config
        self.renamer_config = app_config.episode_renamer_config
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

    def _get_episode_details(self, episode_id: str, fields: str = "Path,Name") -> Optional[Dict]:
        """获取单个分集的详细信息"""
        import requests
        try:
            url = f"{self.base_url}/Users/{self.user_id}/Items/{episode_id}"
            params = {**self.params, "Fields": fields}
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

    def _log_rename_operation(self, episode_id: str, old_base_path: str, new_base_path: str, task_cat: str):
        """将重命名操作记录到 JSON 文件中"""
        log_entry = {
            "id": f"{episode_id}-{int(time.time())}",
            "episode_id": episode_id,
            "old_base_path": old_base_path,
            "new_base_path": new_base_path,
            "timestamp": datetime.now().isoformat(),
            "status": "pending_clouddrive_rename"
        }

        lock_path = RENAME_LOG_FILE + ".lock"
        try:
            with FileLock(lock_path, timeout=10):
                if os.path.exists(RENAME_LOG_FILE):
                    with open(RENAME_LOG_FILE, 'r', encoding='utf-8') as f:
                        logs = json.load(f)
                else:
                    logs = []
                
                if any(log.get('episode_id') == episode_id and log.get('status') == 'pending_clouddrive_rename' for log in logs):
                    ui_logger.info(f"     - 已存在待处理的重命名日志，本次不再重复添加。", task_category=task_cat)
                    return

                logs.append(log_entry)
                
                with open(RENAME_LOG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(logs, f, indent=4, ensure_ascii=False)
                
                ui_logger.info(f"     - 已成功将本次操作写入日志: {RENAME_LOG_FILE}", task_category=task_cat)

        except Timeout:
            ui_logger.error(f"     - 获取日志文件锁超时，无法记录本次重命名操作！", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"     - 写入重命名日志时发生错误: {e}", task_category=task_cat)

    def run_rename_for_episodes(self, episode_ids: Iterable[str], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager, task_category: str):
        """(定时任务)为指定的剧集分集ID列表执行本地文件重命名，并记录到日志。"""
        episode_ids_list = list(episode_ids)
        total_episodes = len(episode_ids_list)
        
        ui_logger.info(f"【本地重命名任务】启动，共需处理 {total_episodes} 个剧集分集。", task_category=task_category)
        
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
            
            old_title_in_filename = self._extract_title_from_filename(base_filename)
            if old_title_in_filename is None:
                ui_logger.debug(f"  -> 跳过文件 '{base_filename}'，无法从中解析出标题部分。", task_category=task_category)
                continue

            new_title_for_filename = self._sanitize_filename(emby_title)

            if old_title_in_filename.lower() == new_title_for_filename.lower():
                ui_logger.debug(f"  -> 跳过文件 '{base_filename}'，文件名中的标题已是最新。", task_category=task_category)
                continue

            ui_logger.info(f"  -> 检测到需要重命名的本地文件: {base_filename}", task_category=task_category)
            ui_logger.info(f"     - 旧标题: '{old_title_in_filename}' -> 新标题: '{new_title_for_filename}'", task_category=task_category)

            new_base_filename = base_filename.replace(old_title_in_filename, new_title_for_filename)
            
            old_base_path = os.path.join(dir_name, base_filename)
            new_base_path = os.path.join(dir_name, new_base_filename)

            if self._rename_associated_files(old_base_path, new_base_path, task_category):
                renamed_count += 1
                self._log_rename_operation(episode_id, old_base_path, new_base_path, task_category)

        ui_logger.info(f"【本地重命名任务】执行完毕。共成功重命名了 {renamed_count} 组本地文件，并已写入日志。", task_category=task_category)
        return {"renamed_count": renamed_count}

    def _get_clouddrive_video_path(self, episode_id: str, old_base_path: str, task_cat: str) -> Optional[Tuple[str, str]]:
        """通过 MediaSources 获取网盘视频的真实路径和文件名"""
        details = self._get_episode_details(episode_id, fields="MediaSources")
        if not details:
            ui_logger.error(f"     - 无法获取分集 {episode_id} 的 MediaSources。", task_category=task_cat)
            return None

        media_sources = details.get("MediaSources")
        if not media_sources or not isinstance(media_sources, list) or len(media_sources) == 0:
            ui_logger.warning(f"     - 分集 {episode_id} 的 MediaSources 为空，无法获取网盘文件名。", task_category=task_cat)
            return None

        strm_url = media_sources[0].get("Path")
        if not strm_url:
            ui_logger.warning(f"     - MediaSources 中缺少 Path 字段。", task_category=task_cat)
            return None

        try:
            clouddrive_filename = strm_url.split('?/')[-1].split('/')[-1]
        except Exception:
            ui_logger.warning(f"     - 无法从 URL '{strm_url}' 中解析出文件名。", task_category=task_cat)
            return None
        
        emby_root = self.renamer_config.emby_path_root
        clouddrive_root = self.renamer_config.clouddrive_path_root
        
        if not old_base_path.startswith(emby_root):
            ui_logger.error(f"     - 路径错误！文件路径 '{old_base_path}' 与配置的 Emby 根目录 '{emby_root}' 不匹配。", task_category=task_cat)
            return None

        relative_dir = os.path.dirname(old_base_path).replace(emby_root, '', 1).lstrip('/\\')
        clouddrive_dir = os.path.join(clouddrive_root, relative_dir)
        
        full_clouddrive_path = os.path.join(clouddrive_dir, clouddrive_filename)
        return full_clouddrive_path, clouddrive_filename

    def apply_clouddrive_rename_task(self, log_entries: List[Dict], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """根据日志条目，重命名网盘文件"""
        task_cat = "网盘重命名"
        total_items = len(log_entries)
        task_manager.update_task_progress(task_id, 0, total_items)
        ui_logger.info(f"【{task_cat}】任务启动，共需处理 {total_items} 个项目。", task_category=task_cat)

        updated_count = 0
        failed_logs = []

        for index, log_entry in enumerate(log_entries):
            if cancellation_event.is_set():
                ui_logger.warning(f"【{task_cat}】任务被用户取消。", task_category=task_cat)
                break
            
            task_manager.update_task_progress(task_id, index + 1, total_items)
            
            episode_id = log_entry['episode_id']
            old_base_path = log_entry['old_base_path']
            new_base_path = log_entry['new_base_path']
            
            ui_logger.info(f"  -> 正在处理: {os.path.basename(old_base_path)}", task_category=task_cat)

            path_info = self._get_clouddrive_video_path(episode_id, old_base_path, task_cat)
            if not path_info:
                log_entry['error'] = "无法获取网盘文件路径"
                failed_logs.append(log_entry)
                continue
            
            old_clouddrive_path, old_clouddrive_filename = path_info
            
            if not os.path.exists(old_clouddrive_path):
                ui_logger.error(f"     - 网盘文件不存在: {old_clouddrive_path}", task_category=task_cat)
                log_entry['error'] = "网盘文件不存在"
                failed_logs.append(log_entry)
                continue

            _, old_ext = os.path.splitext(old_clouddrive_filename)
            new_clouddrive_filename = os.path.basename(new_base_path) + old_ext
            new_clouddrive_path = os.path.join(os.path.dirname(old_clouddrive_path), new_clouddrive_filename)

            try:
                os.rename(old_clouddrive_path, new_clouddrive_path)
                ui_logger.info(f"     - 成功重命名网盘文件 -> {new_clouddrive_filename}", task_category=task_cat)
                updated_count += 1
                
                lock_path = RENAME_LOG_FILE + ".lock"
                with FileLock(lock_path, timeout=10):
                    if os.path.exists(RENAME_LOG_FILE):
                        with open(RENAME_LOG_FILE, 'r', encoding='utf-8') as f:
                            all_logs = json.load(f)
                        
                        for log in all_logs:
                            if log.get('id') == log_entry.get('id'):
                                log['status'] = 'completed'
                                break
                        
                        with open(RENAME_LOG_FILE, 'w', encoding='utf-8') as f:
                            json.dump(all_logs, f, indent=4, ensure_ascii=False)

            except Exception as e:
                ui_logger.error(f"     - 重命名网盘文件失败: {e}", task_category=task_cat)
                log_entry['error'] = str(e)
                failed_logs.append(log_entry)
            
            time.sleep(self.renamer_config.clouddrive_rename_cooldown)

        ui_logger.info(f"【{task_cat}】任务执行完毕。成功: {updated_count}, 失败: {len(failed_logs)}", task_category=task_cat)
        return {"updated_count": updated_count, "failed_logs": failed_logs}

    def manual_scan_for_rename_task(self, series_id: str, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """手动扫描指定剧集，找出需要重命名的网盘文件"""
        task_cat = "手动扫描重命名"
        ui_logger.info(f"【{task_cat}】任务启动，正在扫描剧集 ID: {series_id}", task_category=task_cat)

        import requests
        try:
            episodes_url = f"{self.base_url}/Items"
            episodes_params = {
                "api_key": self.api_key,
                "ParentId": series_id,
                "IncludeItemTypes": "Episode",
                "Recursive": "true",
                "Fields": "Name,IndexNumber,ParentIndexNumber,Path,SeriesName"
            }
            episodes_resp = requests.get(episodes_url, params=episodes_params, timeout=30)
            episodes_resp.raise_for_status()
            emby_episodes = episodes_resp.json().get("Items", [])
        except Exception as e:
            ui_logger.error(f"【{task_cat}】获取剧集 {series_id} 的分集列表失败: {e}", task_category=task_cat)
            return []
        
        task_manager.update_task_progress(task_id, 0, len(emby_episodes))
        
        results = []
        for index, episode in enumerate(emby_episodes):
            if cancellation_event.is_set(): break
            task_manager.update_task_progress(task_id, index + 1, len(emby_episodes))

            emby_title = episode.get("Name")
            if not emby_title or self._is_generic_episode_title(emby_title):
                continue

            path_info = self._get_clouddrive_video_path(episode['Id'], episode['Path'], task_cat)
            if not path_info: continue
            
            clouddrive_path, clouddrive_filename = path_info
            base_clouddrive_filename, _ = os.path.splitext(clouddrive_filename)
            
            title_in_filename = self._extract_title_from_filename(base_clouddrive_filename)
            if title_in_filename is None: continue

            new_title_for_filename = self._sanitize_filename(emby_title)
            if title_in_filename.lower() == new_title_for_filename.lower(): continue
            
            new_base_filename = base_clouddrive_filename.replace(title_in_filename, new_title_for_filename)
            
            new_log_entry = {
                "id": f"manual-{episode['Id']}",
                "episode_id": episode['Id'],
                "old_base_path": os.path.join(os.path.dirname(episode['Path']), base_clouddrive_filename),
                "new_base_path": os.path.join(os.path.dirname(episode['Path']), new_base_filename),
                "timestamp": datetime.now().isoformat(),
                "status": "pending_clouddrive_rename"
            }
            results.append(new_log_entry)
            ui_logger.info(f"  -> 发现待重命名项: {clouddrive_filename}", task_category=task_cat)

        ui_logger.info(f"【{task_cat}】扫描完成，共发现 {len(results)} 个可重命名的项目。", task_category=task_cat)
        
        if results:
            lock_path = RENAME_LOG_FILE + ".lock"
            with FileLock(lock_path, timeout=10):
                if os.path.exists(RENAME_LOG_FILE):
                    with open(RENAME_LOG_FILE, 'r', encoding='utf-8') as f:
                        all_logs = json.load(f)
                else:
                    all_logs = []
                
                existing_ids = {log['episode_id'] for log in all_logs}
                new_logs_to_add = [log for log in results if log['episode_id'] not in existing_ids]
                
                if new_logs_to_add:
                    all_logs.extend(new_logs_to_add)
                    with open(RENAME_LOG_FILE, 'w', encoding='utf-8') as f:
                        json.dump(all_logs, f, indent=4, ensure_ascii=False)
                    ui_logger.info(f"【{task_cat}】已将 {len(new_logs_to_add)} 个新发现的项目追加到日志文件中。", task_category=task_cat)

        task_manager.update_task_result(task_id, results)
        return results