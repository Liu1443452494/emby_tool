# backend/episode_role_sync_logic.py (新文件)

import logging
import threading
import time
import requests
import json
import re
import os
from typing import List, Dict, Any

from models import AppConfig, EpisodeRoleSyncConfig
from task_manager import TaskManager
from douban_manager import DOUBAN_CACHE_FILE
from log_manager import ui_logger
from actor_role_mapper_logic import ACTOR_ROLE_MAP_FILE

class EpisodeRoleSyncLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.server_config = app_config.server_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.session = requests.Session()

    def _load_data_sources(self, task_category: str) -> tuple[Dict, Dict, bool]:
        """一次性加载所有需要的数据源"""
        ui_logger.info("➡️ [数据源] 正在加载角色映射表和豆瓣缓存...", task_category=task_category)
        
        role_map_data = {}
        if not os.path.exists(ACTOR_ROLE_MAP_FILE):
            ui_logger.error(f"❌ [数据源] 角色映射表文件 ({ACTOR_ROLE_MAP_FILE}) 不存在，任务无法继续。", task_category=task_category)
            return None, None, False
        try:
            with open(ACTOR_ROLE_MAP_FILE, 'r', encoding='utf-8') as f:
                role_map_data = json.load(f)
            ui_logger.info(f"✅ [数据源] 成功加载 {len(role_map_data)} 条媒体的角色映射数据。", task_category=task_category)
        except (IOError, json.JSONDecodeError) as e:
            ui_logger.error(f"❌ [数据源] 加载角色映射表失败: {e}", task_category=task_category)
            return None, None, False

        douban_map = {}
        if not os.path.exists(DOUBAN_CACHE_FILE):
            ui_logger.warning("⚠️ [数据源] 未找到豆瓣缓存文件，豆瓣匹配降级功能将不可用。", task_category=task_category)
        else:
            try:
                with open(DOUBAN_CACHE_FILE, 'r', encoding='utf-8') as f:
                    douban_map = json.load(f)
                ui_logger.info(f"✅ [数据源] 成功加载 {len(douban_map)} 条豆瓣缓存数据。", task_category=task_category)
            except (IOError, json.JSONDecodeError) as e:
                ui_logger.error(f"❌ [数据源] 加载豆瓣缓存文件失败: {e}", task_category=task_category)
        
        return role_map_data, douban_map, True

    def _get_item_details(self, item_id: str, fields: str = "ProviderIds,Type"):
        try:
            url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
            params = {**self.params, "Fields": fields}
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logging.error(f"【分集角色同步】获取媒体详情 (ID: {item_id}) 失败: {e}")
            return None

    def _get_all_episodes(self, series_id: str, task_category: str) -> List[Dict]:
        """获取一个剧集下的所有分集，包含People字段"""
        ui_logger.info(f"   - 正在获取剧集 (ID: {series_id}) 的所有分集信息...", task_category=task_category)
        all_episodes = []
        start_index = 0
        limit = 500 
        while True:
            try:
                url = f"{self.base_url}/Items"
                params = {
                    **self.params,
                    "ParentId": series_id,
                    "IncludeItemTypes": "Episode",
                    "Recursive": "true",
                    "Fields": "People,ProviderIds,Name",
                    "StartIndex": start_index,
                    "Limit": limit
                }
                resp = self.session.get(url, params=params, timeout=60)
                resp.raise_for_status()
                page_items = resp.json().get("Items", [])
                if not page_items:
                    break
                all_episodes.extend(page_items)
                start_index += len(page_items)
            except requests.RequestException as e:
                ui_logger.error(f"   - ❌ 获取分集列表时发生网络错误: {e}", task_category=task_category)
                break
        ui_logger.info(f"   - ✅ 成功获取到 {len(all_episodes)} 个分集。", task_category=task_category)
        return all_episodes

    def _update_item_people(self, item_id: str, item_name: str, people_list: List[Dict], task_category: str) -> bool:
        try:
            # 获取完整对象以避免覆盖其他字段
            full_item_json = self._get_item_details(item_id, fields="")
            if not full_item_json:
                ui_logger.error(f"   - ❌ 更新分集《{item_name}》前获取完整信息失败。", task_category=task_category)
                return False

            full_item_json['People'] = people_list
            
            url = f"{self.base_url}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            resp = self.session.post(url, params=self.params, json=full_item_json, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.status_code == 204
        except requests.RequestException as e:
            ui_logger.error(f"   - ❌ 更新分集《{item_name}》(ID: {item_id}) 失败: {e}", task_category=task_category)
            return False

    def _contains_chinese(self, text: str) -> bool:
        if not text: return False
        return bool(re.search(r'[\u4e00-\u9fa5]', text))

    def _clean_douban_character(self, character: str) -> str:
        if not character: return ""
        return re.sub(r'^(饰|饰演)\s*', '', character).strip()

    def run_sync_for_items(
        self, 
        item_ids: List[str], 
        config: EpisodeRoleSyncConfig, 
        cancellation_event: threading.Event, 
        task_id: str, 
        task_manager: TaskManager,
        task_category: str
    ):
        ui_logger.info("➡️ 任务启动：开始同步剧集角色到分集...", task_category=task_category)
        
        role_map_data, douban_map, sources_ok = self._load_data_sources(task_category)
        if not sources_ok:
            ui_logger.error("❌ 关键数据源加载失败，任务中止。", task_category=task_category)
            return

        total_items = len(item_ids)
        task_manager.update_task_progress(task_id, 0, total_items)
        ui_logger.info(f"🔍 [范围分析] 共收到 {total_items} 个待处理媒体项，将开始筛选其中的电视剧...", task_category=task_category)

        processed_series_count = 0
        updated_episode_count = 0

        for index, item_id in enumerate(item_ids):
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务被用户取消。", task_category=task_category)
                break
            
            task_manager.update_task_progress(task_id, index + 1, total_items)
            
            details = self._get_item_details(item_id)
            if not details:
                ui_logger.warning(f"   - [跳过] 无法获取媒体项 (ID: {item_id}) 的详情。", task_category=task_category)
                continue

            item_name = details.get("Name", f"ID {item_id}")
            if details.get("Type") != "Series":
                ui_logger.info(f"   - [跳过] 媒体《{item_name}》是电影，非电视剧。", task_category=task_category)
                continue

            ui_logger.info(f"➡️ [处理剧集] 开始处理《{item_name}》...", task_category=task_category)
            processed_series_count += 1

            provider_ids = details.get("ProviderIds", {})
            provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
            tmdb_id = provider_ids_lower.get("tmdb")
            douban_id = provider_ids_lower.get("douban")

            if not tmdb_id:
                ui_logger.warning(f"   - [跳过] 剧集《{item_name}》缺少 TMDB ID，无法在角色映射表中查找。", task_category=task_category)
                continue
            
            map_key = f"tv-{tmdb_id}"
            series_role_map_data = role_map_data.get(map_key)

            if not series_role_map_data:
                ui_logger.warning(f"   - [跳过] 在角色映射表中未找到《{item_name}》(Key: {map_key}) 的记录。", task_category=task_category)
                continue
            
            series_role_map = series_role_map_data.get("map", {})
            ui_logger.info(f"   - ✅ 在映射表中成功匹配到《{item_name}》，包含 {len(series_role_map)} 位演员的映射。", task_category=task_category)

            # 为豆瓣匹配准备数据
            douban_item_data = douban_map.get(douban_id) if douban_id else None
            douban_actor_map = {}
            if douban_item_data:
                for actor in douban_item_data.get('actors', []):
                    if actor.get('name'):
                        douban_actor_map[actor['name'].lower()] = self._clean_douban_character(actor.get('character', ''))
                    if actor.get('latin_name'):
                        douban_actor_map[actor['latin_name'].lower()] = self._clean_douban_character(actor.get('character', ''))

            all_episodes = self._get_all_episodes(item_id, task_category)
            if not all_episodes:
                ui_logger.info(f"   - 剧集《{item_name}》下没有找到任何分集，处理完毕。", task_category=task_category)
                continue

            for episode in all_episodes:
                if cancellation_event.is_set(): break
                
                episode_id = episode['Id']
                episode_name = episode.get('Name', f"Episode {episode_id}")
                people = episode.get('People', [])
                if not people: continue

                has_changes = False
                
                actors_to_process = people[:config.actor_limit]
                if len(people) > config.actor_limit:
                    ui_logger.info(f"     - [演员裁切] 分集《{episode_name}》演员总数: {len(people)}，根据设置将处理前 {config.actor_limit} 位。", task_category=task_category)

                for person in actors_to_process:
                    if self._contains_chinese(person.get('Role', '')):
                        continue

                    original_role = person.get('Role', '')
                    new_role = None
                    source = ""

                    # 阶段1: 角色映射表匹配
                    person_name = person.get('Name', '')
                    person_tmdb_id = person.get('ProviderIds', {}).get('Tmdb')
                    
                    # 优先用 TMDB ID 匹配
                    if person_tmdb_id:
                        for actor_name_in_map, map_info in series_role_map.items():
                            if str(map_info.get('tmdb_id')) == str(person_tmdb_id):
                                new_role = map_info.get('role')
                                source = "角色映射表(TMDB ID)"
                                break
                    
                    # 其次用演员名匹配
                    if not new_role and person_name in series_role_map:
                        new_role = series_role_map[person_name].get('role')
                        source = "角色映射表(演员名)"

                    # 阶段2: 豆瓣数据匹配
                    if not new_role and douban_actor_map:
                        matched_douban_role = douban_actor_map.get(person_name.lower())
                        if matched_douban_role and self._contains_chinese(matched_douban_role):
                            new_role = matched_douban_role
                            source = "豆瓣数据"
                    
                    # 阶段3: 降级策略
                    if not new_role and config.fallback_to_actor_string:
                        new_role = "演员"
                        source = "降级策略"

                    if new_role and new_role != original_role:
                        ui_logger.info(f"     - [更新] 分集《{episode_name}》: {person_name}: '{original_role}' -> '{new_role}' (来自: {source})", task_category=task_category)
                        person['Role'] = new_role
                        has_changes = True

                if has_changes:
                    if self._update_item_people(episode_id, episode_name, people, task_category):
                        updated_episode_count += 1
                    time.sleep(0.1) # 短暂休眠，防止请求过快

            if cancellation_event.is_set(): break

        ui_logger.info(f"🎉 任务执行完毕！共扫描 {processed_series_count} 部电视剧，成功更新了 {updated_episode_count} 个分集的角色信息。", task_category=task_category)
        return {"updated_count": updated_episode_count}