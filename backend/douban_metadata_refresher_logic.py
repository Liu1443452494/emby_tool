# backend/douban_metadata_refresher_logic.py (完整文件覆盖)

import logging
import threading
import time
import requests
import json
import os
import shutil
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from filelock import FileLock, Timeout

from log_manager import ui_logger
from models import AppConfig, DoubanMetadataRefresherConfig, ScheduledTasksTargetScope
from task_manager import TaskManager
from media_selector import MediaSelector
from douban_manager import DOUBAN_CACHE_FILE, _parse_folder_name
from actor_localizer_logic import ActorLocalizerLogic
from actor_role_mapper_logic import ActorRoleMapperLogic

class DoubanMetadataRefresherLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.server_config = app_config.server_config
        self.douban_config = app_config.douban_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.session = requests.Session()

    def _get_item_details(self, item_id: str, fields: str = "ProviderIds,Name,Type,Path,Locked") -> Optional[Dict]:
        try:
            url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
            params = {**self.params, "Fields": fields}
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"【豆瓣元数据刷新】获取 Emby 媒体详情 (ID: {item_id}) 失败: {e}")
            return None

    def _update_item_provider_ids(self, item_id: str, new_provider_ids: Dict) -> bool:
        try:
            # 获取完整项目信息用于更新
            item_details_full = self._get_item_details(item_id, fields="")
            if not item_details_full:
                raise Exception("获取项目完整详情失败")
            
            item_details_full["ProviderIds"] = new_provider_ids
            
            update_url = f"{self.base_url}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            response = self.session.post(update_url, params=self.params, json=item_details_full, headers=headers, timeout=20)
            response.raise_for_status()
            return True
        except Exception as e:
            logging.error(f"【豆瓣元数据刷新】更新媒体 (ID: {item_id}) 的 ProviderIds 时失败: {e}")
            return False
        
    def _unlock_item(self, item_id: str, task_cat: str) -> bool:
        """解锁媒体项，以便可以刷新元数据"""
        try:
            # 请求Locked字段即可，减少数据量
            item_details = self._get_item_details(item_id, fields="Locked")
            if not item_details:
                return False
            
            if not item_details.get("Locked", False):
                ui_logger.debug(f"     - [解锁] 媒体项 (ID: {item_id}) 未被锁定，无需操作。", task_category=task_cat)
                return True

            # 仅修改Locked字段，避免动到其他数据
            item_details["Locked"] = False
            
            update_url = f"{self.base_url}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            response = self.session.post(update_url, params=self.params, json=item_details, headers=headers, timeout=20)
            response.raise_for_status()
            ui_logger.info(f"     - [解锁] 成功发送解锁请求。", task_category=task_cat)
            return True
        except Exception as e:
            ui_logger.error(f"     - [解锁] ❌ 解锁媒体项 (ID: {item_id}) 时失败: {e}", task_category=task_cat)
            return False

    def _trigger_emby_refresh(self, item_id: str, task_cat: str) -> bool:
        try:
            if not self._unlock_item(item_id, task_cat):
                ui_logger.warning(f"     - ⚠️ 解锁媒体项 (ID: {item_id}) 失败，但仍将继续尝试刷新...", task_category=task_cat)

            url = f"{self.base_url}/Items/{item_id}/Refresh"
            params = {
                **self.params,
                "Recursive": "true",
                "MetadataRefreshMode": "FullRefresh",
                "ImageRefreshMode": "Default",
                "ReplaceAllMetadata": "true",
                "ReplaceAllImages": "false"
            }
            response = self.session.post(url, params=params, timeout=30)
            response.raise_for_status()
            
            if response.status_code == 204:
                ui_logger.info(f"       - ✅ 已成功向 Emby 发送元数据刷新指令 (不替换图片)。", task_category=task_cat)
                return True
            else:
                ui_logger.warning(f"       - ⚠️ Emby 服务器返回异常状态码 {response.status_code}，刷新可能未成功。", task_category=task_cat)
                return False
        except Exception as e:
            ui_logger.error(f"       - ❌ 向 Emby 发送元数据刷新指令时失败: {e}", task_category=task_cat)
            return False

    def _compare_actor_lists(self, old_actors: List[Dict], new_actors: List[Dict]) -> bool:
        """比较新旧演员列表是否有实质性变化，返回True表示有变化"""
        if len(old_actors) != len(new_actors):
            return True

        old_map = {actor.get('name'): actor.get('character', '') for actor in old_actors if actor.get('name')}
        new_map = {actor.get('name'): actor.get('character', '') for actor in new_actors if actor.get('name')}

        if old_map.keys() != new_map.keys():
            return True

        for name, old_char in old_map.items():
            if old_char != new_map.get(name, ''):
                return True
        
        return False

    def run_refresh_task(self, scope: ScheduledTasksTargetScope, config: DoubanMetadataRefresherConfig, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "豆瓣元数据刷新"
        ui_logger.info(f"🎉 任务启动，范围: {scope.mode}", task_category=task_cat)

        # 阶段一：准备与过滤
        ui_logger.info("➡️ [阶段 1/5] 正在获取并过滤媒体项...", task_category=task_cat)
        selector = MediaSelector(self.app_config)
        all_item_ids = selector.get_item_ids(scope)
        if not all_item_ids:
            ui_logger.info("✅ 在指定范围内未找到任何媒体项，任务完成。", task_category=task_cat)
            return

        items_to_process = []
        skipped_count = 0
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_id = {executor.submit(self._get_item_details, item_id): item_id for item_id in all_item_ids}
            for future in as_completed(future_to_id):
                if cancellation_event.is_set(): return
                try:
                    details = future.result()
                    if details:
                        provider_ids = details.get("ProviderIds", {})
                        # 兼容大小写
                        provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
                        if 'douban' in provider_ids_lower and provider_ids_lower['douban']:
                            items_to_process.append(details)
                        else:
                            skipped_count += 1
                            logging.info(f"【豆瓣元数据刷新-跳过】媒体《{details.get('Name')}》因缺少豆瓣ID而被跳过。")
                    else:
                        item_id = future_to_id[future]
                        ui_logger.warning(f"   - ⚠️ 获取媒体项 (ID: {item_id}) 详情失败，已跳过。")
                        skipped_count += 1
                except Exception as e:
                    item_id = future_to_id[future]
                    ui_logger.error(f"   - ❌ 处理媒体项 (ID: {item_id}) 时发生严重错误: {e}，已跳过。")
                    skipped_count += 1
        
        if not items_to_process:
            ui_logger.warning(f"⚠️ 在指定范围内的所有媒体项均缺少豆瓣ID或获取失败，任务中止。共跳过 {skipped_count} 项。", task_category=task_cat)
            return
        
        total_items = len(items_to_process)
        ui_logger.info(f"✅ 过滤完成，共 {total_items} 个项目包含豆瓣ID，将开始处理。(已跳过 {skipped_count} 个无ID或获取失败的项目)", task_category=task_cat)
        task_manager.update_task_progress(task_id, 0, total_items)

        # 阶段二：核心刷新循环
        ui_logger.info("➡️ [阶段 2/5] 开始逐一刷新豆瓣元数据...", task_category=task_cat)
        successful_items = []
        old_actor_data_map = {}
        douban_data_root = self.douban_config.directory

        for i, item in enumerate(items_to_process):
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务被用户取消。", task_category=task_cat)
                break
            
            item_id = item['Id']
            item_name = item['Name']
            item_type = item['Type']
            provider_ids = item.get("ProviderIds", {})
            douban_id = next((v for k, v in provider_ids.items() if k.lower() == 'douban'), None)
            
            ui_logger.info(f"  - ({i+1}/{total_items}) 正在处理《{item_name}》 (豆瓣ID: {douban_id})...", task_category=task_cat)
            task_manager.update_task_progress(task_id, i + 1, total_items)

            try:
                # 1. 找到并备份/删除本地数据
                sub_dir = 'douban-movies' if item_type == 'Movie' else 'douban-tv'
                target_dir = os.path.join(douban_data_root, sub_dir)
                found_folder = None
                if os.path.isdir(target_dir):
                    for folder_name in os.listdir(target_dir):
                        parsed_db_id, _ = _parse_folder_name(folder_name)
                        if parsed_db_id == douban_id:
                            found_folder = os.path.join(target_dir, folder_name)
                            break
                
                if not found_folder:
                    ui_logger.warning(f"     - [跳过] 未在本地找到与豆瓣ID {douban_id} 匹配的元数据文件夹。", task_category=task_cat)
                    continue

                if config.enable_post_refresh_actions:
                    json_filename = 'all.json' if item_type == 'Movie' else 'series.json'
                    json_path = os.path.join(found_folder, json_filename)
                    if os.path.exists(json_path):
                        with open(json_path, 'r', encoding='utf-8') as f:
                            old_data = json.load(f)
                        old_actor_data_map[douban_id] = old_data.get('actors', [])
                        ui_logger.info(f"     - [备份] 已为后续比对备份旧的演员数据。", task_category=task_cat)

                shutil.rmtree(found_folder)
                ui_logger.info(f"     - [清理] 已成功删除本地旧元数据文件夹: {os.path.basename(found_folder)}", task_category=task_cat)

                # 2. 触发Emby刷新
                provider_ids_copy = {k: v for k, v in provider_ids.items() if k.lower() != 'douban'}
                if not self._update_item_provider_ids(item_id, provider_ids_copy):
                    raise Exception("擦除豆瓣ID失败")
                
                ui_logger.info(f"     - ⏱️ [触发] 已擦除豆瓣ID，等待 {config.delete_id_wait_seconds} 秒...", task_category=task_cat)
                time.sleep(config.delete_id_wait_seconds)

                # 统一使用 'Douban' 作为键写回
                provider_ids_copy['Douban'] = douban_id
                if not self._update_item_provider_ids(item_id, provider_ids_copy):
                    raise Exception("写回豆瓣ID失败")
                
                ui_logger.info(f"     - ⏱️ [触发] 已写回豆瓣ID，等待 {config.readd_id_wait_seconds} 秒让插件下载新数据...", task_category=task_cat)
                time.sleep(config.readd_id_wait_seconds)

                # 3. 验证
                new_folder_found = False
                if os.path.isdir(target_dir):
                    for folder_name in os.listdir(target_dir):
                        parsed_db_id, _ = _parse_folder_name(folder_name)
                        if parsed_db_id == douban_id:
                            new_folder_found = True
                            break
                
                if new_folder_found:
                    ui_logger.info(f"     - ✅ [验证] 成功！本地已生成新的元数据文件夹。", task_category=task_cat)
                    successful_items.append(item)
                else:
                    raise Exception("验证失败，本地未重新生成元数据文件夹")

            except Exception as e:
                ui_logger.error(f"     - ❌ 处理《{item_name}》时发生错误: {e}", task_category=task_cat)
            
            if i < total_items - 1:
                ui_logger.info(f"     - ⏱️ [间隔] 等待 {config.item_interval_seconds} 秒...", task_category=task_cat)
                time.sleep(config.item_interval_seconds)

        # 阶段三：批量更新主缓存
        ui_logger.info(f"➡️ [阶段 3/5] 开始批量更新主缓存文件 `douban_data.json`...", task_category=task_cat)
        if successful_items:
            try:
                lock_path = DOUBAN_CACHE_FILE + ".lock"
                with FileLock(lock_path, timeout=10):
                    if os.path.exists(DOUBAN_CACHE_FILE):
                        with open(DOUBAN_CACHE_FILE, 'r', encoding='utf-8') as f:
                            douban_map = json.load(f)
                    else:
                        douban_map = {}
                    
                    updated_count = 0
                    for item in successful_items:
                        douban_id = next((v for k, v in item.get("ProviderIds", {}).items() if k.lower() == 'douban'), None)
                        if not douban_id: continue

                        sub_dir = 'douban-movies' if item['Type'] == 'Movie' else 'douban-tv'
                        target_dir = os.path.join(douban_data_root, sub_dir)
                        found_folder = None
                        if not os.path.isdir(target_dir): continue
                        for folder_name in os.listdir(target_dir):
                            parsed_db_id, _ = _parse_folder_name(folder_name)
                            if parsed_db_id == douban_id:
                                found_folder = os.path.join(target_dir, folder_name)
                                break
                        
                        if not found_folder: continue

                        json_filename = 'all.json' if item['Type'] == 'Movie' else 'series.json'
                        json_path = os.path.join(found_folder, json_filename)
                        if not os.path.isfile(json_path): continue

                        with open(json_path, 'r', encoding='utf-8') as f:
                            new_data = json.load(f)
                        
                        item_data = {
                            'type': item['Type'],
                            'title': new_data.get('title', 'N/A'),
                            'year': new_data.get('year', ''),
                            'genres': new_data.get('genres', []),
                            'intro': new_data.get('intro', ''),
                            'pic': new_data.get('pic', {}),
                            'actors': [
                                {
                                    'id': actor.get('id'), 'name': actor.get('name'),
                                    'latin_name': actor.get('latin_name'), 'character': actor.get('character'),
                                    'avatar': actor.get('avatar', {})
                                } for actor in new_data.get('actors', [])
                            ],
                            'imdb_id': _parse_folder_name(os.path.basename(found_folder))[1],
                            'countries': new_data.get('countries', [])
                        }
                        
                        extra_fields = self.douban_config.extra_fields
                        if 'rating' in extra_fields: item_data['rating'] = new_data.get('rating', {}).get('value')
                        if 'pubdate' in extra_fields: item_data['pubdate'] = new_data.get('pubdate', [])
                        if 'card_subtitle' in extra_fields: item_data['card_subtitle'] = new_data.get('card_subtitle', '')
                        if 'languages' in extra_fields: item_data['languages'] = new_data.get('languages', [])
                        if 'durations' in extra_fields and item['Type'] == 'Movie': item_data['durations'] = new_data.get('durations', [])

                        douban_map[douban_id] = item_data
                        updated_count += 1

                    with open(DOUBAN_CACHE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(douban_map, f, ensure_ascii=False, indent=4)
                    ui_logger.info(f"✅ 主缓存更新完毕，共覆盖 {updated_count} 条记录。", task_category=task_cat)

            except Timeout:
                ui_logger.error("❌ 更新主缓存失败：获取文件锁超时。", task_category=task_cat)
            except Exception as e:
                ui_logger.error(f"❌ 更新主缓存时发生未知错误: {e}", task_category=task_cat)
        else:
            ui_logger.info("没有成功刷新的项目，跳过主缓存更新。", task_category=task_cat)

        # 阶段四：后续自动化
        if not config.enable_post_refresh_actions:
            ui_logger.info("➡️ [阶段 4/5 & 5/5] 后续自动化流程已禁用，任务结束。", task_category=task_cat)
            return

        ui_logger.info("➡️ [阶段 4/5] 后续自动化已启用，开始比对元数据变更...", task_category=task_cat)
        items_to_deep_process = []
        try:
            with open(DOUBAN_CACHE_FILE, 'r', encoding='utf-8') as f:
                current_douban_map = json.load(f)
            
            for item in successful_items:
                douban_id = next((v for k, v in item.get("ProviderIds", {}).items() if k.lower() == 'douban'), None)
                if not douban_id: continue

                old_actors = old_actor_data_map.get(douban_id, [])
                new_item_data = current_douban_map.get(douban_id)
                if not new_item_data: continue
                new_actors = new_item_data.get('actors', [])

                if self._compare_actor_lists(old_actors, new_actors):
                    ui_logger.info(f"   - [检测到变更] 《{item['Name']}》的演员或角色信息已更新。", task_category=task_cat)
                    items_to_deep_process.append(item)
                else:
                    ui_logger.info(f"   - [无变更] 《{item['Name']}》的演员信息未发生变化，跳过深度处理。", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"❌ 比对元数据时发生错误，将跳过后续自动化流程: {e}", task_category=task_cat)
            items_to_deep_process = []

        if not items_to_deep_process:
            ui_logger.info("➡️ [阶段 5/5] 没有检测到元数据有变更的项目，任务结束。", task_category=task_cat)
            return

        ui_logger.info(f"➡️ [阶段 5/5] 开始对 {len(items_to_deep_process)} 个变更项目执行深度处理...", task_category=task_cat)
        for i, item in enumerate(items_to_deep_process):
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务在深度处理阶段被用户取消。", task_category=task_cat)
                break
            
            item_id = item['Id']
            item_name = item['Name']
            ui_logger.info(f"  - ({i+1}/{len(items_to_deep_process)}) 正在深度处理《{item_name}》...", task_category=task_cat)
            
            # 1. 触发Emby刷新
            self._trigger_emby_refresh(item_id, task_cat)
            ui_logger.info(f"     - ⏱️ 等待 {config.emby_refresh_wait_seconds} 秒让 Emby 应用元数据...", task_category=task_cat)
            time.sleep(config.emby_refresh_wait_seconds)

            # 2. 演员中文化
            try:
                localizer_logic = ActorLocalizerLogic(self.app_config)
                localizer_logic._process_single_item_for_localization(item_id, self.app_config.actor_localizer_config, task_cat)
            except Exception as e:
                ui_logger.error(f"     - ❌ 演员中文化步骤失败: {e}", task_category=task_cat)

            # 3. 角色映射更新
            try:
                role_mapper_logic = ActorRoleMapperLogic(self.app_config)
                role_mapper_logic.generate_map_for_single_item(item_id, task_category=task_cat, overwrite=True)
            except Exception as e:
                ui_logger.error(f"     - ❌ 角色映射更新步骤失败: {e}", task_category=task_cat)

        ui_logger.info("🎉 所有流程执行完毕！", task_category=task_cat)


    def run_metadata_fix_task(self, scope: ScheduledTasksTargetScope, config: DoubanMetadataRefresherConfig, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "元数据修复"
        ui_logger.info(f"🎉 任务启动，范围: {scope.mode}", task_category=task_cat)

        # 阶段一：准备与强制过滤
        ui_logger.info("➡️ [阶段 1/3] 正在获取并强制过滤媒体项 (必须包含豆瓣ID)...", task_category=task_cat)
        selector = MediaSelector(self.app_config)
        all_item_ids = selector.get_item_ids(scope)
        if not all_item_ids:
            ui_logger.info("✅ 在指定范围内未找到任何媒体项，任务完成。", task_category=task_cat)
            return

        items_to_process = []
        skipped_count = 0
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_id = {executor.submit(self._get_item_details, item_id): item_id for item_id in all_item_ids}
            for future in as_completed(future_to_id):
                if cancellation_event.is_set(): return
                try:
                    details = future.result()
                    if details:
                        provider_ids = details.get("ProviderIds", {})
                        provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
                        if 'douban' in provider_ids_lower and provider_ids_lower['douban']:
                            items_to_process.append(details)
                        else:
                            skipped_count += 1
                            logging.info(f"【{task_cat}-跳过】媒体《{details.get('Name')}》因缺少豆瓣ID而被跳过。")
                    else:
                        skipped_count += 1
                except Exception:
                    skipped_count += 1
        
        if not items_to_process:
            ui_logger.warning(f"⚠️ 在指定范围内的所有媒体项均缺少豆瓣ID或获取失败，任务中止。共跳过 {skipped_count} 项。", task_category=task_cat)
            return
        
        total_items = len(items_to_process)
        ui_logger.info(f"✅ 过滤完成，共 {total_items} 个项目将执行修复。(已跳过 {skipped_count} 个无ID或获取失败的项目)", task_category=task_cat)
        task_manager.update_task_progress(task_id, 0, total_items)

        # 阶段二：核心修复循环
        ui_logger.info("➡️ [阶段 2/3] 开始对每个项目执行修复链条...", task_category=task_cat)
        for i, item in enumerate(items_to_process):
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务被用户取消。", task_category=task_cat)
                break
            
            item_id = item['Id']
            item_name = item['Name']
            ui_logger.info(f"  - ({i+1}/{total_items}) 正在处理《{item_name}》...", task_category=task_cat)
            task_manager.update_task_progress(task_id, i + 1, total_items)

            try:
                # 1. 触发Emby刷新
                self._trigger_emby_refresh(item_id, task_cat)
                ui_logger.info(f"     - ⏱️ 等待 {config.emby_refresh_wait_seconds} 秒让 Emby 应用元数据...", task_category=task_cat)
                time.sleep(config.emby_refresh_wait_seconds)

                # 2. 演员中文化
                localizer_logic = ActorLocalizerLogic(self.app_config)
                localizer_logic._process_single_item_for_localization(item_id, self.app_config.actor_localizer_config, task_cat)

                # 3. 角色映射覆盖更新
                role_mapper_logic = ActorRoleMapperLogic(self.app_config)
                role_mapper_logic.generate_map_for_single_item(item_id, task_category=task_cat, overwrite=True)

            except Exception as e:
                ui_logger.error(f"     - ❌ 处理《{item_name}》时发生未知错误: {e}", task_category=task_cat, exc_info=True)

            if i < total_items - 1:
                ui_logger.info(f"     - ⏱️ [间隔] 等待 {config.item_interval_seconds} 秒...", task_category=task_cat)
                time.sleep(config.item_interval_seconds)

        ui_logger.info("➡️ [阶段 3/3] 🎉 所有选定项目修复流程执行完毕！", task_category=task_cat)