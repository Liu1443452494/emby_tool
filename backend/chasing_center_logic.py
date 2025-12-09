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
        self.memory_cache: Dict[str, Any] = {}

    def _get_chasing_list(self) -> List[Dict[str, Any]]:
        """安全地读取追更列表文件，并兼容新旧格式"""
        if not os.path.exists(CHASING_LIST_FILE):
            return []
        try:
            with open(CHASING_LIST_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not data:
                return []
            
            # 兼容性处理：如果文件内容是旧的字符串列表格式，则转换为新的对象列表格式
            if isinstance(data[0], str):
                ui_logger.info("➡️ [追更列表] 检测到旧版追更列表格式，将自动在后台进行转换...", task_category="追更中心")
                return [{"emby_id": item, "tmdb_id": None, "cache": None} for item in data]

            return data

        except (IOError, json.JSONDecodeError) as e:
            ui_logger.error(f"❌ [追更列表] 读取追更列表文件失败: {e}", task_category="追更中心")
            return []

    def _save_chasing_list(self, series_list: List[Dict[str, Any]]):
        """安全地写入追更列表文件"""
        lock_path = CHASING_LIST_FILE + ".lock"
        try:
            with FileLock(lock_path, timeout=10):
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



    # backend/chasing_center_logic.py (函数替换)

    def get_detailed_chasing_list(self) -> List[Dict]:
        """获取聚合了 Emby 和 TMDB 信息的详细追更列表，并实现两级缓存和动态分界线逻辑"""
        from trakt_manager import TraktManager
        from collections import Counter
        import pytz
        import os

        task_cat = "追更中心"
        chasing_items_in_memory = self._get_chasing_list()
        if not chasing_items_in_memory:
            return []

        cache_duration_memory = 3600
        cache_duration_file = 86400

        items_to_resave = False
        detailed_list = []
        updates_to_apply = {}
        
        # --- 新增 ---
        ids_to_remove = []
        # --- 新增结束 ---

        trakt_manager = TraktManager(self.config)

        for item_data in chasing_items_in_memory:
            emby_id = item_data.get("emby_id")
            tmdb_id = item_data.get("tmdb_id")
            
            try:
                emby_details = self.episode_refresher._get_emby_item_details(emby_id, fields="Name,ProductionYear,ProviderIds,ImageTags,BackdropImageTags")
                
                # --- 新增：健康检查与自动清理逻辑 ---
                if not emby_details:
                    ui_logger.warning(f"⚠️ [追更维护] 检测到剧集 (Emby ID: {emby_id}) 已在 Emby 中被删除或无法访问，将自动从追更列表中移除。", task_category=task_cat)
                    ids_to_remove.append(emby_id)
                    items_to_resave = True
                    continue
                # --- 新增结束 ---

                if not tmdb_id:
                    provider_ids_lower = {k.lower(): v for k, v in emby_details.get("ProviderIds", {}).items()}
                    tmdb_id = provider_ids_lower.get("tmdb")
                    if tmdb_id:
                        item_data["tmdb_id"] = tmdb_id
                        items_to_resave = True
                    else:
                        ui_logger.warning(f"⚠️ [追更] 剧集《{emby_details.get('Name')}》缺少 TMDB ID，无法处理。", task_category=task_cat)
                        continue
                
                episodes_url = f"{self.config.server_config.server}/Items"
                episodes_params = {
                    "api_key": self.config.server_config.api_key, 
                    "ParentId": emby_id, 
                    "IncludeItemTypes": "Episode", 
                    "Recursive": "true", 
                    "Fields": "ParentIndexNumber"
                }
                emby_episodes_full_list = self.episode_refresher.session.get(episodes_url, params=episodes_params, timeout=30).json().get("Items", [])
                emby_total_episodes_count = len(emby_episodes_full_list)

                tmdb_cache_data = None
                
                if tmdb_id in self.memory_cache:
                    cached_item = self.memory_cache[tmdb_id]
                    if time.time() - cached_item.get("timestamp", 0) < cache_duration_memory:
                        # --- 修改：优化日志输出 ---
                        remaining_seconds = cache_duration_memory - (time.time() - cached_item.get("timestamp", 0))
                        remaining_time_str = f"{remaining_seconds / 60:.0f}分钟"
                        
                        cached_status_text = cached_item.get("data", {}).get("details", {}).get("status", "未知")
                        status_map = {"Returning Series": "更新中", "Ended": "已完结", "Canceled": "已砍", "In Production": "制作中"}
                        display_status = status_map.get(cached_status_text, cached_status_text)

                        ui_logger.debug(f"🔍 [追更-缓存] 命中内存缓存: {emby_details.get('Name')} (剧集状态: {display_status}, 剩余: {remaining_time_str})", task_category=task_cat)
                        # --- 修改结束 ---
                        tmdb_cache_data = cached_item["data"]

                if not tmdb_cache_data and item_data.get("cache"):
                    cached_item = item_data["cache"]
                    cached_status = cached_item.get("data", {}).get("details", {}).get("status")
                    
                    if cached_status in ["Ended", "Canceled"]:
                        cache_duration_file = 14 * 86400 # 14天
                    else:
                        cache_duration_file = 1 * 86400 # 24小时

                    if time.time() - datetime.fromisoformat(cached_item.get("timestamp", "1970-01-01T00:00:00Z")).timestamp() < cache_duration_file:
                        # --- 修改：优化日志输出 ---
                        remaining_seconds = cache_duration_file - (time.time() - datetime.fromisoformat(cached_item.get("timestamp", "1970-01-01T00:00:00Z")).timestamp())
                        if remaining_seconds > 86400:
                            remaining_time_str = f"{remaining_seconds / 86400:.1f}天"
                        else:
                            remaining_time_str = f"{remaining_seconds / 3600:.1f}小时"
                        
                        cached_status_text = cached_item.get("data", {}).get("details", {}).get("status", "未知")
                        status_map = {"Returning Series": "更新中", "Ended": "已完结", "Canceled": "已砍", "In Production": "制作中"}
                        display_status = status_map.get(cached_status_text, cached_status_text)
                        
                        ui_logger.debug(f"🔍 [追更-缓存] 命中文件缓存: {emby_details.get('Name')} (剧集状态: {display_status}, 有效期: {cache_duration_file // 86400}天, 剩余: {remaining_time_str})", task_category=task_cat)
                        # --- 修改结束 ---
                        tmdb_cache_data = cached_item["data"]
                        self.memory_cache[tmdb_id] = {"timestamp": time.time(), "data": tmdb_cache_data}

                if not tmdb_cache_data:
                    ui_logger.info(f"➡️ [追更-API] 缓存未命中或已过期，正在为《{emby_details.get('Name')}》请求 TMDB API...", task_category=task_cat)
                    
                    ui_logger.debug(f"   - [追更-API] 执行轻量级巡检...", task_category=task_cat)
                    tmdb_details_full = self.tmdb_logic._tmdb_request(f"tv/{tmdb_id}")
                    new_status = tmdb_details_full.get("status")
                    
                    tmdb_cache_data = {
                        "details": {
                            "status": new_status,
                            "number_of_episodes": tmdb_details_full.get("number_of_episodes"),
                            "first_air_date": tmdb_details_full.get("first_air_date"),
                        }
                    }

                    is_chasing = new_status in ["Returning Series", "In Production"]

                    if is_chasing:
                        ui_logger.debug(f"   - [追更-API] 剧集播出中，请求并缓存详细分集列表。")
                        latest_season_summary = max(
                            (s for s in tmdb_details_full.get("seasons", []) if s.get("season_number", 0) > 0 and s.get("episode_count", 0) > 0),
                            key=lambda x: x.get("season_number", 0),
                            default=None
                        )
                        chasing_season_details = {}
                        if latest_season_summary:
                            season_number = latest_season_summary.get("season_number")
                            season_data = self.tmdb_logic.get_season_details(int(tmdb_id), season_number)

                            
                            if season_data and season_data.get("episodes"):
                                chasing_season_details[str(season_number)] = season_data["episodes"]
                        
                        
                        trakt_result = trakt_manager.get_show_seasons_with_episodes(tmdb_id)
                        trakt_episodes_map = None
                        trakt_episode_count = 0
                        if trakt_result:
                            trakt_episodes_map, trakt_episode_count = trakt_result
                        

                        
                        if trakt_episodes_map and latest_season_summary:
                            tmdb_latest_season_num = latest_season_summary.get("season_number")
                            
                            trakt_season_num = None
                            if trakt_episodes_map:
                                first_key = next(iter(trakt_episodes_map))
                                trakt_season_num = int(first_key.split('E')[0][1:])

                            ui_logger.info(f"   - [追更-Trakt] 开始数据一致性校验...", task_category=task_cat)
                            if tmdb_latest_season_num == trakt_season_num:
                                ui_logger.info(f"     - ✅ 季号一致 (均为 S{tmdb_latest_season_num})，校验通过。", task_category=task_cat)
                                
                                tmdb_episode_count = latest_season_summary.get("episode_count", 0)
                                # --- 核心修改：使用从 Trakt 获取的声明值进行比较 ---
                                if tmdb_episode_count == trakt_episode_count:
                                    ui_logger.info(f"     - ✅ 总集数一致 (均为 {tmdb_episode_count} 集)，数据完美匹配。", task_category=task_cat)
                                else:
                                    ui_logger.warning(f"     - ⚠️ 总集数不一致 (TMDB: {tmdb_episode_count} 集, Trakt: {trakt_episode_count} 集)。将继续合并可用数据。", task_category=task_cat)
                                # --- 修改结束 ---

                                ui_logger.info(f"   - [追更-Trakt] 开始合并精确播出时间...", task_category=task_cat)
                                for s_num, eps in chasing_season_details.items():
                                    for ep in eps:
                                        trakt_key = f"S{ep.get('season_number')}E{ep.get('episode_number')}"
                                        if trakt_key in trakt_episodes_map and trakt_episodes_map[trakt_key]:
                                            try:
                                                utc_time = datetime.fromisoformat(trakt_episodes_map[trakt_key].replace('Z', '+00:00'))
                                                local_tz = pytz.timezone(os.environ.get('TZ', 'Asia/Shanghai'))
                                                local_time = utc_time.astimezone(local_tz)
                                                ep['air_date'] = local_time.strftime('%Y-%m-%d %H:%M')
                                            except Exception as e:
                                                logging.warning(f"   - [追更-Trakt] 解析时间戳失败: {trakt_episodes_map[trakt_key]}, 错误: {e}")
                            else:
                                ui_logger.warning(f"   - [追更-Trakt] ❌ 季号不匹配 (TMDB 最新为 S{tmdb_latest_season_num}, Trakt 最新为 S{trakt_season_num})。将跳过 Trakt 数据合并。", task_category=task_cat)
                        
                        tmdb_cache_data["chasing_season_details"] = {
                            s_num: [{"season_number": ep.get("season_number"), "episode_number": ep.get("episode_number"), "air_date": ep.get("air_date")} for ep in eps]
                            for s_num, eps in chasing_season_details.items()
                        }
                    else:
                        ui_logger.debug(f"   - [追更-API] 剧集已完结，采用轻量级摘要缓存策略。")
                        last_ep = tmdb_details_full.get("last_episode_to_air")
                        latest_season_summary = max(
                            (s for s in tmdb_details_full.get("seasons", []) if s.get("season_number", 0) > 0 and s.get("episode_count", 0) > 0),
                            key=lambda x: x.get("season_number", 0),
                            default=None
                        )
                        tmdb_cache_data["chasing_season_summary"] = {
                            "status": new_status,
                            "total_episodes": latest_season_summary.get("episode_count", 0) if latest_season_summary else 0,
                            "last_episode": {
                                "season_number": last_ep.get("season_number"),
                                "episode_number": last_ep.get("episode_number"),
                                "air_date": last_ep.get("air_date")
                            } if last_ep else None
                        }

                    updates_to_apply[tmdb_id] = {"timestamp": datetime.utcnow().isoformat() + "Z", "data": tmdb_cache_data}
                    self.memory_cache[tmdb_id] = {"timestamp": time.time(), "data": tmdb_cache_data}
                    items_to_resave = True

                latest_episode_info = {}
                missing_info = {"count": 0, "status": "synced"}
                
                chasing_season_number = None
                tmdb_chasing_season_total_episodes = 0
                
                if tmdb_cache_data.get("chasing_season_summary"):
                    summary = tmdb_cache_data["chasing_season_summary"]
                    last_ep = summary.get("last_episode")
                    if last_ep:
                        chasing_season_number = last_ep.get("season_number")
                        tmdb_chasing_season_total_episodes = summary.get("total_episodes", 0)
                        latest_episode_info = {
                            "season_number": last_ep.get("season_number"),
                            "episode_number": last_ep.get("episode_number"),
                            "air_date": last_ep.get("air_date"),
                            "is_next": False
                        }
                
                elif tmdb_cache_data.get("chasing_season_details"):
                    chasing_season_details = tmdb_cache_data["chasing_season_details"]
                    if chasing_season_details:
                        chasing_season_number = int(list(chasing_season_details.keys())[0])
                        chasing_episodes = list(chasing_season_details.values())[0]
                        tmdb_chasing_season_total_episodes = len(chasing_episodes)
                        
                        chasing_episodes.sort(key=lambda x: x.get("episode_number", 0))
                        
                        emby_chasing_season_episode_count = sum(1 for ep in emby_episodes_full_list if ep.get("ParentIndexNumber") == chasing_season_number)
                        
                        has_precise_time = any(":" in (ep.get("air_date") or "") for ep in chasing_episodes)

                        if has_precise_time:
                            now = datetime.now(pytz.timezone(os.environ.get('TZ', 'Asia/Shanghai')))
                            
                            def parse_air_datetime(air_date_str, common_time_str=None):
                                try:
                                    return datetime.strptime(air_date_str, '%Y-%m-%d %H:%M').replace(tzinfo=now.tzinfo)
                                except ValueError:
                                    dt = datetime.strptime(air_date_str, '%Y-%m-%d')
                                    if common_time_str:
                                        h, m = map(int, common_time_str.split(':'))
                                        dt = dt.replace(hour=h, minute=m)
                                    return dt.replace(tzinfo=now.tzinfo)

                            time_parts = [ep.get("air_date").split(" ")[1] for ep in chasing_episodes if ep.get("air_date") and ":" in ep.get("air_date", "")]
                            common_time = Counter(time_parts).most_common(1)[0][0] if time_parts else None

                            aired_episodes = [ep for ep in chasing_episodes if ep.get("air_date") and parse_air_datetime(ep["air_date"], common_time) < now]
                            missing_count = len(aired_episodes) - emby_chasing_season_episode_count
                            missing_info = {"count": max(0, missing_count), "status": "missing" if missing_count > 0 else "synced"}

                            future_next_episode = next((ep for ep in chasing_episodes if ep.get("air_date") and parse_air_datetime(ep["air_date"], common_time) >= now), None)
                        
                        else:
                            today = datetime.now().date()
                            emby_latest_ep_in_tmdb = chasing_episodes[emby_chasing_season_episode_count - 1] if emby_chasing_season_episode_count > 0 and emby_chasing_season_episode_count <= len(chasing_episodes) else None
                            emby_latest_air_date_str = emby_latest_ep_in_tmdb.get("air_date") if emby_latest_ep_in_tmdb else None
                            
                            cutoff_date = today
                            if emby_latest_air_date_str:
                                try:
                                    if datetime.strptime(emby_latest_air_date_str, "%Y-%m-%d").date() == today:
                                        cutoff_date = today + timedelta(days=1)
                                except ValueError: pass
                            
                            aired_episodes = [ep for ep in chasing_episodes if ep.get("air_date") and datetime.strptime(ep["air_date"], "%Y-%m-%d").date() < cutoff_date]
                            missing_count = len(aired_episodes) - emby_chasing_season_episode_count
                            missing_info = {"count": max(0, missing_count), "status": "missing" if missing_count > 0 else "synced"}

                            future_next_episode = next((ep for ep in chasing_episodes if ep.get("air_date") and datetime.strptime(ep["air_date"], "%Y-%m-%d").date() >= cutoff_date), None)

                        if future_next_episode:
                            target_ep = future_next_episode
                        else:
                            # 查找最后一个有播出日期的分集
                            episodes_with_air_date = [ep for ep in chasing_episodes if ep.get("air_date")]
                            target_ep = episodes_with_air_date[-1] if episodes_with_air_date else None


                        is_next = bool(future_next_episode)

                        if target_ep:
                            latest_episode_info = {
                                "season_number": target_ep.get("season_number"),
                                "episode_number": target_ep.get("episode_number"),
                                "air_date": target_ep.get("air_date"),
                                "is_next": is_next
                            }

                if chasing_season_number is not None:
                    emby_chasing_season_episode_count = sum(1 for ep in emby_episodes_full_list if ep.get("ParentIndexNumber") == chasing_season_number)
                    
                    if tmdb_cache_data.get("chasing_season_summary"):
                        tmdb_chasing_season_total_episodes = tmdb_cache_data["chasing_season_summary"].get("total_episodes", 0)
                        missing_count = tmdb_chasing_season_total_episodes - emby_chasing_season_episode_count
                        missing_info = {"count": max(0, missing_count), "status": "complete" if missing_count <= 0 else "missing"}
                
                image_tags = emby_details.get("ImageTags", {})
                if backdrop_tag := emby_details.get("BackdropImageTags", []):
                    image_tags['Backdrop'] = backdrop_tag[0]

                emby_episode_count_display = sum(1 for ep in emby_episodes_full_list if ep.get("ParentIndexNumber") == chasing_season_number) if chasing_season_number is not None else emby_total_episodes_count

                detailed_list.append({
                    "emby_id": emby_id,
                    "tmdb_id": tmdb_id,
                    "name": emby_details.get("Name"),
                    "year": emby_details.get("ProductionYear"),
                    "image_tags": image_tags,
                    "tmdb_status": tmdb_cache_data.get("details", {}).get("status"),
                    "tmdb_total_episodes": tmdb_chasing_season_total_episodes,
                    "tmdb_first_air_date": tmdb_cache_data.get("details", {}).get("first_air_date"),
                    "emby_episode_count": emby_episode_count_display,
                    "latest_episode": latest_episode_info,
                    "missing_info": missing_info,
                    "chasing_season_number": chasing_season_number
                })

            except Exception as e:
                logging.error(f"❌ [追更] 获取剧集 {emby_id} 的详细信息时失败: {e}", exc_info=True)
                continue
        
        if items_to_resave:
            # --- 新增：在回写前，先执行清理操作 ---
            if ids_to_remove:
                ui_logger.info(f"✅ [追更] 正在从追更列表中移除 {len(ids_to_remove)} 个无效条目...", task_category=task_cat)
                chasing_items_in_memory = [item for item in chasing_items_in_memory if item.get("emby_id") not in ids_to_remove]
            # --- 新增结束 ---

            ui_logger.info("✅ [追更] 检测缓存有变更，正在回写到追更列表文件...", task_category=task_cat)
            for item in chasing_items_in_memory:
                if item.get("tmdb_id") in updates_to_apply:
                    item["cache"] = updates_to_apply[item["tmdb_id"]]
            self._save_chasing_list(chasing_items_in_memory)

        return detailed_list

    def add_to_chasing_list(self, series_id: str, series_name: str):
        """将一个剧集ID和TMDB ID添加到追更列表，并发送通知"""
        task_cat = "追更中心"
        chasing_list = self._get_chasing_list()
        
        if any(item.get("emby_id") == series_id for item in chasing_list):
            ui_logger.debug(f"剧集《{series_name}》已存在于追更列表中，无需重复添加。", task_category=task_cat)
            return

        emby_details = self.episode_refresher._get_emby_item_details(series_id, fields="ProviderIds")
        if not emby_details:
            ui_logger.error(f"❌ [追更] 添加《{series_name}》失败：无法获取其 Emby 详情。", task_category=task_cat)
            return
            
        provider_ids_lower = {k.lower(): v for k, v in emby_details.get("ProviderIds", {}).items()}
        tmdb_id = provider_ids_lower.get("tmdb")

        if not tmdb_id:
            ui_logger.warning(f"⚠️ [追更] 添加《{series_name}》失败：该剧集缺少 TMDB ID。", task_category=task_cat)
            return

        existing_item = next((item for item in chasing_list if item.get("tmdb_id") == tmdb_id), None)

        if existing_item:
            # 如果 TMDB ID 存在，仅更新 Emby ID
            old_emby_id = existing_item.get("emby_id")
            existing_item["emby_id"] = series_id
            ui_logger.info(f"🔄 [追更] 检测到剧集《{series_name}》(TMDB: {tmdb_id}) 已在列表中，更新 Emby ID: {old_emby_id} -> {series_id}", task_category=task_cat)
        else:
            # 如果 TMDB ID 不存在，则新增
            chasing_list.append({"emby_id": series_id, "tmdb_id": tmdb_id, "cache": None})
            ui_logger.info(f"➡️ [追更] 已将剧集《{series_name}》加入追更列表。", task_category=task_cat)

        self._save_chasing_list(chasing_list)
        

        # --- 核心修改：统一的、自给自足的通知逻辑 ---
        if self.config.telegram_config.enabled:
            ui_logger.info(f"🔔 准备为《{series_name}》发送追更添加通知...", task_category=task_cat)
            
            # 主动获取通知所需的全部信息
            details_for_noti = self.episode_refresher._get_emby_item_details(series_id, fields="ProductionYear,Overview,BackdropImageTags")
            if not details_for_noti:
                ui_logger.error(f"   - ❌ 无法获取《{series_name}》的详细信息以发送通知。", task_category=task_cat)
                return

            series_year = details_for_noti.get("ProductionYear")
            overview = details_for_noti.get("Overview")
            backdrop_tags = details_for_noti.get("BackdropImageTags")

            image_source = None
            if backdrop_tags and len(backdrop_tags) > 0:
                server = self.config.server_config.server.rstrip('/')
                api_key = self.config.server_config.api_key
                image_url = f"{server}/Items/{series_id}/Images/Backdrop/0?api_key={api_key}&tag={backdrop_tags[0]}&maxWidth=1280&quality=80"
                
                try:
                    ui_logger.debug(f"   - 正在从 Emby 下载背景图: {image_url}", task_category=task_cat)
                    proxies = self.episode_refresher.tmdb_logic.proxy_manager.get_proxies(image_url)
                    response = self.episode_refresher.session.get(image_url, timeout=20, proxies=proxies)
                    response.raise_for_status()
                    image_source = response.content
                    ui_logger.debug(f"   - 背景图下载成功，大小: {len(image_source) / 1024:.2f} KB", task_category=task_cat)
                except Exception as e:
                    ui_logger.error(f"   - ❌ 下载背景图失败: {e}", task_category=task_cat)

            if not image_source:
                ui_logger.warning("⚠️ 无法获取背景图，将不发送带图通知。", task_category=task_cat)
                return

            year_str = f"({series_year})" if series_year else ""
            title_line = escape_markdown(f"{series_name} {year_str} 添加追更剧集成功")
            
            time_line = escape_markdown(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            overview_line = ""
            if overview:
                max_len = 300
                truncated_overview = overview[:max_len] + '...' if len(overview) > max_len else overview
                overview_line = escape_markdown(f"剧情: {truncated_overview}")

            caption = f"*{title_line}*\n\n`{time_line}`\n\n{overview_line}"
            
            notification_manager.send_telegram_photo_notification(image_source, caption, self.config)
        

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
                    # --- 修改：优化日志输出 ---
                    time_left = deadline - datetime.now()
                    days_left = time_left.days
                    
                    remaining_str = ""
                    if days_left > 0:
                        remaining_str = f" (还剩 {days_left} 天)"
                    else:
                        hours_left = time_left.total_seconds() / 3600
                        if hours_left > 1:
                            remaining_str = f" (还剩 {hours_left:.0f} 小时)"
                        else:
                            minutes_left = time_left.total_seconds() / 60
                            remaining_str = f" (还剩 {minutes_left:.0f} 分钟)"

                    ui_logger.info(f"剧集《{series_name}》元数据不完整，仍在 {self.chasing_config.completion_deadline_days} 天的等待期内{remaining_str}，本次不移除。", task_category=task_cat)

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

        for i, series_item in enumerate(chasing_list):
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务被取消。", task_category=task_cat)
                return
            
            series_id = series_item.get("emby_id")
            if not series_id:
                ui_logger.warning(f"   - [跳过] 追更列表中的第 {i+1} 项缺少 'emby_id'，无法处理。", task_category=task_cat)
                task_manager.update_task_progress(task_id, i + 1, len(chasing_list))
                continue
            
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

        self.run_orphaned_cache_cleanup_task(cancellation_event, task_id, task_manager)

    def _scan_and_cleanup_orphaned_cache_for_series(self, series_id: str, task_category: str) -> int:
        """
        扫描指定剧集，清理那些 TMDB 已有图（Emby无标记）但本地仍残留的截图缓存。
        实现了远程索引的按需加载（Lazy Load）。
        """
        cleaned_count = 0
        try:
            # 1. 获取剧集详情与标签检查
            series_details = self.episode_refresher._get_emby_item_details(series_id, fields="ProviderIds,Name,Tags,TagItems")
            if not series_details:
                return 0
            
            series_name = series_details.get("Name", "未知剧集")
            
            # 检查强制刷新标签 (豁免权)
            tags = []
            if 'TagItems' in series_details and isinstance(series_details['TagItems'], list):
                tags = [t.get('Name') for t in series_details.get('TagItems', []) if isinstance(t, dict)]
            elif 'Tags' in series_details and isinstance(series_details['Tags'], list):
                tags = series_details.get("Tags", [])
            
            for t in tags:
                if str(t).lower() in ["forceimagerefresh", "forcelmagerefresh"]:
                    ui_logger.info(f"   - [跳过] 剧集《{series_name}》拥有强制刷新标签，跳过清理。", task_category=task_category)
                    return 0

            # 获取 TMDB ID
            provider_ids_lower = {k.lower(): v for k, v in series_details.get("ProviderIds", {}).items()}
            series_tmdb_id = provider_ids_lower.get("tmdb")
            if not series_tmdb_id:
                return 0

            # 2. 获取所有分集
            episodes_url = f"{self.config.server_config.server}/Items"
            episodes_params = {
                "api_key": self.config.server_config.api_key,
                "ParentId": series_id,
                "IncludeItemTypes": "Episode",
                "Recursive": "true",
                "Fields": "Id,Name,ParentIndexNumber,IndexNumber,ProviderIds"
            }
            episodes_resp = self.episode_refresher.session.get(episodes_url, params=episodes_params, timeout=30)
            episodes_resp.raise_for_status()
            all_episodes = episodes_resp.json().get("Items", [])

            remote_db = None
            remote_db_loaded = False # 标记是否尝试加载过

            # 3. 遍历检查
            for ep in all_episodes:
                # 检查 Emby 标记
                ep_provider_ids = {k.lower(): v for k, v in ep.get("ProviderIds", {}).items()}
                if ep_provider_ids.get("toolboximagesource"):
                    continue # 有标记，说明是有效截图，保留

                # 构建本地路径
                s_num = ep.get("ParentIndexNumber")
                e_num = ep.get("IndexNumber")
                if s_num is None or e_num is None: continue

                # 调用 Refresher 的辅助方法构建路径
                local_path = self.episode_refresher._get_local_screenshot_path(series_tmdb_id, s_num, e_num, series_name)
                if not local_path: continue

                # 检查本地文件是否存在
                # 注意：_get_local_screenshot_path 返回的是理论路径，我们需要检查实际文件
                # 这里为了保险，我们使用 _find_screenshot_cache_dir_by_tmdbid 来定位真实目录
                real_cache_dir = self.episode_refresher._find_screenshot_cache_dir_by_tmdbid(series_tmdb_id)
                if not real_cache_dir: continue
                
                real_file_path = os.path.join(real_cache_dir, os.path.basename(local_path))

                if os.path.exists(real_file_path):
                    # 命中！无标记 + 本地有文件 = 垃圾文件
                    ui_logger.info(f"   - 🗑️ [清理] 发现无效缓存: S{s_num:02d}E{e_num:02d} (Emby已用官方图)，正在删除...", task_category=task_category)
                    
                    try:
                        os.remove(real_file_path)
                        cleaned_count += 1
                        
                        # 尝试清理空目录
                        try:
                            if not os.listdir(real_cache_dir):
                                os.rmdir(real_cache_dir)
                        except: pass

                        # 4. 联动远程检查 (按需加载)
                        if not remote_db_loaded:
                            ui_logger.debug(f"   - [远程] 首次触发清理，正在加载远程索引以检查备份状态...", task_category=task_category)
                            remote_db, _ = self.episode_refresher._get_remote_db(self.config.episode_refresher_config)
                            remote_db_loaded = True
                        
                        if remote_db:
                            episode_key = f"{s_num}-{e_num}"
                            if remote_db.get("series", {}).get(str(series_tmdb_id), {}).get(episode_key):
                                ui_logger.info(f"   - 📝 [远程] 该截图存在于远程备份中，已加入待删除日志。", task_category=task_category)
                                self.episode_refresher._log_screenshot_for_deletion(
                                    series_tmdb_id=series_tmdb_id,
                                    series_name=series_name,
                                    emby_series_id=series_id,
                                    season_number=s_num,
                                    episode_number=e_num
                                )

                    except Exception as e:
                        ui_logger.error(f"   - ❌ 删除本地文件失败: {e}", task_category=task_category)

        except Exception as e:
            ui_logger.error(f"   - ❌ 清理剧集 {series_id} 缓存时出错: {e}", task_category=task_category)
        
        return cleaned_count

    def run_orphaned_cache_cleanup_task(self, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """
        扫描追更列表中的剧集，清理那些已被官方图替换的本地无效截图缓存。
        """
        task_cat = "追更-缓存清理"
        ui_logger.info(f"🧹 开始执行无效缓存清理任务...", task_category=task_cat)
        
        chasing_list = self._get_chasing_list()
        if not chasing_list:
            ui_logger.info("✅ 追更列表为空，无需清理。", task_category=task_cat)
            return

        total_cleaned = 0
        
        for i, series_item in enumerate(chasing_list):
            if cancellation_event.is_set(): return
            
            series_id = series_item.get("emby_id")
            if not series_id: continue
            
            cleaned = self._scan_and_cleanup_orphaned_cache_for_series(series_id, task_cat)
            total_cleaned += cleaned
            
            if task_manager:
                task_manager.update_task_progress(task_id, i + 1, len(chasing_list))

        if total_cleaned > 0:
            ui_logger.info(f"🎉 清理完成。共删除了 {total_cleaned} 个无效的本地截图缓存文件。", task_category=task_cat)
        else:
            ui_logger.info(f"✅ 清理完成。未发现无效的本地缓存。", task_category=task_cat)


    def send_calendar_notification_task(self, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """
        生成并发送追剧日历通知 (V2.5 - 修正 • 符号转义问题)。
        """
        task_cat = "追更-日历通知"
        ui_logger.info(f"📅 开始基于本地缓存生成追剧日历...", task_category=task_cat)

        ui_logger.info(f"   - [步骤1/2] 正在预热缓存，确保数据为最新...", task_category=task_cat)
        self.get_detailed_chasing_list()
        ui_logger.info(f"   - ✅ 缓存预热完成。", task_category=task_cat)
        
        ui_logger.info(f"   - [步骤2/2] 开始生成日历内容...", task_category=task_cat)

        chasing_list_data = self._get_chasing_list()
        if not chasing_list_data:
            ui_logger.info("✅ 追更列表为空，无需发送通知。", task_category=task_cat)
            return

        calendar_days = self.chasing_config.calendar_days
        today = datetime.now().date()
        end_date = today + timedelta(days=calendar_days)
        
        upcoming_episodes = []
        
        for series_data in chasing_list_data:
            if cancellation_event.is_set(): return
            
            series_name = "未知剧集"
            series_year = ""
            try:
                emby_details = self.episode_refresher._get_emby_item_details(series_data.get("emby_id"), fields="Name,ProductionYear")
                if emby_details:
                    series_name = emby_details.get("Name")
                    series_year = emby_details.get("ProductionYear")

                cache = series_data.get("cache", {})
                if not cache:
                    ui_logger.debug(f"   - [跳过] 剧集《{series_name}》缺少缓存数据。", task_category=task_cat)
                    continue

                tmdb_status = cache.get("data", {}).get("details", {}).get("status")
                if tmdb_status not in ["Returning Series", "In Production"]:
                    ui_logger.debug(f"   - [跳过] 剧集《{series_name}》状态为 '{tmdb_status}'，非播出中。", task_category=task_cat)
                    continue

                chasing_season_details = cache.get("data", {}).get("chasing_season_details", {})
                if not chasing_season_details:
                    continue

                for season_number_str, episodes in chasing_season_details.items():
                    for episode in episodes:
                        air_date_str = episode.get("air_date")
                        if not air_date_str or air_date_str == "null":
                            continue
                        
                        try:
                            # --- 核心修改：增强数据结构，同时保留日期对象和原始字符串 ---
                            air_date_part = air_date_str.split(' ')[0]
                            air_date = datetime.strptime(air_date_part, "%Y-%m-%d").date()
                            
                            if today <= air_date < end_date:
                                upcoming_episodes.append({
                                    "series_name": series_name,
                                    "series_year": series_year,
                                    "air_date": air_date, # 用于排序和分组
                                    "air_date_str": air_date_str, # 用于最终展示
                                    "season_number": episode.get("season_number"),
                                    "episode_number": episode.get("episode_number"),
                                })
                            # --- 修改结束 ---
                        except (ValueError, TypeError):
                            continue
            except Exception as e:
                logging.error(f"❌ 处理剧集 {series_data.get('emby_id')} 的日历数据时出错: {e}", exc_info=True)

        if not upcoming_episodes:
            ui_logger.info(f"✅ 检测到未来 {calendar_days} 天内无更新，跳过本次通知。", task_category=task_cat)
            return

        upcoming_episodes.sort(key=lambda x: (x["air_date"], x["series_name"], x["season_number"], x["episode_number"]))
        
        message_parts = [f"📅 *Emby 追剧日历 \\(未来 {escape_markdown(str(calendar_days))} 天\\)*\n"]
        
        from collections import defaultdict
        from itertools import groupby

        grouped_by_date = defaultdict(list)
        for ep in upcoming_episodes:
            grouped_by_date[ep["air_date"]].append(ep)
            
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        
        sorted_dates = sorted(grouped_by_date.keys())

        for i, air_date in enumerate(sorted_dates):
            date_str_escaped = escape_markdown(air_date.strftime("%Y-%m-%d"))
            weekday_str = weekdays[air_date.weekday()]
            
            relative_day_raw = ""
            if air_date == today:
                relative_day_raw = " (今天)"
            elif air_date == today + timedelta(days=1):
                relative_day_raw = " (明天)"
            elif air_date == today + timedelta(days=2):
                relative_day_raw = " (后天)"
            
            relative_day_escaped = escape_markdown(relative_day_raw)
            
            message_parts.append(f"\n*{date_str_escaped} {weekday_str}{relative_day_escaped}*")
            
            keyfunc = lambda x: (x['series_name'], x['series_year'], x['season_number'])
            
            for (series_name, series_year, season_number), group in groupby(grouped_by_date[air_date], key=keyfunc):
                year_str = f"\\({series_year}\\)" if series_year else ""
                
                message_parts.append(
                    f"● *[{escape_markdown(series_name)}{year_str}]* S{season_number:02d}"
                )
                
                # --- 核心修改：根据格式动态拼接分集信息 ---
                for ep in group:
                    time_str = ""
                    if ' ' in ep['air_date_str']:
                        time_part = ep['air_date_str'].split(' ')[1]
                        time_str = f" `{escape_markdown(time_part)}`" # 增加代码块样式以突出时间

                    message_parts.append(f"  \\ － 第{ep['episode_number']}集{time_str}")
                # --- 修改结束 ---
            
        final_message = "\n".join(message_parts)
        
        ui_logger.info("➡️ 正在发送 Telegram 通知...", task_category=task_cat)
        notification_manager.send_telegram_message(final_message, self.config)

    def get_calendar_data_for_series(self, series_id: str) -> Dict[str, Any]:
        """为单个剧集生成日历数据"""
        task_cat = "追更-日历"
        chasing_list = self._get_chasing_list()
        
        target_series = next((item for item in chasing_list if item.get("emby_id") == series_id), None)
        
        if not target_series:
            ui_logger.warning(f"⚠️ [日历] 在追更列表中未找到 Emby ID 为 {series_id} 的剧集。", task_category=task_cat)
            return {}

        cache = target_series.get("cache", {})
        if not cache:
            ui_logger.debug(f"   - [日历] 剧集 {series_id} 缺少缓存数据，无法生成日历。", task_category=task_cat)
            return {}

        chasing_season_details = cache.get("data", {}).get("chasing_season_details", {})
        if not chasing_season_details:
            ui_logger.debug(f"   - [日历] 剧集 {series_id} 的缓存中缺少 'chasing_season_details'，无法生成日历。", task_category=task_cat)
            return {}

        # 使用 defaultdict 简化分组逻辑
        from collections import defaultdict
        grouped_by_date = defaultdict(list)

        for season_number_str, episodes in chasing_season_details.items():
            for episode in episodes:
                air_date_str = episode.get("air_date")
                if air_date_str and air_date_str != "null":
                    date_key = air_date_str.split(' ')[0]
                    grouped_by_date[date_key].append(episode)
        
        return dict(grouped_by_date)
    
    