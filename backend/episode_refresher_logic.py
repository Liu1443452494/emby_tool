# backend/episode_refresher_logic.py (修改)

import logging
import threading
import time
import requests
from typing import List, Iterable, Optional

# --- 新增：导入 ui_logger ---
from log_manager import ui_logger
# --- 结束新增 ---
from models import AppConfig, EpisodeRefresherConfig
from task_manager import TaskManager

class EpisodeRefresherLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.server_config = app_config.server_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.session = requests.Session()

    def _refresh_single_episode(self, episode_id: str, config: EpisodeRefresherConfig) -> bool:
        """对单个剧集分集发送刷新请求"""
        try:
            url = f"{self.base_url}/Items/{episode_id}/Refresh"
            params = {
                **self.params,
                "MetadataRefreshMode": "FullRefresh",
                "ImageRefreshMode": "FullRefresh",
                "ReplaceAllMetadata": str(config.overwrite_metadata).lower(),
                "ReplaceAllImages": "true"
            }
            response = self.session.post(url, params=params, timeout=20)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            # 这个错误只记录在后端日志
            logging.error(f"【剧集刷新】刷新分集 (ID: {episode_id}) 失败: {e}")
            return False

    def run_refresh_for_episodes(
        self, 
        episode_ids: Iterable[str], 
        config: EpisodeRefresherConfig, 
        cancellation_event: threading.Event, 
        task_id: Optional[str] = None, 
        task_manager: Optional[TaskManager] = None,
        task_category: str = "剧集刷新" # 新增 task_category 参数
    ):
        """为指定的剧集分集ID列表执行刷新，包含智能跳过和详细日志功能"""
        episode_ids_list = list(episode_ids)
        total_episodes = len(episode_ids_list)
        
        # --- 核心修改：使用传入的 task_category ---
        ui_logger.info(f"任务启动，共需处理 {total_episodes} 个剧集分集。", task_category=task_category)
        ui_logger.info(f"  - 刷新模式: {'覆盖所有元数据' if config.overwrite_metadata else '搜索缺少的元数据'}", task_category=task_category)
        ui_logger.info(f"  - 智能跳过: {'开启' if config.skip_if_complete else '关闭'}", task_category=task_category)
        
        if task_manager and task_id:
            task_manager.update_task_progress(task_id, 0, total_episodes)

        if total_episodes == 0:
            ui_logger.info("没有需要处理的剧集分集，任务结束。", task_category=task_category)
            return {"refreshed_count": 0}

        refreshed_count = 0
        skipped_count = 0
        for index, episode_id in enumerate(episode_ids_list):
            if cancellation_event.is_set():
                ui_logger.info("任务被用户取消。", task_category=task_category)
                break
            
            try:
                details_url = f"{self.base_url}/Users/{self.user_id}/Items/{episode_id}"
                details_params = {**self.params, "Fields": "SeriesName,Name,Overview,ImageTags,IndexNumber"}
                details_resp = self.session.get(details_url, params=details_params, timeout=15)
                details_resp.raise_for_status()
                details = details_resp.json()
            except requests.RequestException as e:
                # 这个错误只记录在后端日志，不展示给用户
                logging.error(f"【剧集刷新】获取分集详情 (ID: {episode_id}) 失败: {e}，跳过此分集。")
                continue

            if config.skip_if_complete:
                has_title = bool(details.get("Name"))
                has_overview = bool(details.get("Overview"))
                has_image = bool(details.get("ImageTags", {}).get("Primary"))
                if has_title and has_overview and has_image:
                    logging.debug(f"  -> 跳过 (ID: {episode_id})，元数据已完整。")
                    skipped_count += 1
                    if task_manager and task_id:
                        task_manager.update_task_progress(task_id, index + 1, total_episodes)
                    continue
            
            series_name = details.get("SeriesName", "未知剧集")
            episode_number = details.get("IndexNumber")
            episode_title = details.get("Name", f"分集 {episode_number}" if episode_number else f"ID {episode_id}")
            
            log_message = f"{series_name} - "
            if episode_number:
                log_message += f"第{episode_number}集 - "
            log_message += episode_title
            
            ui_logger.info(f"进度 {index + 1}/{total_episodes}: 正在刷新: {log_message}", task_category=task_category)

            if self._refresh_single_episode(episode_id, config):
                refreshed_count += 1
            
            if task_manager and task_id:
                task_manager.update_task_progress(task_id, index + 1, total_episodes)
            
            time.sleep(0.2)

        ui_logger.info(f"任务执行完毕，共刷新 {refreshed_count} 个分集，跳过 {skipped_count} 个。", task_category=task_category)
        return {"refreshed_count": refreshed_count, "skipped_count": skipped_count}