# backend/media_tagger_logic.py (完整文件覆盖 - 逻辑隔离最终版)

import logging
import threading
import requests
from typing import Dict, List, Set, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from models import AppConfig, MediaTaggerConfig, MediaTaggerRule
from log_manager import ui_logger
from task_manager import TaskManager
from proxy_manager import ProxyManager

class MediaTaggerLogic:
    def __init__(self, config: AppConfig):
        self.config = config
        self.server_config = config.server_config
        self.tagger_config = config.media_tagger_config
        self.proxy_manager = ProxyManager(config)
        self.session = requests.Session()
        self._library_cache = None
        self._physical_library_cache = None

    # --- 默认的、用于批量任务的媒体库获取方法 (基于 /Views) ---
    def _get_libraries(self) -> List[Dict]:
        if self._library_cache is not None:
            return self._library_cache
        task_cat = "媒体标签器"
        try:
            url = f"{self.server_config.server}/Users/{self.server_config.user_id}/Views"
            params = {"api_key": self.server_config.api_key}
            proxies = self.proxy_manager.get_proxies(url)
            response = self.session.get(url, params=params, timeout=15, proxies=proxies)
            response.raise_for_status()
            views = response.json().get("Items", [])
            libraries = [
                {"Id": v["Id"], "Name": v["Name"]} 
                for v in views 
                if v.get("Id") and v.get("Name")
            ]
            self._library_cache = libraries
            return self._library_cache
        except Exception as e:
            logging.error(f"【{task_cat}】获取媒体库列表 (/Views) 失败: {e}", exc_info=True)
            return []

    # --- 专用于 Webhook 的、基于物理路径的媒体库匹配方法 ---
    def _get_library_for_item_by_path(self, item_id: str) -> Optional[Dict]:
        task_cat = "媒体标签器-Webhook"
        try:
            # 1. 获取媒体项的物理路径
            item_url = f"{self.server_config.server}/Users/{self.server_config.user_id}/Items/{item_id}"
            params = {"api_key": self.server_config.api_key, "Fields": "Path"}
            proxies = self.proxy_manager.get_proxies(item_url)
            response = self.session.get(item_url, params=params, timeout=15, proxies=proxies)
            response.raise_for_status()
            item_path = response.json().get('Path')
            if not item_path:
                ui_logger.warning(f"⚠️ 无法获取媒体项 (ID: {item_id}) 的物理路径，无法进行匹配。", task_cat=task_cat)
                return None

            # 2. 获取所有媒体库及其扫描路径 (带缓存)
            if self._physical_library_cache is None:
                folders_url = f"{self.server_config.server}/Library/VirtualFolders/Query"
                folders_params = {"api_key": self.server_config.api_key}
                folders_proxies = self.proxy_manager.get_proxies(folders_url)
                folders_response = self.session.get(folders_url, params=folders_params, timeout=15, proxies=folders_proxies)
                if folders_response.status_code == 404:
                    folders_url = f"{self.server_config.server}/emby/Library/VirtualFolders/Query"
                    folders_response = self.session.get(folders_url, params=folders_params, timeout=15, proxies=folders_proxies)
                folders_response.raise_for_status()
                self._physical_library_cache = folders_response.json().get("Items", [])
            
            all_physical_libraries = self._physical_library_cache

            # 3. 进行前缀匹配
            for library in all_physical_libraries:
                if library.get("CollectionType") == "boxsets": continue # 显式跳过合集
                locations = library.get("Locations", [])
                for loc_path in locations:
                    if item_path.startswith(loc_path):
                        return {"Id": library.get("ItemId", library.get("Id")), "Name": library.get("Name")}
            return None
        except Exception as e:
            logging.error(f"【{task_cat}】通过物理路径为媒体项 {item_id} 匹配媒体库时出错: {e}", exc_info=True)
            return None

    def _parse_item_data(self, item: Dict, lib_id: str, library_name: str) -> Dict:
        item_id = item.get('Id')
        
        # --- 核心修改：增强标签和类型的解析逻辑，使其更健壮 ---
        tags_set = set()
        # 优先处理 TagItems (对象列表)
        if 'TagItems' in item and isinstance(item['TagItems'], list):
            tags_set = {t.get('Name') for t in item.get('TagItems', []) if isinstance(t, dict) and t.get('Name')}
        # 降级处理 Tags (字符串列表)
        elif 'Tags' in item and isinstance(item['Tags'], list):
            tags_set = {tag for tag in item['Tags'] if isinstance(tag, str)}

        genres_set = set()
        # 优先处理 GenreItems (对象列表)
        if 'GenreItems' in item and isinstance(item['GenreItems'], list):
            genres_set = {g.get('Name') for g in item.get('GenreItems', []) if isinstance(g, dict) and g.get('Name')}
        # 降级处理 Genres (字符串列表)
        elif 'Genres' in item and isinstance(item['Genres'], list):
            genres_set = {genre for genre in item['Genres'] if isinstance(genre, str)}
        # --- 修改结束 ---

        return {
            'Id': item_id, 'Name': item.get('Name', f"ID {item_id}"),
            'LibraryId': lib_id, 'LibraryName': library_name,
            'Tags': tags_set, 'Genres': genres_set
        }

    # backend/media_tagger_logic.py (函数替换)

    def _get_items_from_library(self, library_id: str, fields: str) -> List[Dict]:
        """获取指定媒体库中的所有媒体项，并包含指定字段"""
        task_cat = "媒体标签器"
        all_items = []
        # --- 核心修改：统一使用系统级 /Items 端点 ---
        url = f"{self.server_config.server}/Items"
        params = {
            "api_key": self.server_config.api_key, "ParentId": library_id,
            "Recursive": "true", "IncludeItemTypes": "Movie,Series", "Fields": fields
        }
        # --- 修改结束 ---
        start_index = 0
        while True:
            params["StartIndex"] = start_index
            try:
                proxies = self.proxy_manager.get_proxies(url)
                response = self.session.get(url, params=params, timeout=60, proxies=proxies)
                response.raise_for_status()
                page_items = response.json().get("Items", [])
                if not page_items: break
                all_items.extend(page_items)
                start_index += len(page_items)
            except requests.RequestException as e:
                ui_logger.error(f"【{task_cat}】从媒体库 {library_id} 获取项目时出错: {e}", task_category=task_cat)
                break
        return all_items

    def _get_media_from_libraries(self, library_ids: List[str], task_cat: str) -> Dict[str, Dict[str, Any]]:
        all_libraries = self._get_libraries()
        target_libraries = [lib for lib in all_libraries if lib['Id'] in library_ids]
        library_names = {lib['Id']: lib['Name'] for lib in target_libraries}
        ui_logger.info(f"🔍 将扫描 {len(target_libraries)} 个媒体库: {[lib['Name'] for lib in target_libraries]}", task_category=task_cat)
        all_parsed_items = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_lib = {
                executor.submit(self._get_items_from_library, lib['Id'], "Tags,TagItems,Genres"): lib['Id'] 
                for lib in target_libraries
            }
            for future in as_completed(future_to_lib):
                lib_id = future_to_lib[future]
                try:
                    items = future.result()
                    for item in items:
                        if isinstance(item, dict) and item.get('Id'):
                            parsed_data = self._parse_item_data(item, lib_id, library_names[lib_id])
                            all_parsed_items[parsed_data['Id']] = parsed_data
                        else:
                            logging.warning(f"【{task_cat}】在媒体库 (ID: {lib_id}) 中发现一个非标准格式的项目，已跳过: {item}")
                except Exception as e:
                    ui_logger.error(f"❌ 处理媒体库 (ID: {lib_id}) 内容时失败: {e}", task_category=task_cat)
        ui_logger.info(f"✅ 数据准备完成，共获取到 {len(all_parsed_items)} 个媒体项。", task_category=task_cat)
        return all_parsed_items

    def _update_item_tags(self, item_id: str, final_tags: List[str]) -> bool:
        task_cat = "媒体标签器"
        try:
            get_url = f"{self.server_config.server}/Users/{self.server_config.user_id}/Items/{item_id}"
            params = {"api_key": self.server_config.api_key}
            proxies = self.proxy_manager.get_proxies(get_url)
            response = self.session.get(get_url, params=params, timeout=15, proxies=proxies)
            response.raise_for_status()
            item_data = response.json()
            sorted_final_tags = sorted(list(final_tags))
            item_data['Tags'] = sorted_final_tags
            item_data['TagItems'] = [{"Name": tag} for tag in sorted_final_tags]
            locked_fields = set(item_data.get('LockedFields', []))
            if 'Tags' in locked_fields:
                ui_logger.info(f"   - ℹ️ 注意：媒体项【{item_data.get('Name')}】的标签字段被锁定，将临时解锁以进行更新。", task_cat=task_cat)
                locked_fields.remove('Tags')
                item_data['LockedFields'] = list(locked_fields)
            update_url = f"{self.server_config.server}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            update_params = {"api_key": self.server_config.api_key}
            update_proxies = self.proxy_manager.get_proxies(update_url)
            update_response = self.session.post(
                update_url, params=update_params, headers=headers, json=item_data, timeout=20, proxies=update_proxies
            )
            update_response.raise_for_status()
            return True
        except Exception as e:
            logging.error(f"更新媒体 {item_id} 标签时出错: {e}", exc_info=True)
            if 'update_response' in locals() and update_response is not None:
                logging.error(f"失败的请求响应内容: {update_response.text}")
            return False

    def _filter_items_by_rule(self, all_items: Dict[str, Dict[str, Any]], rule: MediaTaggerRule) -> Set[str]:
        lib_target = rule.target.libraries
        if lib_target.mode == 'all':
            eligible_ids = set(all_items.keys())
        elif lib_target.mode == 'include':
            eligible_ids = {item_id for item_id, item in all_items.items() if item['LibraryName'] in lib_target.names}
        elif lib_target.mode == 'exclude':
            eligible_ids = {item_id for item_id, item in all_items.items() if item['LibraryName'] not in lib_target.names}
        else: eligible_ids = set()
        genre_target = rule.target.genres
        if genre_target.mode == 'any' or not genre_target.names: return eligible_ids
        final_ids, filter_genres = set(), set(genre_target.names)
        for item_id in eligible_ids:
            item_genres = all_items[item_id]['Genres']
            if genre_target.mode == 'include':
                if genre_target.match == 'or' and item_genres.intersection(filter_genres): final_ids.add(item_id)
                elif genre_target.match == 'and' and filter_genres.issubset(item_genres): final_ids.add(item_id)
            elif genre_target.mode == 'exclude':
                if genre_target.match == 'or' and not item_genres.intersection(filter_genres): final_ids.add(item_id)
                elif genre_target.match == 'and' and not filter_genres.issubset(item_genres): final_ids.add(item_id)
        return final_ids

    def process_single_item(self, item_id: str, task_cat: str):
        ui_logger.info(f"➡️ 开始为媒体项 (ID: {item_id}) 应用标签规则...", task_category=task_cat)
        try:
            # 1. 确定媒体项所属的媒体库 (使用物理路径匹配的专用方法)
            library = self._get_library_for_item_by_path(item_id)
            if not library:
                ui_logger.warning(f"⚠️ 无法确定媒体项 (ID: {item_id}) 所属的媒体库，跳过打标签。", task_category=task_cat)
                return
            library_id, library_name = library['Id'], library['Name']
            ui_logger.info(f"   - ✅ 已确定媒体项所属媒体库为: 【{library_name}】", task_category=task_cat)

            # 2. 获取媒体项的详细信息
            item_data_url = f"{self.server_config.server}/Users/{self.server_config.user_id}/Items/{item_id}"
            item_data_params = {"api_key": self.server_config.api_key, "Fields": "Tags,TagItems,Genres"}
            item_data_proxies = self.proxy_manager.get_proxies(item_data_url)
            item_data_response = self.session.get(item_data_url, params=item_data_params, timeout=15, proxies=item_data_proxies)
            item_data_response.raise_for_status()
            item_data = item_data_response.json()

            # 3. 规则匹配与演算
            parsed_item = self._parse_item_data(item_data, library_id, library_name)
            initial_tags = parsed_item['Tags']
            change_set = {"add": set(), "remove": set()}
            enabled_rules = [rule for rule in self.tagger_config.rules if rule.enabled]
            for i, rule in enumerate(enabled_rules):
                matched_ids = self._filter_items_by_rule({item_id: parsed_item}, rule)
                if item_id in matched_ids:
                    ui_logger.info(f"   - ✅ 命中规则 #{i+1}: “{rule.remark}”", task_category=task_cat)
                    tags_to_add, tags_to_remove = set(rule.action.add_tags), set(rule.action.remove_tags)
                    change_set["add"].update(tags_to_add)
                    change_set["remove"].update(tags_to_remove)
                    conflicts = change_set["add"].intersection(change_set["remove"])
                    if conflicts:
                        change_set["add"].difference_update(conflicts)
                        change_set["remove"].difference_update(conflicts)
            
            # 4. 计算并更新
            final_tags = (initial_tags.union(change_set['add'])).difference(change_set['remove'])
            if final_tags != initial_tags:
                added = sorted(list(final_tags - initial_tags))
                removed = sorted(list(initial_tags - final_tags))
                log_msg = f"   - 正在处理【{parsed_item['Name']}】: 当前标签 [{', '.join(sorted(list(initial_tags)))}]，"
                if added: log_msg += f" 新增 [{', '.join(added)}]"
                if removed: log_msg += f" 移除 [{', '.join(removed)}]"
                ui_logger.info(log_msg.strip(), task_category=task_cat)
                self._update_item_tags(item_id, list(final_tags))
            else:
                ui_logger.info(f"   - 媒体项【{parsed_item['Name']}】的标签已符合所有规则，无需更新。", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"❌ 为媒体项 {item_id} 应用标签时发生错误: {e}", task_category=task_cat)

    # backend/media_tagger_logic.py (函数替换)

    def run_tagging_task(self, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "媒体标签器-应用规则"
        ui_logger.info("➡️ [步骤 1/4] 开始预分析规则并确定需要扫描的媒体库...", task_category=task_cat)
        all_libraries = self._get_libraries()
        if not all_libraries:
            ui_logger.warning("⚠️ 未找到任何媒体库，任务中止。", task_category=task_cat)
            return
        all_lib_map_name_to_id = {lib['Name']: lib["Id"] for lib in all_libraries}
        all_lib_ids = set(all_lib_map_name_to_id.values())
        final_required_ids = set()
        enabled_rules = [rule for rule in self.tagger_config.rules if rule.enabled]
        if not enabled_rules:
            ui_logger.info("✅ 未启用任何规则，无需扫描媒体项，任务提前结束。", task_category=task_cat)
            return
        for rule in enabled_rules:
            lib_target = rule.target.libraries
            if lib_target.mode == 'all':
                final_required_ids = all_lib_ids
                break
            elif lib_target.mode == 'include':
                rule_ids = {all_lib_map_name_to_id[name] for name in lib_target.names if name in all_lib_map_name_to_id}
                final_required_ids.update(rule_ids)
            elif lib_target.mode == 'exclude':
                excluded_ids = {all_lib_map_name_to_id[name] for name in lib_target.names if name in all_lib_map_name_to_id}
                rule_ids = all_lib_ids - excluded_ids
                final_required_ids.update(rule_ids)
        if not final_required_ids:
            ui_logger.info("✅ 根据所有规则计算后，没有需要扫描的媒体库，任务提前结束。", task_category=task_cat)
            return
        all_items = self._get_media_from_libraries(list(final_required_ids), task_cat)
        if not all_items: return
        if cancellation_event.is_set():
            ui_logger.warning("⚠️ 任务在数据准备阶段被取消。", task_category=task_cat)
            return
        ui_logger.info("➡️ [步骤 2/4] 开始根据规则进行离线演算...", task_category=task_cat)
        
        # --- 核心修改：初始化 change_set 以存储命中规则的详细信息 ---
        change_set: Dict[str, Dict[str, Any]] = {}
        # --- 修改结束 ---

        for i, rule in enumerate(enabled_rules):
            ui_logger.info(f"   - [规则 {i+1}/{len(enabled_rules)}] 正在处理: “{rule.remark}”", task_category=task_cat)
            matched_ids = self._filter_items_by_rule(all_items, rule)
            ui_logger.info(f"     - 🔍 匹配到 {len(matched_ids)} 个媒体项。", task_category=task_cat)
            tags_to_add, tags_to_remove = set(rule.action.add_tags), set(rule.action.remove_tags)
            for item_id in matched_ids:
                if item_id not in change_set:
                    # --- 核心修改：扩展 change_set 结构 ---
                    change_set[item_id] = {"add": set(), "remove": set(), "matched_rules": []}
                
                change_set[item_id]["add"].update(tags_to_add)
                change_set[item_id]["remove"].update(tags_to_remove)
                # --- 新增：记录命中的规则备注 ---
                change_set[item_id]["matched_rules"].append(rule.remark)
                # --- 新增结束 ---

                conflicts = change_set[item_id]["add"].intersection(change_set[item_id]["remove"])
                if conflicts:
                    change_set[item_id]["add"].difference_update(conflicts)
                    change_set[item_id]["remove"].difference_update(conflicts)

        ui_logger.info("✅ [步骤 2/4] 离线演算完成。", task_category=task_cat)
        ui_logger.info("➡️ [步骤 3/4] 开始计算最终标签并识别变更...", task_category=task_cat)
        items_to_update = []
        for item_id, changes in change_set.items():
            initial_tags = all_items[item_id]['Tags']
            final_tags = (initial_tags.union(changes['add'])).difference(changes['remove'])
            if final_tags != initial_tags:
                items_to_update.append({
                    'id': item_id, 'name': all_items[item_id]['Name'],
                    'initial_tags': initial_tags, 'final_tags': final_tags,
                    # --- 新增：将命中的规则和类型信息传递下去 ---
                    'matched_rules': changes['matched_rules'],
                    'genres': all_items[item_id]['Genres']
                    # --- 新增结束 ---
                })
        if not items_to_update:
            ui_logger.info("✅ [步骤 3/4] 计算完成，未发现任何需要变更标签的媒体项。", task_category=task_cat)
            ui_logger.info("🎉 所有媒体的标签均符合规则，任务完成！", task_category=task_cat)
            return
        ui_logger.info(f"✅ [步骤 3/4] 计算完成，共发现 {len(items_to_update)} 个媒体项需要更新标签。", task_category=task_cat)
        ui_logger.info("➡️ [步骤 4/4] 开始将变更应用到 Emby...", task_category=task_cat)
        task_manager.update_task_progress(task_id, 0, len(items_to_update))
        processed_count, success_count = 0, 0
        for item_data in items_to_update:
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务在应用变更阶段被取消。", task_category=task_cat)
                return
            
            # --- 核心修改：构建更详细的日志输出 ---
            item_id, item_name = item_data['id'], item_data['name']
            initial_tags, final_tags = item_data['initial_tags'], item_data['final_tags']
            genres_str = ', '.join(sorted(list(item_data['genres']))) if item_data['genres'] else '无'
            
            ui_logger.info(f"   - 正在处理【{item_name}】", task_category=task_cat)
            ui_logger.info(f"     - 类型: [{genres_str}]", task_category=task_cat)
            for rule_remark in item_data['matched_rules']:
                ui_logger.info(f"     - 命中规则: “{rule_remark}”", task_category=task_cat)

            added = sorted(list(final_tags - initial_tags))
            removed = sorted(list(initial_tags - final_tags))
            
            change_log = ""
            if added: change_log += f" 新增 [{', '.join(added)}]"
            if removed: change_log += f" 移除 [{', '.join(removed)}]"
            
            if change_log:
                ui_logger.info(f"     - 标签变更: 当前 [{', '.join(sorted(list(initial_tags)))}] →{change_log.strip()}", task_category=task_cat)
            # --- 修改结束 ---

            if self._update_item_tags(item_id, list(final_tags)):
                success_count += 1
            processed_count += 1
            task_manager.update_task_progress(task_id, processed_count, len(items_to_update))
        ui_logger.info(f"✅ [步骤 4/4] 应用变更完成。", task_category=task_cat)
        ui_logger.info(f"🎉 任务执行完毕！共处理 {len(items_to_update)} 个媒体项，成功更新 {success_count} 个。", task_category=task_cat)

    def clear_all_tags_task(self, scope: Dict, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "清空所有标签"
        ui_logger.info(f"➡️ [步骤 1/2] 开始根据范围获取媒体项...", task_category=task_cat)
        all_libraries = self._get_libraries()
        all_lib_map_name_to_id = {lib['Name']: lib["Id"] for lib in all_libraries}
        if scope.get('mode') == 'all':
            target_lib_ids = list(all_lib_map_name_to_id.values())
        else:
            target_lib_ids = [all_lib_map_name_to_id[name] for name in scope.get('library_names', []) if name in all_lib_map_name_to_id]
        if not target_lib_ids:
            ui_logger.warning("⚠️ 在指定范围内未找到任何媒体库，任务中止。", task_category=task_cat)
            return
        all_items = self._get_media_from_libraries(target_lib_ids, task_cat)
        if not all_items: return
        items_to_clear = [item_id for item_id, item_data in all_items.items() if item_data.get('Tags')]
        if not items_to_clear:
            ui_logger.info("✅ 范围内所有媒体项都没有标签，无需操作。", task_category=task_cat)
            return
        ui_logger.info(f"🔍 [步骤 2/2] 发现 {len(items_to_clear)} 个媒体项需要清空标签，开始处理...", task_category=task_cat)
        task_manager.update_task_progress(task_id, 0, len(items_to_clear))
        processed_count, success_count = 0, 0
        for item_id in items_to_clear:
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务在处理过程中被取消。", task_category=task_cat)
                return
            item_name = all_items[item_id].get('Name', f"ID {item_id}")
            current_tags = all_items[item_id].get('Tags', set())
            ui_logger.info(f"   - 正在处理【{item_name}】: 当前标签 [{', '.join(sorted(list(current_tags)))}]，将清空所有标签...", task_category=task_cat)
            if self._update_item_tags(item_id, []):
                success_count += 1
            processed_count += 1
            task_manager.update_task_progress(task_id, processed_count, len(items_to_clear))
        ui_logger.info(f"🎉 任务执行完毕！共处理 {processed_count} 个媒体项，成功清空 {success_count} 个。", task_category=task_cat)

    def remove_specific_tags_task(self, tags_to_remove: List[str], scope: Dict, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "移除指定标签"
        tags_to_remove_set = set(tags_to_remove)
        ui_logger.info(f"➡️ [步骤 1/2] 开始根据范围获取媒体项，准备移除标签: {tags_to_remove}", task_category=task_cat)
        all_libraries = self._get_libraries()
        all_lib_map_name_to_id = {lib['Name']: lib["Id"] for lib in all_libraries}
        if scope.get('mode') == 'all':
            target_lib_ids = list(all_lib_map_name_to_id.values())
        else:
            target_lib_ids = [all_lib_map_name_to_id[name] for name in scope.get('library_names', []) if name in all_lib_map_name_to_id]
        if not target_lib_ids:
            ui_logger.warning("⚠️ 在指定范围内未找到任何媒体库，任务中止。", task_category=task_cat)
            return
        all_items = self._get_media_from_libraries(target_lib_ids, task_cat)
        if not all_items: return
        items_to_process = [
            item_id for item_id, item_data in all_items.items() 
            if item_data.get('Tags', set()).intersection(tags_to_remove_set)
        ]
        if not items_to_process:
            ui_logger.info(f"✅ 范围内未在任何媒体项中找到指定的标签，无需操作。", task_category=task_cat)
            return
        ui_logger.info(f"🔍 [步骤 2/2] 发现 {len(items_to_process)} 个媒体项包含指定标签，开始处理...", task_category=task_cat)
        task_manager.update_task_progress(task_id, 0, len(items_to_process))
        processed_count, success_count = 0, 0
        for item_id in items_to_process:
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务在处理过程中被取消。", task_category=task_cat)
                return
            item_name = all_items[item_id].get('Name', f"ID {item_id}")
            current_tags = all_items[item_id].get('Tags', set())
            removed = sorted(list(current_tags.intersection(tags_to_remove_set)))
            new_tags = list(current_tags - tags_to_remove_set)
            ui_logger.info(f"   - 正在处理【{item_name}】: 当前标签 [{', '.join(sorted(list(current_tags)))}]，将移除 [{', '.join(removed)}]...", task_category=task_cat)
            if self._update_item_tags(item_id, new_tags):
                success_count += 1
            processed_count += 1
            task_manager.update_task_progress(task_id, processed_count, len(items_to_process))
        ui_logger.info(f"🎉 任务执行完毕！共处理 {processed_count} 个媒体项，成功更新 {success_count} 个。", task_category=task_cat)