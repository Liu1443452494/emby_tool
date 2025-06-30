# 文件: backend/episode_refresher_logic.py

import logging
import threading
import time
import requests
import base64
import re
import os  # 新增导入
import json # 新增导入
import subprocess # 新增导入
import uuid # 新增导入
from typing import List, Iterable, Optional, Dict
from collections import defaultdict

from log_manager import ui_logger
from models import AppConfig, EpisodeRefresherConfig
from task_manager import TaskManager
from tmdb_logic import TmdbLogic

class EpisodeRefresherLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.server_config = app_config.server_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.session = requests.Session()
        self.tmdb_logic = TmdbLogic(app_config)

    # --- 核心修复：在此类中添加 _get_emby_item_details 方法 ---
    def _get_emby_item_details(self, item_id: str, fields: str) -> Optional[Dict]:
        """获取 Emby 媒体项的详细信息"""
        url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
        params = {**self.params, "Fields": fields}
        try:
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            # 这是一个底层错误，不直接展示给用户，所以保留 logging
            logging.error(f"【剧集刷新】获取 Emby 媒体详情 (ID: {item_id}) 失败: {e}")
            return None
    # --- 结束修复 ---

    @staticmethod
    def _is_generic_episode_title(text: str) -> bool:
        # ... (此方法保持不变) ...
        if not text: return True
        pattern = re.compile(r'^(第\s*\d+\s*集|Episode\s*\d+)$', re.IGNORECASE)
        return bool(pattern.match(text.strip()))

    def _unlock_item(self, item_id: str, task_cat: str) -> bool:
        # ... (此方法保持不变) ...
        try:
            details_url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
            details_resp = self.session.get(details_url, params=self.params, timeout=15)
            details_resp.raise_for_status()
            item_details = details_resp.json()
            if item_details.get("LockedFields") and len(item_details["LockedFields"]) > 0:
                ui_logger.debug(f"     - 检测到锁定的字段: {item_details['LockedFields']}，正在解锁...", task_category=task_cat)
                item_details["LockedFields"] = []
                update_url = f"{self.base_url}/Items/{item_id}"
                headers = {'Content-Type': 'application/json'}
                update_resp = self.session.post(update_url, params=self.params, json=item_details, headers=headers, timeout=20)
                update_resp.raise_for_status()
                ui_logger.debug(f"     - 媒体项 (ID: {item_id}) 已成功解锁。", task_category=task_cat)
            else:
                ui_logger.debug(f"     - 媒体项 (ID: {item_id}) 无需解锁。", task_category=task_cat)
            return True
        except requests.RequestException as e:
            ui_logger.error(f"     - 解锁媒体项 (ID: {item_id}) 时发生网络错误: {e}", task_category=task_cat)
            return False
        except Exception as e:
            ui_logger.error(f"     - 解锁媒体项 (ID: {item_id}) 时发生未知错误: {e}", task_category=task_cat, exc_info=True)
            return False

    def _refresh_single_episode_by_emby(self, episode_id: str, config: EpisodeRefresherConfig, task_cat: str) -> bool:
        # ... (此方法保持不变) ...
        try:
            if not self._unlock_item(episode_id, task_cat):
                ui_logger.warning(f"     - 解锁媒体项 (ID: {episode_id}) 失败，刷新可能不会生效。", task_category=task_cat)
            
            url = f"{self.base_url}/Items/{episode_id}/Refresh"
            params = {
                **self.params,
                "Recursive": "true",
                "MetadataRefreshMode": "FullRefresh",
                "ImageRefreshMode": "FullRefresh",
                "ReplaceAllMetadata": str(config.overwrite_metadata).lower(),
                "ReplaceAllImages": "true"
            }
            ui_logger.debug(f"     - [Emby模式] 发送刷新请求到: {url}", task_category=task_cat)
            
            response = self.session.post(url, params=params, timeout=30)
            response.raise_for_status()
            
            if response.status_code == 204:
                ui_logger.debug(f"     - [Emby模式] Emby 服务器已成功接收刷新请求 (ID: {episode_id})。", task_category=task_cat)
                return True
            else:
                ui_logger.warning(f"     - [Emby模式] Emby 服务器返回异常状态码 {response.status_code} (ID: {episode_id})。", task_category=task_cat)
                return False

        except requests.RequestException as e:
            ui_logger.error(f"     - [Emby模式] 刷新分集 (ID: {episode_id}) 时发生网络错误: {e}", task_category=task_cat)
            return False

    def _upload_image_from_url(self, item_id: str, image_url: str, task_cat: str) -> bool:
        # ... (此方法保持不变) ...
        try:
            ui_logger.debug(f"     - 正在从URL下载图片: {image_url}", task_category=task_cat)
            proxies = self.tmdb_logic.proxy_manager.get_proxies(image_url)
            image_response = self.tmdb_logic.session.get(image_url, timeout=30, proxies=proxies)
            image_response.raise_for_status()
            image_data = image_response.content
            content_type = image_response.headers.get('Content-Type', 'image/jpeg')

            upload_url = f"{self.base_url}/Items/{item_id}/Images/Primary"
            
            try:
                self.session.delete(upload_url, params=self.params, timeout=20)
            except requests.RequestException as e:
                ui_logger.warning(f"     - 删除旧主图时发生错误（可能是正常的）: {e}", task_category=task_cat)

            base64_encoded_data = base64.b64encode(image_data).decode('utf-8')
            
            headers = {'Content-Type': content_type}
            
            upload_response = self.session.post(
                upload_url, 
                params=self.params, 
                data=base64_encoded_data,
                headers=headers, 
                timeout=60
            )
            upload_response.raise_for_status()
            return True
        except Exception as e:
            ui_logger.error(f"     - 上传图片到 Emby (ID: {item_id}) 失败: {e}", task_category=task_cat, exc_info=True)
            return False

    def _refresh_season_by_toolbox(self, series_tmdb_id: str, season_number: int, emby_episodes: List[Dict], config: EpisodeRefresherConfig, task_cat: str) -> int:
        # ... (此方法保持不变) ...
        updated_count = 0
        try:
            series_name_for_log = emby_episodes[0].get("SeriesName", f"剧集 {series_tmdb_id}")
            ui_logger.info(f"  -> [工具箱模式] 正在为《{series_name_for_log}》S{season_number:02d} 获取整季TMDB数据...", task_category=task_cat)
            tmdb_season_details = self.tmdb_logic.get_season_details(int(series_tmdb_id), season_number)

            if not tmdb_season_details or not tmdb_season_details.get("episodes"):
                ui_logger.warning(f"     - 未能从TMDB获取到 S{season_number:02d} 的有效分集列表。", task_category=task_cat)
                tmdb_episodes_map = {}
            else:
                tmdb_episodes_map = {ep.get("episode_number"): ep for ep in tmdb_season_details["episodes"]}

            for emby_episode in emby_episodes:
                episode_num = emby_episode.get("IndexNumber")
                if episode_num is None:
                    continue
                
                log_prefix = f"     - 《{series_name_for_log}》S{season_number:02d}E{episode_num:02d}:"

                tmdb_episode = tmdb_episodes_map.get(episode_num)
                
                update_payload = emby_episode
                all_changes_log = []
                missing_log = []

                if tmdb_episode:
                    tmdb_name = tmdb_episode.get("name")
                    if tmdb_name and not self._is_generic_episode_title(tmdb_name) and tmdb_name != update_payload.get("Name"):
                        update_payload["Name"] = tmdb_name
                        all_changes_log.append("标题")
                    elif not tmdb_name:
                        missing_log.append("标题")

                    tmdb_overview = tmdb_episode.get("overview")
                    if tmdb_overview and tmdb_overview != update_payload.get("Overview"):
                        update_payload["Overview"] = tmdb_overview
                        all_changes_log.append("简介")
                    elif not tmdb_overview:
                        missing_log.append("简介")

                    tmdb_air_date = tmdb_episode.get("air_date")
                    if tmdb_air_date:
                        emby_premiere_date = update_payload.get("PremiereDate", "")
                        if not emby_premiere_date or tmdb_air_date != emby_premiere_date[:10]:
                            update_payload["PremiereDate"] = tmdb_air_date + "T00:00:00.000Z"
                            all_changes_log.append("首播日期")
                    elif not tmdb_air_date:
                        missing_log.append("首播日期")
                
                image_updated_successfully = False
                emby_has_image = bool(emby_episode.get("ImageTags", {}).get("Primary"))
                tmdb_still_path = tmdb_episode.get("still_path") if tmdb_episode else None

                if tmdb_still_path:
                    if not emby_has_image:
                        ui_logger.info(f"{log_prefix} Emby缺少图片，尝试从TMDB更新...", task_category=task_cat)
                        image_url = f"https://image.tmdb.org/t/p/original{tmdb_still_path}"
                        if self._upload_image_from_url(emby_episode["Id"], image_url, task_cat):
                            image_updated_successfully = True
                            all_changes_log.append("图片(TMDB)")
                        else:
                            ui_logger.error(f"{log_prefix} 图片更新失败。", task_category=task_cat)
                else:
                    missing_log.append("图片")
                    if not emby_has_image and config.enable_emby_screenshot:
                        ui_logger.info(f"{log_prefix} TMDB和Emby均无图片，尝试调用Emby截图...", task_category=task_cat)
                        if self._screenshot_by_emby(emby_episode, config, task_cat):
                            image_updated_successfully = True
                            all_changes_log.append("图片(Emby截图)")
                        else:
                            ui_logger.error(f"{log_prefix} Emby截图失败。", task_category=task_cat)

                if not all_changes_log:
                    if missing_log:
                        ui_logger.info(f"{log_prefix} 无需更新 (TMDB源缺少: {', '.join(missing_log)})", task_category=task_cat)
                    else:
                        ui_logger.info(f"{log_prefix} 元数据和图片均无需更新。", task_category=task_cat)
                    continue
                
                if any(item for item in all_changes_log if not item.startswith("图片")):
                    if self._unlock_item(emby_episode["Id"], task_cat):
                        update_url = f"{self.base_url}/Items/{emby_episode['Id']}"
                        headers = {'Content-Type': 'application/json'}
                        update_resp = self.session.post(update_url, params=self.params, json=update_payload, headers=headers, timeout=20)
                        update_resp.raise_for_status()
                    else:
                        ui_logger.error(f"{log_prefix} 解锁失败，跳过元数据更新。", task_category=task_cat)
                        all_changes_log = [item for item in all_changes_log if item.startswith("图片")]
                
                if all_changes_log:
                    ui_logger.info(f"{log_prefix} 成功更新到Emby，内容: [{', '.join(all_changes_log)}]", task_category=task_cat)
                    updated_count += 1

                time.sleep(0.2)

        except Exception as e:
            ui_logger.error(f"     - 处理 S{season_number:02d} 时发生错误: {e}", task_category=task_cat, exc_info=True)
        
        return updated_count

    def _screenshot_by_emby(self, episode_details: Dict, config: EpisodeRefresherConfig, task_cat: str) -> bool:
        """
        通过在后端容器内调用 FFmpeg，为分集截图并上传。
        """
        episode_id = episode_details.get("Id")
        strm_path = episode_details.get("Path")

        if not strm_path or not os.path.exists(strm_path):
            ui_logger.warning(f"     - 无法截图，找不到 .strm 文件路径或文件不存在: {strm_path}", task_category=task_cat)
            return False

        try:
            with open(strm_path, 'r', encoding='utf-8') as f:
                video_url = f.readline().strip()
            if not video_url.startswith(('http://', 'https://')):
                ui_logger.warning(f"     - 无法截图，.strm 文件中内容不是有效的 URL: {video_url}", task_category=task_cat)
                return False
        except Exception as e:
            ui_logger.error(f"     - 读取 .strm 文件失败: {e}", task_category=task_cat)
            return False

        # 创建临时文件路径
        temp_dir = "/app/data/temp"
        os.makedirs(temp_dir, exist_ok=True)
        temp_image_path = os.path.join(temp_dir, f"{uuid.uuid4()}.jpg")
        
        seek_time = "00:01:30" # 默认降级时间
        log_msg_suffix = "在第 90 秒位置 (备用方案)"

        # 步骤1: 尝试用 ffprobe 获取时长
        try:
            ui_logger.debug("     - 步骤1: 尝试使用 ffprobe 分析视频流...", task_category=task_cat)
            ffprobe_cmd = [
                'ffprobe',
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                video_url
            ]
            result = subprocess.run(ffprobe_cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                duration_sec = float(result.stdout.strip())
                percent = max(1, min(99, config.screenshot_time_percent))
                seek_seconds = int(duration_sec * (percent / 100.0))
                seek_time = time.strftime('%H:%M:%S', time.gmtime(seek_seconds))
                log_msg_suffix = f"在 {percent}% 位置"
                ui_logger.success(f"     - ffprobe 分析成功，视频时长 {duration_sec:.2f}s，将在 {seek_time} ({log_msg_suffix}) 截图。", task_category=task_cat)
            else:
                ui_logger.warning("     - ffprobe 分析失败或无时长返回，将使用默认时间点截图。", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"     - 执行 ffprobe 时出错: {e}", task_category=task_cat)

        # 步骤2: 使用 ffmpeg 截图
        try:
            ui_logger.info(f"     - 步骤2: 正在调用 FFmpeg {log_msg_suffix} 截图...", task_category=task_cat)
            ffmpeg_cmd = [
                'ffmpeg',
                '-ss', seek_time,
                '-i', video_url,
                '-vframes', '1',
                '-q:v', '2',
                '-y', # 覆盖输出文件
                temp_image_path
            ]
            subprocess.run(ffmpeg_cmd, check=True, capture_output=True, timeout=60)
            
            if not os.path.exists(temp_image_path):
                raise FileNotFoundError("FFmpeg 执行后未生成截图文件。")

            ui_logger.info("     - FFmpeg 截图成功。", task_category=task_cat)

            # 步骤3: 上传图片
            with open(temp_image_path, 'rb') as f:
                image_data = f.read()
            
            upload_url = f"{self.base_url}/Items/{episode_id}/Images/Primary"
            headers = {'Content-Type': 'image/jpeg'}
            base64_encoded_data = base64.b64encode(image_data).decode('utf-8')
            
            upload_response = self.session.post(upload_url, params=self.params, data=base64_encoded_data, headers=headers, timeout=60)
            upload_response.raise_for_status()
            
            ui_logger.success("     - 步骤3: 截图上传成功！", task_category=task_cat)
            return True

        except subprocess.CalledProcessError as e:
            error_output = e.stderr.decode('utf-8', errors='ignore')
            ui_logger.error(f"     - FFmpeg 执行失败。返回码: {e.returncode}", task_category=task_cat)
            ui_logger.error(f"     - FFmpeg 错误输出: {error_output.strip().splitlines()[-2:]}", task_category=task_cat) # 只显示最后几行关键错误
            return False
        except Exception as e:
            ui_logger.error(f"     - 截图或上传过程中发生未知错误: {e}", task_category=task_cat, exc_info=True)
            return False
        finally:
            # 步骤4: 清理临时文件
            if os.path.exists(temp_image_path):
                os.remove(temp_image_path)
                ui_logger.debug(f"     - 已清理临时文件: {temp_image_path}", task_category=task_cat)

    def run_refresh_for_episodes(self, episode_ids: Iterable[str], config: EpisodeRefresherConfig, cancellation_event: threading.Event, task_id: Optional[str] = None, task_manager: Optional[TaskManager] = None, task_category: str = "剧集刷新"):
        # ... (此方法保持不变) ...
        episode_ids_list = list(episode_ids)
        total_episodes = len(episode_ids_list)
        
        ui_logger.info(f"任务启动，共需处理 {total_episodes} 个剧集分集。", task_category=task_category)
        ui_logger.info(f"  - 刷新模式: {'工具箱代理刷新' if config.refresh_mode == 'toolbox' else '通知Emby刷新'}", task_category=task_category)
        if config.refresh_mode == 'emby':
            ui_logger.info(f"  - 元数据写入方式: {'覆盖所有元数据' if config.overwrite_metadata else '仅补充缺失'}", task_category=task_category)
        if config.enable_emby_screenshot:
            ui_logger.info(f"  - 备用截图: 已开启 (截图位置: {config.screenshot_time_percent}%)", task_category=task_category)
        
        ui_logger.info(f"  - 智能跳过: {'开启' if config.skip_if_complete else '关闭'}", task_category=task_category)
        
        if task_manager and task_id:
            task_manager.update_task_progress(task_id, 0, total_episodes)

        if total_episodes == 0:
            ui_logger.info("没有需要处理的剧集分集，任务结束。", task_category=task_category)
            return {"refreshed_count": 0}

        ui_logger.info("步骤 1/2: 正在获取并筛选需要处理的分集...", task_category=task_category)
        
        all_episode_details = []
        for index, episode_id in enumerate(episode_ids_list):
            if cancellation_event.is_set(): break
            task_manager.update_task_progress(task_id, index + 1, total_episodes)
            try:
                fields_to_get = "SeriesId,SeriesName,Name,Overview,ImageTags,IndexNumber,ParentIndexNumber,PremiereDate,ProviderIds,LockedFields,RunTimeTicks"
                details = self._get_emby_item_details(episode_id, fields=fields_to_get)
                if details:
                    all_episode_details.append(details)
            except requests.RequestException as e:
                logging.error(f"【剧集刷新】获取分集详情 (ID: {episode_id}) 失败: {e}，跳过此分集。")
        
        if cancellation_event.is_set():
            ui_logger.warning("任务在预处理阶段被取消。", task_category=task_category)
            return

        episodes_to_process = []
        if config.skip_if_complete:
            for ep in all_episode_details:
                is_title_ok = bool(ep.get("Name")) and not self._is_generic_episode_title(ep.get("Name"))
                is_overview_ok = bool(ep.get("Overview"))
                is_image_ok = bool(ep.get("ImageTags", {}).get("Primary"))
                
                if not (is_title_ok and is_overview_ok and is_image_ok):
                    episodes_to_process.append(ep)
            ui_logger.info(f"智能跳过已开启，共筛选出 {len(episodes_to_process)} / {len(all_episode_details)} 个需要处理的分集。", task_category=task_category)
        else:
            episodes_to_process = all_episode_details

        refreshed_count = 0
        
        if config.refresh_mode == 'toolbox':
            grouped_seasons = defaultdict(lambda: defaultdict(list))
            for ep in episodes_to_process:
                if ep.get("SeriesId") and ep.get("ParentIndexNumber") is not None:
                    grouped_seasons[ep["SeriesId"]][ep["ParentIndexNumber"]].append(ep)

            ui_logger.info(f"步骤 2/2: [工具箱模式] 开始按季获取TMDB数据并更新...", task_category=task_category)
            series_tmdb_id_cache = {}
            processed_ep_count = 0
            for series_id, seasons in grouped_seasons.items():
                if cancellation_event.is_set(): break
                
                series_tmdb_id = series_tmdb_id_cache.get(series_id)
                if not series_tmdb_id:
                    series_details = self.tmdb_logic._get_emby_item_details(series_id, fields="ProviderIds")
                    series_tmdb_id = next((v for k, v in series_details.get("ProviderIds", {}).items() if k.lower() == 'tmdb'), None)
                    if series_tmdb_id:
                        series_tmdb_id_cache[series_id] = series_tmdb_id
                    else:
                        ui_logger.warning(f"剧集(ID: {series_id})缺少TMDB ID，跳过该剧集的所有分集。", task_category=task_category)
                        processed_ep_count += sum(len(eps) for eps in seasons.values())
                        task_manager.update_task_progress(task_id, processed_ep_count, len(episodes_to_process))
                        continue
                
                for season_number, emby_episodes in seasons.items():
                    if cancellation_event.is_set(): break
                    refreshed_count += self._refresh_season_by_toolbox(series_tmdb_id, season_number, emby_episodes, config, task_category)
                    processed_ep_count += len(emby_episodes)
                    task_manager.update_task_progress(task_id, processed_ep_count, len(episodes_to_process))
        else:
            ui_logger.info(f"步骤 2/2: [Emby模式] 开始逐个通知Emby刷新...", task_category=task_category)
            for index, episode in enumerate(episodes_to_process):
                if cancellation_event.is_set(): break
                task_manager.update_task_progress(task_id, index + 1, len(episodes_to_process))
                
                series_name = episode.get("SeriesName", "未知剧集")
                episode_number = episode.get("IndexNumber")
                episode_title = episode.get("Name", f"分集 {episode_number}" if episode_number else f"ID {episode['Id']}")
                log_message = f"{series_name} - "
                if episode_number:
                    log_message += f"第{episode_number}集 - "
                log_message += episode_title
                ui_logger.info(f"进度 {index + 1}/{len(episodes_to_process)}: 正在刷新: {log_message}", task_category=task_category)

                if self._refresh_single_episode_by_emby(episode['Id'], config, task_category):
                    refreshed_count += 1
                
                if config.enable_emby_screenshot:
                    time.sleep(2)
                    refreshed_episode_details = self._get_emby_item_details(episode['Id'], fields="ImageTags,RunTimeTicks")
                    if refreshed_episode_details and not refreshed_episode_details.get("ImageTags", {}).get("Primary"):
                        ui_logger.info(f"     - Emby刷新后依然无图，尝试调用Emby截图...", task_category=task_category)
                        self._screenshot_by_emby(refreshed_episode_details, config, task_category)

                time.sleep(0.5)

        ui_logger.info(f"任务执行完毕。共成功处理 {refreshed_count} 个分集。", task_category=task_category)
        if config.refresh_mode == 'emby':
            ui_logger.warning("请注意：Emby 的刷新是在后台进行的，实际元数据更新可能会有延迟。请稍后在 Emby 中查看结果。", task_category=task_category)
        return {"refreshed_count": refreshed_count}