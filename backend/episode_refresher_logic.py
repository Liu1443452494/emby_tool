# backend/episode_refresher_logic.py (最终修复版)

import logging
import threading
import time
import requests
from typing import List, Iterable, Optional

from log_manager import ui_logger
from models import AppConfig, EpisodeRefresherConfig
from task_manager import TaskManager

class EpisodeRefresherLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.server_config = app_config.server_config
        # 保持原始的 base_url 构建方式
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.session = requests.Session()

    def _unlock_item(self, item_id: str, task_cat: str) -> bool:
        """解锁媒体项的所有元数据字段"""
        try:
            # 1. 获取当前项目详情
            details_url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
            details_resp = self.session.get(details_url, params=self.params, timeout=15)
            details_resp.raise_for_status()
            item_details = details_resp.json()

            # 2. 如果 LockedFields 存在且不为空，则清空它
            if item_details.get("LockedFields") and len(item_details["LockedFields"]) > 0:
                ui_logger.debug(f"     - 检测到锁定的字段: {item_details['LockedFields']}，正在解锁...", task_category=task_cat)
                item_details["LockedFields"] = []
                
                # 3. 发送更新请求
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

    def _refresh_single_episode(self, episode_id: str, config: EpisodeRefresherConfig, task_cat: str) -> bool:
        """对单个剧集分集发送刷新请求"""
        try:
            # --- 核心修复：在刷新前先执行解锁操作 ---
            if not self._unlock_item(episode_id, task_cat):
                ui_logger.warning(f"     - 解锁媒体项 (ID: {episode_id}) 失败，刷新可能不会生效。", task_category=task_cat)
                # 即使解锁失败，我们仍然尝试刷新
            
            url = f"{self.base_url}/Items/{episode_id}/Refresh"
            params = {
                **self.params,
                "Recursive": "true",
                "MetadataRefreshMode": "FullRefresh",
                "ImageRefreshMode": "FullRefresh",
                "ReplaceAllMetadata": str(config.overwrite_metadata).lower(),
                "ReplaceAllImages": "true"
            }
            ui_logger.debug(f"     - 发送刷新请求到: {url}", task_category=task_cat)
            ui_logger.debug(f"     - 请求参数: {params}", task_category=task_cat)
            
            response = self.session.post(url, params=params, timeout=30)
            response.raise_for_status()
            
            if response.status_code == 204:
                ui_logger.debug(f"     - Emby 服务器已成功接收刷新请求 (ID: {episode_id})。", task_category=task_cat)
                return True
            else:
                ui_logger.warning(f"     - Emby 服务器返回异常状态码 {response.status_code} (ID: {episode_id})。", task_category=task_cat)
                return False

        except requests.RequestException as e:
            ui_logger.error(f"     - 刷新分集 (ID: {episode_id}) 时发生网络错误: {e}", task_category=task_cat)
            return False

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
                ui_logger.warning("任务被用户取消。", task_category=task_category)
                break
            
            try:
                details_url = f"{self.base_url}/Users/{self.user_id}/Items/{episode_id}"
                details_params = {**self.params, "Fields": "SeriesName,Name,Overview,ImageTags,IndexNumber"}
                details_resp = self.session.get(details_url, params=details_params, timeout=15)
                details_resp.raise_for_status()
                details = details_resp.json()
            except requests.RequestException as e:
                logging.error(f"【剧集刷新】获取分集详情 (ID: {episode_id}) 失败: {e}，跳过此分集。")
                continue

            if config.skip_if_complete:
                has_title = bool(details.get("Name"))
                has_overview = bool(details.get("Overview"))
                has_image = bool(details.get("ImageTags", {}).get("Primary"))
                if has_title and has_overview and has_image:
                    ui_logger.debug(f"  -> 跳过 (ID: {episode_id})，元数据已完整。", task_category=task_category)
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

            if self._refresh_single_episode(episode_id, config, task_category):
                refreshed_count += 1
            
            if task_manager and task_id:
                task_manager.update_task_progress(task_id, index + 1, total_episodes)
            
            time.sleep(0.5)

        ui_logger.info(f"任务执行完毕。共向 Emby 提交了 {refreshed_count} 个刷新请求，跳过了 {skipped_count} 个分集。", task_category=task_category)
        ui_logger.warning("请注意：Emby 的刷新是在后台进行的，实际元数据更新可能会有延迟。请稍后在 Emby 中查看结果。", task_category=task_category)
        return {"refreshed_count": refreshed_count, "skipped_count": skipped_count}