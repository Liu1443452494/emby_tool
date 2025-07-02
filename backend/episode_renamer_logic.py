
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

    def _trigger_emby_scan(self, series_id: str, task_cat: str):
        """触发 Emby 扫描指定剧集的文件，但不更新元数据"""
        import requests
        ui_logger.info(f"     - 正在为剧集(ID: {series_id})触发文件扫描...", task_category=task_cat)
        try:
            url = f"{self.base_url}/Items/{series_id}/Refresh"
            # 这些参数确保只扫描文件，不修改元数据或图片
            params = {
                **self.params,
                "Recursive": "true",
                "MetadataRefreshMode": "Default",
                "ImageRefreshMode": "Default",
                "ReplaceAllMetadata": "false",
                "ReplaceAllImages": "false"
            }
            response = requests.post(url, params=params, timeout=30)
            response.raise_for_status()
            ui_logger.info(f"     - 已成功向 Emby 发送扫描请求。", task_category=task_cat)
        except requests.RequestException as e:
            ui_logger.error(f"     - 触发 Emby 扫描失败: {e}", task_category=task_cat)

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
        
    def _get_latest_episode_by_series_and_number(self, series_id: str, season_number: int, episode_number: int, task_cat: str) -> Optional[Dict]:
        """通过剧集ID、季号和集号获取最新的分集详情"""
        import requests
        ui_logger.debug(f"     - 正在为剧集(ID:{series_id})查找 S{season_number:02d}E{episode_number:02d} 的最新信息...", task_category=task_cat)
        try:
            url = f"{self.base_url}/Items"
            params = {
                **self.params,
                "ParentId": series_id,
                "IncludeItemTypes": "Episode",
                "Recursive": "true",
                "Fields": "Path,Name,SeriesId,SeriesName,IndexNumber,ParentIndexNumber,MediaSources"
            }
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            episodes = response.json().get("Items", [])
            
            for ep in episodes:
                if ep.get("ParentIndexNumber") == season_number and ep.get("IndexNumber") == episode_number:
                    ui_logger.debug(f"     - 成功找到匹配的分集，新ID为: {ep['Id']}", task_category=task_cat)
                    return ep
            
            ui_logger.warning(f"     - 在剧集(ID:{series_id})下未找到 S{season_number:02d}E{episode_number:02d}。", task_category=task_cat)
            return None
        except requests.RequestException as e:
            logging.error(f"【剧集重命名】获取剧集(ID:{series_id})的分集列表时失败: {e}")
            return None

    def _extract_title_from_filename(self, filename: str) -> Optional[str]:
        """
        从文件名中提取标题部分。
        仅匹配 SXXEXX 和 -XXX 后缀之间的部分。
        如果文件名格式为 SXXEXX-XXX，则返回 None。
        """
        # 正则表达式匹配 SXXEXX - [标题] - [后缀] 的格式
        # 它会捕获 SXXEXX 和 -ADWeb (或任何后缀) 之间的所有内容
        match = re.search(r'S\d{2}E\d{2}\s*-\s*(.*?)\s*-\s*\w+$', filename, re.IGNORECASE)
        if match:
            # 确保捕获组不是空的或只包含空格
            title = match.group(1).strip()
            if title:
                return title
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

    def _log_rename_operation(self, series_id: str, season_number: int, episode_number: int, old_base_path: str, new_base_path: str, task_cat: str):
        """将重命名操作记录到 JSON 文件中"""
        log_entry = {
            "id": f"{series_id}-{season_number}-{episode_number}-{int(time.time())}",
            "series_id": series_id,
            "season_number": season_number,
            "episode_number": episode_number,
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
                
                # 检查是否已存在相同的待处理任务
                pending_exists = any(
                    log.get('series_id') == series_id and
                    log.get('season_number') == season_number and
                    log.get('episode_number') == episode_number and
                    log.get('status') == 'pending_clouddrive_rename'
                    for log in logs
                )

                if pending_exists:
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
        from collections import defaultdict
        import requests

        episode_ids_list = list(episode_ids)
        total_episodes_to_fetch = len(episode_ids_list)
        
        ui_logger.info(f"【本地重命名任务】启动，开始获取 {total_episodes_to_fetch} 个分集的详细信息...", task_category=task_category)
        
        if task_manager and task_id:
            task_manager.update_task_progress(task_id, 0, total_episodes_to_fetch)

        # 按剧集ID对分集进行分组
        series_map = defaultdict(list)
        for index, episode_id in enumerate(episode_ids_list):
            if cancellation_event.is_set():
                ui_logger.warning("任务在获取分集信息阶段被取消。", task_category=task_category)
                return
            
            details = self._get_episode_details(episode_id, fields="Path,Name,SeriesId,SeriesName,IndexNumber,ParentIndexNumber")
            if details and details.get("SeriesId"):
                series_map[details["SeriesId"]].append(details)
            
            if task_manager and task_id:
                task_manager.update_task_progress(task_id, index + 1, total_episodes_to_fetch)

        ui_logger.info(f"信息获取完毕，共涉及 {len(series_map)} 个剧集。开始逐一处理...", task_category=task_category)
        
        total_renamed_count = 0
        total_skipped_count = 0

        for series_id, episodes in series_map.items():
            if cancellation_event.is_set():
                ui_logger.warning("任务被用户取消。", task_category=task_category)
                break

            series_name = episodes[0].get("SeriesName", f"剧集ID {series_id}")
            ui_logger.info(f"--- 正在处理剧集: 【{series_name}】 ---", task_category=task_category)
            
            series_renamed_count = 0
            series_skipped_reasons = defaultdict(int)

            for episode in episodes:
                emby_path = episode.get("Path")
                emby_title = episode.get("Name")

                if not emby_path or not emby_title:
                    ui_logger.debug(f"  -> 跳过分集 {episode['Id']}，缺少路径或标题信息。", task_category=task_category)
                    series_skipped_reasons['缺少必要信息'] += 1
                    continue

                if self._is_generic_episode_title(emby_title):
                    ui_logger.debug(f"  -> 跳过分集 {episode['Id']}，Emby 标题 '{emby_title}' 是通用标题。", task_category=task_category)
                    series_skipped_reasons['通用标题'] += 1
                    continue

                dir_name = os.path.dirname(emby_path)
                base_filename, ext = os.path.splitext(os.path.basename(emby_path))
                
                new_title_for_filename = self._sanitize_filename(emby_title)
                new_base_filename = None

                old_title_in_filename = self._extract_title_from_filename(base_filename)
                
                if old_title_in_filename:
                    # 模式一：文件名中包含旧标题，执行替换
                    if old_title_in_filename.lower() == new_title_for_filename.lower():
                        ui_logger.debug(f"  -> 跳过文件 '{base_filename}'，文件名中的标题已是最新。", task_category=task_category)
                        series_skipped_reasons['标题已是最新'] += 1
                        continue
                    new_base_filename = base_filename.replace(old_title_in_filename, new_title_for_filename)
                    ui_logger.info(f"  -> 计划重命名 (替换): {base_filename}", task_category=task_category)
                    ui_logger.info(f"     - 旧标题: '{old_title_in_filename}' -> 新标题: '{new_title_for_filename}'", task_category=task_category)
                else:
                    # 模式二：文件名中无标题，尝试插入
                    no_title_match = re.search(r'(S\d{2}E\d{2})\s*-\s*(\w+)$', base_filename, re.IGNORECASE)
                    if no_title_match:
                        prefix_part = base_filename[:no_title_match.start()]
                        sxxexx_part = no_title_match.group(1)
                        suffix_part = no_title_match.group(2)
                        new_base_filename = f"{prefix_part}{sxxexx_part} - {new_title_for_filename} - {suffix_part}"
                        ui_logger.info(f"  -> 计划重命名 (插入): {base_filename}", task_category=task_category)
                        ui_logger.info(f"     - 将插入标题: '{new_title_for_filename}'", task_category=task_category)
                    else:
                        ui_logger.debug(f"  -> 跳过文件 '{base_filename}'，无法解析文件名结构。", task_category=task_category)
                        series_skipped_reasons['无法解析文件名'] += 1
                        continue

                if new_base_filename:
                    old_base_path = os.path.join(dir_name, base_filename)
                    new_base_path = os.path.join(dir_name, new_base_filename)

                    if self._rename_associated_files(old_base_path, new_base_path, task_category):
                        series_renamed_count += 1
                        self._log_rename_operation(
                            series_id=episode['SeriesId'],
                            season_number=episode['ParentIndexNumber'],
                            episode_number=episode['IndexNumber'],
                            old_base_path=old_base_path,
                            new_base_path=new_base_path,
                            task_cat=task_category
                        )

            # 单个剧集处理完毕，打印总结并触发扫描
            skipped_count = sum(series_skipped_reasons.values())
            total_skipped_count += skipped_count
            total_renamed_count += series_renamed_count

            reasons_str = ", ".join([f"{reason}: {count}" for reason, count in series_skipped_reasons.items()]) if series_skipped_reasons else "无"
            ui_logger.info(f"【{series_name}】处理完毕：成功重命名 {series_renamed_count} 组文件，跳过 {skipped_count} 组文件 (原因: {reasons_str})。", task_category=task_category)

            if series_renamed_count > 0:
                self._trigger_emby_scan(series_id, task_category)

        ui_logger.info(f"---", task_category=task_category)
        ui_logger.info(f"【本地重命名任务】全部执行完毕。共成功重命名了 {total_renamed_count} 组文件，总共跳过了 {total_skipped_count} 组文件。", task_category=task_category)
        return {"renamed_count": total_renamed_count, "skipped_count": total_skipped_count}

    def _get_clouddrive_video_path(self, episode_details: Dict, old_base_path: str, task_cat: str) -> Optional[Tuple[str, str]]:
        """通过 MediaSources 获取网盘视频的真实路径和文件名"""
        if not episode_details:
            ui_logger.error(f"     - 无法获取分集的 MediaSources，因为分集详情为空。", task_category=task_cat)
            return None

        media_sources = episode_details.get("MediaSources")
        if not media_sources or not isinstance(media_sources, list) or len(media_sources) == 0:
            ui_logger.warning(f"     - 分集 {episode_details.get('Id')} 的 MediaSources 为空，无法获取网盘文件名。", task_category=task_cat)
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
            
            series_id = log_entry['series_id']
            season_number = log_entry['season_number']
            episode_number = log_entry['episode_number']
            old_base_path = log_entry['old_base_path']
            new_base_path = log_entry['new_base_path']
            
            ui_logger.info(f"  -> 正在处理: {os.path.basename(old_base_path)}", task_category=task_cat)

            latest_episode_details = self._get_latest_episode_by_series_and_number(series_id, season_number, episode_number, task_cat)
            if not latest_episode_details:
                log_entry['error'] = "无法在Emby中找到对应的最新分集信息"
                failed_logs.append(log_entry)
                continue

            path_info = self._get_clouddrive_video_path(latest_episode_details, old_base_path, task_cat)
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

            if self.renamer_config.clouddrive_rename_cooldown > 0:
                ui_logger.debug(f"     - [网盘重命名-冷却] 等待 {self.renamer_config.clouddrive_rename_cooldown} 秒...", task_category=task_cat)
            
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
                "Fields": "Name,IndexNumber,ParentIndexNumber,Path,SeriesName,MediaSources"
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

            path_info = self._get_clouddrive_video_path(episode, episode['Path'], task_cat)
            if not path_info: continue
            
            clouddrive_path, clouddrive_filename = path_info
            base_clouddrive_filename, old_ext = os.path.splitext(clouddrive_filename)
            
            new_title_for_filename = self._sanitize_filename(emby_title)
            new_base_filename = None

            old_title_in_filename = self._extract_title_from_filename(base_clouddrive_filename)
            
            if old_title_in_filename:
                if old_title_in_filename.lower() == new_title_for_filename.lower():
                    continue
                new_base_filename = base_clouddrive_filename.replace(old_title_in_filename, new_title_for_filename)
            else:
                no_title_match = re.search(r'(S\d{2}E\d{2})\s*-\s*(\w+)$', base_clouddrive_filename, re.IGNORECASE)
                if no_title_match:
                    prefix_part = base_clouddrive_filename[:no_title_match.start()]
                    sxxexx_part = no_title_match.group(1)
                    suffix_part = no_title_match.group(2)
                    new_base_filename = f"{prefix_part}{sxxexx_part} - {new_title_for_filename} - {suffix_part}"
                else:
                    continue
            
            if not new_base_filename:
                continue

            new_log_entry = {
                "id": f"manual-{episode['Id']}",
                "series_id": episode['SeriesId'],
                "season_number": episode['ParentIndexNumber'],
                "episode_number": episode['IndexNumber'],
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
                
                existing_keys = {f"{log['series_id']}-{log['season_number']}-{log['episode_number']}" for log in all_logs if log.get('status') == 'pending_clouddrive_rename'}
                
                new_logs_to_add = []
                for log in results:
                    key = f"{log['series_id']}-{log['season_number']}-{log['episode_number']}"
                    if key not in existing_keys:
                        new_logs_to_add.append(log)
                
                if new_logs_to_add:
                    all_logs.extend(new_logs_to_add)
                    with open(RENAME_LOG_FILE, 'w', encoding='utf-8') as f:
                        json.dump(all_logs, f, indent=4, ensure_ascii=False)
                    ui_logger.info(f"【{task_cat}】已将 {len(new_logs_to_add)} 个新发现的项目追加到日志文件中。", task_category=task_cat)

        task_manager.update_task_result(task_id, results)
        return results