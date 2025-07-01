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

    @staticmethod
    def _is_generic_episode_title(text: str) -> bool:
        """判断是否为通用、无意义的标题，如 'Episode 5', '第 5 集'"""
        if not text:
            return True
        pattern = re.compile(r'^(第\s*\d+\s*集|Episode\s*\d+)$', re.IGNORECASE)
        return bool(pattern.match(text.strip()))

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """清理文件名中的非法字符"""
        return re.sub(r'[\\/*?:"<>|]', '_', name)

    def _get_episode_details(self, episode_id: str) -> Optional[Dict]:
        """获取单个分集的详细信息"""
        import requests
        try:
            url = f"{self.base_url}/Users/{self.user_id}/Items/{episode_id}"
            params = {**self.params, "Fields": "Path,Name,SeriesName"}
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"【剧集重命名】获取分集详情 (ID: {episode_id}) 失败: {e}")
            return None

    def _extract_title_from_filename(self, filename: str) -> Optional[str]:
        """从文件名中提取标题部分"""
        match = re.search(r'S\d{2}E\d{2}\s*-\s*(.*?)\s*-\s*\w+$', filename, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _rename_associated_files(self, old_base_path: str, new_base_path: str, task_cat: str) -> bool:
        """重命名 .strm, .nfo, 和 -thumb.jpg 文件"""
        renamed_any = False
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

    def run_rename_for_episodes(self, episode_ids: Iterable[str], config: "EpisodeRenamerConfig", cancellation_event: threading.Event, task_id: str, task_manager: TaskManager, task_category: str):
        """为指定的剧集分集ID列表执行重命名任务"""
        episode_ids_list = list(episode_ids)
        total_episodes = len(episode_ids_list)
        
        ui_logger.info(f"任务启动，共需处理 {total_episodes} 个剧集分集。", task_category=task_category)
        
        if task_manager and task_id:
            task_manager.update_task_progress(task_id, 0, total_episodes)

        if total_episodes == 0:
            ui_logger.info("没有需要处理的剧集分集，任务结束。", task_category=task_category)
            return {"renamed_count": 0}

        series_results = {}

        for index, episode_id in enumerate(episode_ids_list):
            if cancellation_event.is_set():
                ui_logger.warning("任务被用户取消。", task_category=task_category)
                break
            
            if task_manager and task_id:
                task_manager.update_task_progress(task_id, index + 1, total_episodes)

            details = self._get_episode_details(episode_id)
            if not details:
                continue

            series_name = details.get("SeriesName", "未知剧集")
            if series_name not in series_results:
                series_results[series_name] = {"success": 0, "skipped": 0, "skipped_reasons": set()}

            emby_path = details.get("Path")
            emby_title = details.get("Name")

            if not emby_path or not emby_title:
                ui_logger.debug(f"  -> 跳过分集 {episode_id}，缺少路径或标题信息。", task_category=task_category)
                series_results[series_name]["skipped"] += 1
                series_results[series_name]["skipped_reasons"].add("信息不全")
                continue

            if self._is_generic_episode_title(emby_title):
                ui_logger.debug(f"  -> 跳过分集 {episode_id}，Emby 标题 '{emby_title}' 是通用标题。", task_category=task_category)
                series_results[series_name]["skipped"] += 1
                series_results[series_name]["skipped_reasons"].add("通用标题")
                continue

            dir_name = os.path.dirname(emby_path)
            base_filename, ext = os.path.splitext(os.path.basename(emby_path))
            
            old_title_in_filename = self._extract_title_from_filename(base_filename)
            if old_title_in_filename is None:
                ui_logger.debug(f"  -> 跳过文件 '{base_filename}'，无法从中解析出标题部分。", task_category=task_category)
                series_results[series_name]["skipped"] += 1
                series_results[series_name]["skipped_reasons"].add("无法解析文件名")
                continue

            new_title_for_filename = self._sanitize_filename(emby_title)

            if old_title_in_filename.lower() == new_title_for_filename.lower():
                ui_logger.debug(f"  -> 跳过文件 '{base_filename}'，文件名中的标题已是最新。", task_category=task_category)
                series_results[series_name]["skipped"] += 1
                series_results[series_name]["skipped_reasons"].add("已是最新")
                continue

            ui_logger.info(f"  -> 检测到需要重命名的分集: {base_filename}", task_category=task_category)
            ui_logger.info(f"     - 旧标题: '{old_title_in_filename}' -> 新标题: '{new_title_for_filename}'", task_category=task_category)

            new_base_filename = base_filename.replace(old_title_in_filename, new_title_for_filename)
            
            old_base_path = os.path.join(dir_name, base_filename)
            new_base_path = os.path.join(dir_name, new_base_filename)

            if self._rename_associated_files(old_base_path, new_base_path, task_category):
                series_results[series_name]["success"] += 1
                self._log_rename_operation(episode_id, f"{old_base_path}.strm", f"{new_base_path}.strm", task_category)
            else:
                series_results[series_name]["skipped"] += 1
                series_results[series_name]["skipped_reasons"].add("文件操作失败")

        ui_logger.info("="*20 + " 任务执行摘要 " + "="*20, task_category=task_category)
        total_renamed_count = 0
        for series, result in series_results.items():
            total_renamed_count += result["success"]
            if result["success"] == 0 and result["skipped"] > 0:
                reasons = ", ".join(result["skipped_reasons"])
                ui_logger.info(f"【{series}】-- 全部 {result['skipped']} 个分集已跳过 (原因: {reasons})", task_category=task_category)
            elif result["success"] > 0:
                reasons = ", ".join(result["skipped_reasons"])
                log_msg = f"【{series}】-- 成功重命名 {result['success']} 组文件"
                if result["skipped"] > 0:
                    log_msg += f"，跳过 {result['skipped']} 组 (原因: {reasons})"
                ui_logger.info(log_msg, task_category=task_category)
        
        ui_logger.info("="*50, task_category=task_category)
        ui_logger.info(f"任务执行完毕。共成功重命名了 {total_renamed_count} 组文件。", task_category=task_category)
        return {"renamed_count": total_renamed_count}
    
    def scan_series_for_rename_plan(self, series_id: str, path_from: str, path_to: str, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager, task_category: str):
        """
        扫描单个剧集，比对Emby和网盘文件，生成重命名计划。
        这个函数不依赖 rename_log.json。
        """
        import requests
        
        # 步骤 1: 获取该剧集下的所有分集信息
        ui_logger.info(f"【网盘扫描】开始获取剧集 (ID: {series_id}) 的所有分集信息...", task_category=task_category)
        all_episodes = []
        try:
            episodes_url = f"{self.server_config.server}/Items"
            episodes_params = {
                "api_key": self.server_config.api_key,
                "ParentId": series_id,
                "IncludeItemTypes": "Episode",
                "Recursive": "true",
                "Fields": "Path,Name,SeriesName,ParentId,IndexNumber"
            }
            episodes_resp = requests.get(episodes_url, params=episodes_params, timeout=60)
            episodes_resp.raise_for_status()
            all_episodes = episodes_resp.json().get("Items", [])
            if not all_episodes:
                ui_logger.warning("【网盘扫描】未找到该剧集的任何分集。", task_category=task_category)
                return []
        except requests.RequestException as e:
            ui_logger.error(f"【网盘扫描】获取剧集 {series_id} 的分集时失败: {e}", task_category=task_category)
            return []

        ui_logger.info(f"【网盘扫描】获取到 {len(all_episodes)} 个分集，开始逐一比对...", task_category=task_category)
        task_manager.update_task_progress(task_id, 0, len(all_episodes))

        rename_plan = []
        processed_dirs = set() # 避免重复扫描同一个目录

        for index, episode in enumerate(all_episodes):
            if cancellation_event.is_set():
                ui_logger.warning("【网盘扫描】任务被用户取消。", task_category=task_category)
                break
            
            task_manager.update_task_progress(task_id, index + 1, len(all_episodes))

            emby_path = episode.get("Path")
            emby_title = episode.get("Name")
            series_name = episode.get("SeriesName", "未知剧集")
            
            if not emby_path or not emby_title or self._is_generic_episode_title(emby_title):
                continue

            # 步骤 2: 确定要扫描的网盘目录
            local_dir_path = os.path.dirname(emby_path)
            
            # 应用路径转换
            local_dir_path_norm = local_dir_path.replace('\\', '/')
            path_from_norm = path_from.replace('\\', '/')
            path_to_norm = path_to.replace('\\', '/')

            if not local_dir_path_norm.startswith(path_from_norm):
                ui_logger.warning(f"【网盘扫描】路径转换失败: Emby目录 '{local_dir_path_norm}' 不以 '{path_from_norm}' 开头。", task_category=task_category)
                continue
            
            cloud_dir_path = local_dir_path_norm.replace(path_from_norm, path_to_norm, 1)

            # 步骤 3: 扫描网盘目录 (仅在首次遇到该目录时扫描)
            if cloud_dir_path not in processed_dirs:
                ui_logger.info(f"【网盘扫描】正在扫描目录: {cloud_dir_path}", task_category=task_category)
                processed_dirs.add(cloud_dir_path)

            if not os.path.isdir(cloud_dir_path):
                ui_logger.warning(f"【网盘扫描】转换后的网盘目录不存在，跳过: {cloud_dir_path}", task_category=task_category)
                continue

            try:
                cloud_files = os.listdir(cloud_dir_path)
            except OSError as e:
                ui_logger.error(f"【网盘扫描】读取网盘目录失败: {cloud_dir_path}。错误: {e}", task_category=task_category)
                continue

            # 步骤 4: 匹配文件
            local_base_filename, _ = os.path.splitext(os.path.basename(emby_path))
            old_title_in_local_filename = self._extract_title_from_filename(local_base_filename)
            
            if old_title_in_local_filename is None:
                continue
            
            # 稳定部分 = 文件名中除了标题之外的所有内容
            stable_part_of_filename = local_base_filename.replace(old_title_in_local_filename, "###TITLE_PLACEHOLDER###")

            for cloud_filename in cloud_files:
                cloud_base_filename, _ = os.path.splitext(cloud_filename)
                old_title_in_cloud_filename = self._extract_title_from_filename(cloud_base_filename)
                
                if old_title_in_cloud_filename is None:
                    continue

                stable_part_of_cloud_filename = cloud_base_filename.replace(old_title_in_cloud_filename, "###TITLE_PLACEHOLDER###")

                if stable_part_of_filename == stable_part_of_cloud_filename:
                    # 找到了对应的网盘文件
                    new_sanitized_title = self._sanitize_filename(emby_title)
                    
                    if old_title_in_cloud_filename.lower() != new_sanitized_title.lower():
                        # 网盘文件名中的标题与Emby中的新标题不一致，需要重命名
                        new_cloud_base_filename = cloud_base_filename.replace(old_title_in_cloud_filename, new_sanitized_title)
                        
                        rename_plan.append({
                            "series_name": series_name,
                            "episode_number": episode.get("IndexNumber"),
                            "old_filename": cloud_filename,
                            "new_filename": f"{new_cloud_base_filename}{os.path.splitext(cloud_filename)[1]}",
                            "cloud_dir_path": cloud_dir_path
                        })
                        # 找到一个匹配后就跳出内层循环
                        break
        
        ui_logger.info(f"【网盘扫描】扫描完成，共生成 {len(rename_plan)} 条重命名建议。", task_category=task_category)
        return rename_plan