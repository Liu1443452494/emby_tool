# backend/chasing_center_logic.py (新文件)

import logging
import threading
import time
import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from filelock import FileLock, Timeout

from log_manager import ui_logger
from models import AppConfig, ChasingCenterConfig
from tmdb_logic import TmdbLogic
from episode_refresher_logic import EpisodeRefresherLogic
from notification_manager import notification_manager, escape_markdown
from task_manager import TaskManager

CHASING_LIST_FILE = os.path.join('/app/data', 'chasing_series.json')

class ChasingCenterLogic:
    def __init__(self, config: AppConfig):
        self.config = config
        self.chasing_config = config.chasing_center_config
        self.tmdb_logic = TmdbLogic(config)
        self.episode_refresher = EpisodeRefresherLogic(config)

    def _get_chasing_list(self) -> List[Dict[str, str]]:
        """安全地读取追更列表文件，并兼容新旧格式"""
        if not os.path.exists(CHASING_LIST_FILE):
            return []
        try:
            with open(CHASING_LIST_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # --- 新增：兼容性处理 ---
            if not data:
                return []
            
            # 如果文件内容是旧的字符串列表格式，则转换为新的对象列表格式
            if isinstance(data[0], str):
                ui_logger.info("➡️ [追更列表] 检测到旧版追更列表格式，将自动在后台进行转换...", task_category="追更中心")
                
                # 为了避免在只读操作中执行大量网络请求，我们返回一个不完整的列表，
                # 并在写入操作（如添加/删除）时进行真正的转换和填充。
                # 或者，更好的方式是在一个专门的迁移任务中完成。
                # 为简单起见，我们在这里只做结构转换，tmdb_id 暂时留空。
                # 真正的填充将在 get_detailed_chasing_list 中处理。
                return [{"emby_id": item, "tmdb_id": None} for item in data]

            return data
            # --- 新增结束 ---

        except (IOError, json.JSONDecodeError):
            return []

    def _save_chasing_list(self, series_list: List[Dict[str, str]]):
        """安全地写入追更列表文件"""
        lock_path = CHASING_LIST_FILE + ".lock"
        try:
            with FileLock(lock_path, timeout=10):
                # --- 新增：确保所有条目都有 tmdb_id ---
                # 这是一个保险措施，防止不完整的条目被写入
                final_list = [item for item in series_list if item.get("emby_id") and item.get("tmdb_id")]
                if len(final_list) != len(series_list):
                    ui_logger.warning("⚠️ [追更列表] 在保存时发现部分条目缺少 Emby ID 或 TMDB ID，已被过滤。", task_category="追更中心")

                with open(CHASING_LIST_FILE, 'w', encoding='utf-8') as f:
                    json.dump(final_list, f, indent=4)
        except Timeout:
            ui_logger.error("❌ [追更列表] 写入文件时获取锁超时！", task_category="追更中心")
        except Exception as e:
            ui_logger.error(f"❌ [追更列表] 写入文件时发生错误: {e}", task_category="追更中心")

    def get_detailed_chasing_list(self) -> List[Dict]:
        """获取聚合了 Emby 和 TMDB 信息的详细追更列表"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        chasing_items = self._get_chasing_list()
        if not chasing_items:
            return []

        detailed_list = []
        items_to_resave = False # 标记是否需要回写文件（用于旧格式迁移）

        def fetch_series_details(item_data):
            nonlocal items_to_resave
            emby_id = item_data.get("emby_id")
            tmdb_id = item_data.get("tmdb_id")
            
            try:
                # 1. 获取 Emby 基础信息
                emby_details = self.episode_refresher._get_emby_item_details(emby_id, fields="Name,ProductionYear,ProviderIds,ImageTags,BackdropImageTags")
                
                # 2. 如果文件中没有 tmdb_id (兼容旧格式)，则从 Emby 获取并标记回写
                if not tmdb_id:
                    provider_ids_lower = {k.lower(): v for k, v in emby_details.get("ProviderIds", {}).items()}
                    tmdb_id = provider_ids_lower.get("tmdb")
                    if tmdb_id:
                        item_data["tmdb_id"] = tmdb_id # 更新内存中的对象
                        items_to_resave = True
                    else:
                        # 如果 Emby 也没有，则跳过此项
                        ui_logger.warning(f"⚠️ [追更列表] 剧集《{emby_details.get('Name')}》缺少 TMDB ID，无法处理。", task_category="追更中心")
                        return None

                # 3. 获取 Emby 分集数量
                episodes_url = f"{self.config.server_config.server}/Users/{self.config.server_config.user_id}/Items"
                episodes_params = {"api_key": self.config.server_config.api_key, "ParentId": emby_id, "IncludeItemTypes": "Episode", "Recursive": "true", "Fields": "Id"}
                emby_episodes_count = self.episode_refresher.session.get(episodes_url, params=episodes_params, timeout=15).json().get("TotalRecordCount", 0)

                # 4. 获取 TMDB 详细信息
                tmdb_details = self.tmdb_logic._tmdb_request(f"tv/{tmdb_id}")
                
                image_tags = emby_details.get("ImageTags", {})
                if backdrop_tag := emby_details.get("BackdropImageTags", []):
                    image_tags['Backdrop'] = backdrop_tag[0]

                # 5. 聚合数据
                return {
                    "emby_id": emby_id,
                    "tmdb_id": tmdb_id,
                    "name": emby_details.get("Name"),
                    "year": emby_details.get("ProductionYear"),
                    "image_tags": image_tags,
                    "tmdb_status": tmdb_details.get("status"),
                    "tmdb_total_episodes": tmdb_details.get("number_of_episodes"),
                    "tmdb_first_air_date": tmdb_details.get("first_air_date"),
                    "emby_episode_count": emby_episodes_count
                }
            except Exception as e:
                logging.error(f"❌ [追更列表] 获取剧集 {emby_id} 的详细信息时失败: {e}")
                return None

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_id = {executor.submit(fetch_series_details, item): item.get("emby_id") for item in chasing_items}
            for future in as_completed(future_to_id):
                result = future.result()
                if result:
                    detailed_list.append(result)
        
        # 如果在处理过程中为旧数据填充了 tmdb_id，则回写整个文件
        if items_to_resave:
            ui_logger.info("✅ [追更列表] 已为旧格式数据填充 TMDB ID，正在保存到文件...", task_category="追更中心")
            self._save_chasing_list(chasing_items)

        return detailed_list

    def add_to_chasing_list(self, series_id: str, series_name: str):
        """将一个剧集ID和TMDB ID添加到追更列表"""
        task_cat = "追更中心"
        chasing_list = self._get_chasing_list()
        
        # 检查是否已存在
        if any(item.get("emby_id") == series_id for item in chasing_list):
            ui_logger.debug(f"剧集《{series_name}》已存在于追更列表中，无需重复添加。", task_category=task_cat)
            return

        # 获取 TMDB ID
        emby_details = self.episode_refresher._get_emby_item_details(series_id, fields="ProviderIds")
        if not emby_details:
            ui_logger.error(f"❌ [追更] 添加《{series_name}》失败：无法获取其 Emby 详情。", task_category=task_cat)
            return
            
        provider_ids_lower = {k.lower(): v for k, v in emby_details.get("ProviderIds", {}).items()}
        tmdb_id = provider_ids_lower.get("tmdb")

        if not tmdb_id:
            ui_logger.warning(f"⚠️ [追更] 添加《{series_name}》失败：该剧集缺少 TMDB ID。", task_category=task_cat)
            return

        chasing_list.append({"emby_id": series_id, "tmdb_id": tmdb_id})
        self._save_chasing_list(chasing_list)
        ui_logger.info(f"➡️ [追更] 已将剧集《{series_name}》加入追更列表。", task_category=task_cat)

    def remove_from_chasing_list(self, series_id: str, series_name: str, reason: str):
        """从追更列表中移除一个剧集"""
        task_cat = "追更中心"
        chasing_list = self._get_chasing_list()
        
        original_length = len(chasing_list)
        # 根据 emby_id 过滤掉要移除的项
        updated_list = [item for item in chasing_list if item.get("emby_id") != series_id]

        if len(updated_list) < original_length:
            self._save_chasing_list(updated_list)
            ui_logger.info(f"✅ [追更] 已将剧集《{series_name}》从追更列表移除。原因: {reason}", task_category=task_cat)

    def _check_and_remove_if_series_complete(self, series_id: str, cancellation_event: threading.Event):
        """
        执行优化后的完结检测逻辑 (V2.0)。
        """
        # --- 核心修改：直接从追更列表中获取 tmdb_id ---
        chasing_item = next((item for item in self._get_chasing_list() if item.get("emby_id") == series_id), None)
        if not chasing_item: return # 如果在列表中找不到，直接返回
        tmdb_id = chasing_item.get("tmdb_id")
        # --- 修改结束 ---

        emby_series_details = self.episode_refresher._get_emby_item_details(series_id, fields="ProviderIds,Name")
        if not emby_series_details: return
        
        series_name = emby_series_details.get("Name", f"ID {series_id}")
        task_cat = f"追更-完结检测({series_name})"

        if not tmdb_id:
            ui_logger.warning(f"剧集《{series_name}》缺少 TMDB ID，无法进行完结检测。", task_category=task_cat)
            return

        try:
            tmdb_series_details = self.tmdb_logic._tmdb_request(f"tv/{tmdb_id}")
            
            episodes_url = f"{self.config.server_config.server}/Items"
            episodes_params = {
                "api_key": self.config.server_config.api_key,
                "ParentId": series_id, "IncludeItemTypes": "Episode", "Recursive": "true",
                "Fields": "Name,Overview,ImageTags,ProviderIds"
            }
            emby_episodes = self.episode_refresher.session.get(episodes_url, params=episodes_params, timeout=30).json().get("Items", [])
            
            # 维度一：数量完整性
            total_episodes_on_tmdb = tmdb_series_details.get("number_of_episodes")
            if not total_episodes_on_tmdb:
                ui_logger.info(f"剧集《{series_name}》在 TMDB 上的总集数未知，跳过数量完整性检查。", task_category=task_cat)
                return

            if len(emby_episodes) < total_episodes_on_tmdb:
                ui_logger.info(f"剧集《{series_name}》尚未完结：Emby 中有 {len(emby_episodes)} 集，TMDB 显示总共 {total_episodes_on_tmdb} 集。", task_category=task_cat)
                return

            # 维度二：质量完整性
            all_metadata_complete = True
            for ep in emby_episodes:
                is_title_ok = bool(ep.get("Name")) and not self.episode_refresher._is_generic_episode_title(ep.get("Name"))
                is_overview_ok = bool(ep.get("Overview"))
                
                ep_provider_ids_lower = {k.lower(): v for k, v in ep.get("ProviderIds", {}).items()}
                image_source = ep_provider_ids_lower.get("toolboximagesource")
                has_official_image = bool(ep.get("ImageTags", {}).get("Primary")) and image_source != "screenshot"

                if not (is_title_ok and is_overview_ok and has_official_image):
                    all_metadata_complete = False
                    break
            
            # 最终决策
            if all_metadata_complete:
                self.remove_from_chasing_list(series_id, series_name, "数量与元数据质量均完整")
                return
            else:
                # 维度三：超时容错
                last_air_date_str = tmdb_series_details.get("last_episode_to_air", {}).get("air_date")
                if not last_air_date_str:
                    ui_logger.warning(f"剧集《{series_name}》元数据不完整，且无法获取 TMDB 最后一集播出日期，暂时不移除。", task_category=task_cat)
                    return

                last_air_date = datetime.strptime(last_air_date_str, "%Y-%m-%d")
                deadline = last_air_date + timedelta(days=self.chasing_config.completion_deadline_days)
                
                if datetime.now() > deadline:
                    self.remove_from_chasing_list(series_id, series_name, f"超出最终播出日期 {self.chasing_config.completion_deadline_days} 天，强制完结")
                else:
                    days_left = (deadline - datetime.now()).days
                    ui_logger.info(f"剧集《{series_name}》元数据不完整，仍在 {days_left} 天的等待期内，本次不移除。", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 在为《{series_name}》执行完结检测时发生错误: {e}", task_category=task_cat, exc_info=True)

    def run_chasing_workflow_task(self, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """
        内置的每日追更工作流。
        """
        task_cat = "追更-每日维护"
        ui_logger.info(f"🎉 开始执行每日追更维护任务...", task_category=task_cat)
        
        chasing_list = self._get_chasing_list()
        if not chasing_list:
            ui_logger.info("✅ 追更列表为空，无需执行。", task_category=task_cat)
            return

        ui_logger.info(f"🔍 发现 {len(chasing_list)} 个追更剧集，开始逐一处理...", task_category=task_cat)
        task_manager.update_task_progress(task_id, 0, len(chasing_list))

        for i, series_id in enumerate(chasing_list):
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务被取消。", task_category=task_cat)
                return
            
            series_details = self.episode_refresher._get_emby_item_details(series_id, fields="Name")
            series_name = series_details.get("Name", f"ID {series_id}") if series_details else f"ID {series_id}"
            ui_logger.info(f"➡️ 正在处理第 {i+1}/{len(chasing_list)} 个剧集: 《{series_name}》", task_category=task_cat)

            # 1. 刷新元数据
            ui_logger.info(f"   - [步骤1/2] 正在刷新元数据...", task_category=task_cat)
            try:
                episodes_url = f"{self.config.server_config.server}/Items"
                episodes_params = {
                    "api_key": self.config.server_config.api_key,
                    "ParentId": series_id, "IncludeItemTypes": "Episode", "Recursive": "true", "Fields": "Id"
                }
                episodes = self.episode_refresher.session.get(episodes_url, params=episodes_params, timeout=30).json().get("Items", [])
                episode_ids = [ep['Id'] for ep in episodes]
                
                if episode_ids:
                    self.episode_refresher.run_refresh_for_episodes(
                        episode_ids, self.config.episode_refresher_config, cancellation_event, 
                        task_id=None, task_manager=None, task_category=f"追更-刷新({series_name})"
                    )
                else:
                    ui_logger.info(f"   - 《{series_name}》下暂无分集，跳过刷新。", task_category=task_cat)
            except Exception as e:
                ui_logger.error(f"   - ❌ 刷新《{series_name}》时发生错误: {e}", task_category=task_cat)

            # 2. 完结检测
            ui_logger.info(f"   - [步骤2/2] 正在进行完结状态检测...", task_category=task_cat)
            self._check_and_remove_if_series_complete(series_id, cancellation_event)
            
            task_manager.update_task_progress(task_id, i + 1, len(chasing_list))
            time.sleep(1) # 短暂间隔

        ui_logger.info("🎉 每日追更维护任务执行完毕。", task_category=task_cat)

    def send_calendar_notification_task(self, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """
        生成并发送追剧日历通知。
        """
        task_cat = "追更-日历通知"
        ui_logger.info(f"📅 开始生成追剧日历...", task_category=task_cat)

        chasing_list = self._get_chasing_list()
        if not chasing_list:
            ui_logger.info("追更列表为空，无需发送通知。", task_category=task_cat)
            return

        calendar_days = self.chasing_config.calendar_days
        today = datetime.now().date()
        end_date = today + timedelta(days=calendar_days)
        
        upcoming_episodes = []
        
        for series_id in chasing_list:
            if cancellation_event.is_set(): return
            try:
                details = self.episode_refresher._get_emby_item_details(series_id, fields="ProviderIds,Name")
                if not details: continue
                
                provider_ids_lower = {k.lower(): v for k, v in details.get("ProviderIds", {}).items()}
                tmdb_id = provider_ids_lower.get("tmdb")
                if not tmdb_id: continue

                tmdb_details = self.tmdb_logic._tmdb_request(f"tv/{tmdb_id}")
                
                # 使用季详情获取更完整的未来播出计划
                for season in tmdb_details.get("seasons", []):
                    season_number = season.get("season_number")
                    if season_number is None: continue
                    
                    season_details = self.tmdb_logic.get_season_details(int(tmdb_id), season_number)
                    if not season_details or not season_details.get("episodes"): continue
                    
                    for episode in season_details["episodes"]:
                        air_date_str = episode.get("air_date")
                        if not air_date_str: continue
                        
                        air_date = datetime.strptime(air_date_str, "%Y-%m-%d").date()
                        if today <= air_date < end_date:
                            upcoming_episodes.append({
                                "series_name": tmdb_details.get("name"),
                                "air_date": air_date,
                                "season_number": episode.get("season_number"),
                                "episode_number": episode.get("episode_number"),
                                "episode_name": episode.get("name")
                            })
            except Exception as e:
                logging.error(f"获取剧集 {series_id} 的播出信息时出错: {e}")

        if not upcoming_episodes:
            ui_logger.info(f"检测到未来 {calendar_days} 天内无更新，跳过本次通知。", task_category=task_cat)
            return

        # 按日期和剧集名排序
        upcoming_episodes.sort(key=lambda x: (x["air_date"], x["series_name"]))
        
        # 构建消息
        message_parts = [f"📅 *Emby 追剧日历 (未来 {calendar_days} 天)*\n"]
        
        from collections import defaultdict
        grouped_by_date = defaultdict(list)
        for ep in upcoming_episodes:
            grouped_by_date[ep["air_date"]].append(ep)
            
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        
        for air_date in sorted(grouped_by_date.keys()):
            date_str = air_date.strftime("%Y-%m-%d")
            weekday_str = weekdays[air_date.weekday()]
            
            relative_day = ""
            if air_date == today:
                relative_day = " (今天)"
            elif air_date == today + timedelta(days=1):
                relative_day = " (明天)"
            
            message_parts.append(f"\n*{date_str} {weekday_str}{relative_day}*")
            
            for ep in grouped_by_date[air_date]:
                ep_name = ep.get('episode_name') or f"第 {ep.get('episode_number')} 集"
                message_parts.append(f"- *[{escape_markdown(ep['series_name'])}]* S{ep['season_number']:02d}E{ep['episode_number']:02d} - {escape_markdown(ep_name)}")

        final_message = "\n".join(message_parts)
        
        ui_logger.info("正在发送 Telegram 通知...", task_category=task_cat)
        notification_manager.send_telegram_message(final_message, self.config)