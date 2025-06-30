# backend/episode_refresher_logic.py (最终修复版)

import logging
import threading
import time
import requests
import base64
import re # --- 新增导入 re ---
from typing import List, Iterable, Optional, Dict
from collections import defaultdict

from log_manager import ui_logger
from models import AppConfig, EpisodeRefresherConfig
from task_manager import TaskManager
from tmdb_logic import TmdbLogic

class EpisodeRefresherLogic:
    def __init__(self, app_config: AppConfig):
        # ... (init 方法保持不变) ...
        self.app_config = app_config
        self.server_config = app_config.server_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.session = requests.Session()
        self.tmdb_logic = TmdbLogic(app_config)

    # --- 新增：用于智能跳过的辅助函数 ---
    @staticmethod
    def _is_generic_episode_title(text: str) -> bool:
        """判断标题是否为“第X集”这种通用格式"""
        if not text: return True
        # 匹配 "第 1 集", "Episode 1", "第1集" 等格式
        pattern = re.compile(r'^(第\s*\d+\s*集|Episode\s*\d+)$', re.IGNORECASE)
        return bool(pattern.match(text.strip()))

    def _unlock_item(self, item_id: str, task_cat: str) -> bool:
        # ... (此函数保持不变) ...
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
        # ... (此函数保持不变) ...
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
        # ... (此函数保持不变) ...
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

    def _refresh_season_by_toolbox(self, series_tmdb_id: str, season_number: int, emby_episodes: List[Dict], task_cat: str) -> int:
        updated_count = 0
        try:
            series_name_for_log = emby_episodes[0].get("SeriesName", f"剧集 {series_tmdb_id}")
            ui_logger.info(f"  -> [工具箱模式] 正在为《{series_name_for_log}》S{season_number:02d} 获取整季TMDB数据...", task_category=task_cat)
            tmdb_season_details = self.tmdb_logic.get_season_details(int(series_tmdb_id), season_number)

            if not tmdb_season_details or not tmdb_season_details.get("episodes"):
                ui_logger.warning(f"     - 未能从TMDB获取到 S{season_number:02d} 的有效分集列表。", task_category=task_cat)
                return 0
            
            tmdb_episodes_map = {ep.get("episode_number"): ep for ep in tmdb_season_details["episodes"]}

            for emby_episode in emby_episodes:
                episode_num = emby_episode.get("IndexNumber")
                if episode_num is None:
                    continue
                
                log_prefix = f"     - 《{series_name_for_log}》S{season_number:02d}E{episode_num:02d}:"

                tmdb_episode = tmdb_episodes_map.get(episode_num)
                if not tmdb_episode:
                    ui_logger.debug(f"{log_prefix} 在TMDB返回的列表中未找到对应分集。", task_category=task_cat)
                    continue

                update_payload = emby_episode
                all_changes_log = []
                missing_log = []

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
                tmdb_still_path = tmdb_episode.get("still_path")
                if not tmdb_still_path:
                    missing_log.append("图片")
                elif not emby_has_image:
                    ui_logger.info(f"{log_prefix} Emby缺少图片，尝试从TMDB更新...", task_category=task_cat)
                    image_url = f"https://image.tmdb.org/t/p/original{tmdb_still_path}"
                    if self._upload_image_from_url(emby_episode["Id"], image_url, task_cat):
                        image_updated_successfully = True
                        all_changes_log.append("图片")
                    else:
                        ui_logger.error(f"{log_prefix} 图片更新失败。", task_category=task_cat)

                # --- 核心修改 2：优化“无需更新”的日志 ---
                if not all_changes_log:
                    if missing_log:
                        ui_logger.info(f"{log_prefix} 无需更新 (TMDB源缺少: {', '.join(missing_log)})", task_category=task_cat)
                    else:
                        ui_logger.info(f"{log_prefix} 元数据和图片均无需更新。", task_category=task_cat)
                    continue
                
                if any(item != "图片" for item in all_changes_log):
                    if self._unlock_item(emby_episode["Id"], task_cat):
                        update_url = f"{self.base_url}/Items/{emby_episode['Id']}"
                        headers = {'Content-Type': 'application/json'}
                        update_resp = self.session.post(update_url, params=self.params, json=update_payload, headers=headers, timeout=20)
                        update_resp.raise_for_status()
                    else:
                        ui_logger.error(f"{log_prefix} 解锁失败，跳过元数据更新。", task_category=task_cat)
                        all_changes_log = [item for item in all_changes_log if item == "图片"]
                
                if all_changes_log:
                    ui_logger.info(f"{log_prefix} 成功更新到Emby，内容: [{', '.join(all_changes_log)}]", task_category=task_cat)
                    updated_count += 1

                time.sleep(0.2)

        except Exception as e:
            ui_logger.error(f"     - 处理 S{season_number:02d} 时发生错误: {e}", task_category=task_cat, exc_info=True)
        
        return updated_count

    def run_refresh_for_episodes(
        self, 
        episode_ids: Iterable[str], 
        config: EpisodeRefresherConfig, 
        cancellation_event: threading.Event, 
        task_id: Optional[str] = None, 
        task_manager: Optional[TaskManager] = None,
        task_category: str = "剧集刷新"
    ):
        episode_ids_list = list(episode_ids)
        total_episodes = len(episode_ids_list)
        
        ui_logger.info(f"任务启动，共需处理 {total_episodes} 个剧集分集。", task_category=task_category)
        ui_logger.info(f"  - 刷新模式: {'工具箱代理刷新' if config.refresh_mode == 'toolbox' else '通知Emby刷新'}", task_category=task_category)
        # --- 核心修改 1：为 Emby 模式增加元数据写入方式日志 ---
        if config.refresh_mode == 'emby':
            ui_logger.info(f"  - 元数据写入方式: {'覆盖所有元数据' if config.overwrite_metadata else '仅补充缺失'}", task_category=task_category)
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
                fields_to_get = "SeriesId,SeriesName,Name,Overview,ImageTags,IndexNumber,ParentIndexNumber,PremiereDate,ProviderIds,LockedFields"
                details_url = f"{self.base_url}/Users/{self.user_id}/Items/{episode_id}"
                details_params = {**self.params, "Fields": fields_to_get}
                details_resp = self.session.get(details_url, params=details_params, timeout=15)
                details_resp.raise_for_status()
                all_episode_details.append(details_resp.json())
            except requests.RequestException as e:
                logging.error(f"【剧集刷新】获取分集详情 (ID: {episode_id}) 失败: {e}，跳过此分集。")
        
        if cancellation_event.is_set():
            ui_logger.warning("任务在预处理阶段被取消。", task_category=task_category)
            return

        episodes_to_process = []
        if config.skip_if_complete:
            for ep in all_episode_details:
                # --- 核心修改 3：增强智能跳过的判断逻辑 ---
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
                    refreshed_count += self._refresh_season_by_toolbox(series_tmdb_id, season_number, emby_episodes, task_category)
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
                time.sleep(0.5)

        ui_logger.info(f"任务执行完毕。共成功处理 {refreshed_count} 个分集。", task_category=task_category)
        if config.refresh_mode == 'emby':
            ui_logger.warning("请注意：Emby 的刷新是在后台进行的，实际元数据更新可能会有延迟。请稍后在 Emby 中查看结果。", task_category=task_category)
        return {"refreshed_count": refreshed_count}