# backend/media_tagger_logic.py (完整文件覆盖)

import logging
import threading
import requests
from typing import Dict, List, Set, Any
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

    # --- 新增：统一的、健壮的 Item 解析器 ---
    def _parse_item_data(self, item: Dict, lib_id: str, library_names: Dict[str, str]) -> Dict:
        """从原始 item 字典中安全地提取所需信息，并兼容多种标签格式"""
        item_id = item.get('Id')
        
        # 兼容 TagItems (对象列表) 和 Tags (字符串列表)
        tags_set = set()
        if 'TagItems' in item and isinstance(item['TagItems'], list):
            tags_set = {
                tag.get('Name') 
                for tag in item.get('TagItems', []) 
                if isinstance(tag, dict) and tag.get('Name')
            }
        elif 'Tags' in item and isinstance(item['Tags'], list):
            # 确保只处理字符串类型的标签
            tags_set = {tag for tag in item['Tags'] if isinstance(tag, str)}

        genres_set = {
            genre.get('Name') 
            for genre in item.get('Genres', []) 
            if isinstance(genre, dict) and genre.get('Name')
        }
        
        return {
            'Id': item_id,
            'Name': item.get('Name', f"ID {item_id}"),
            'LibraryId': lib_id,
            'LibraryName': library_names.get(lib_id, "未知库"),
            'Tags': tags_set,
            'Genres': genres_set
        }

    def _get_libraries(self) -> List[Dict]:
        """获取当前用户可见的所有媒体库列表"""
        task_cat = "媒体标签器"
        try:
            url = f"{self.server_config.server}/Users/{self.server_config.user_id}/Views"
            params = {"api_key": self.server_config.api_key}
            proxies = self.proxy_manager.get_proxies(url)
            response = self.session.get(url, params=params, timeout=15, proxies=proxies)
            response.raise_for_status()
            views = response.json().get("Items", [])
            valid_collection_types = ["movies", "tvshows", "homevideos", "music", "mixed"]
            libraries = [
                {"Id": v["Id"], "Name": v["Name"]} 
                for v in views 
                if v.get("CollectionType") in valid_collection_types or v.get("Type") == "CollectionFolder"
            ]
            return libraries
        except Exception as e:
            logging.error(f"【{task_cat}】获取媒体库列表失败: {e}", exc_info=True)
            return []

    def _get_items_from_library(self, library_id: str, fields: str) -> List[Dict]:
        """获取指定媒体库中的所有媒体项，并包含指定字段"""
        task_cat = "媒体标签器"
        all_items = []
        url = f"{self.server_config.server}/Users/{self.server_config.user_id}/Items"
        params = {
            "api_key": self.server_config.api_key,
            "ParentId": library_id,
            "Recursive": "true", 
            "IncludeItemTypes": "Movie,Series",
            "Fields": fields
        }
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

    # --- 新增：通用的、根据媒体库ID列表获取数据的方法 ---
    def _get_media_from_libraries(self, library_ids: List[str], task_cat: str) -> Dict[str, Dict[str, Any]]:
        """根据指定的媒体库ID列表，并发获取所有媒体项数据"""
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
                            parsed_data = self._parse_item_data(item, lib_id, library_names)
                            all_parsed_items[parsed_data['Id']] = parsed_data
                        else:
                            logging.warning(f"【{task_cat}】在媒体库 (ID: {lib_id}) 中发现一个非标准格式的项目，已跳过: {item}")
                except Exception as e:
                    ui_logger.error(f"❌ 处理媒体库 (ID: {lib_id}) 内容时失败: {e}", task_category=task_cat)
        
        ui_logger.info(f"✅ 数据准备完成，共获取到 {len(all_parsed_items)} 个媒体项。", task_category=task_cat)
        return all_parsed_items
    
    def _filter_items_by_rule(self, all_items: Dict[str, Dict[str, Any]], rule: MediaTaggerRule) -> Set[str]:
        """根据单条规则筛选出符合条件的媒体项ID"""
        
        lib_target = rule.target.libraries
        if lib_target.mode == 'all':
            eligible_ids = set(all_items.keys())
        elif lib_target.mode == 'include':
            eligible_ids = {item_id for item_id, item in all_items.items() if item['LibraryName'] in lib_target.names}
        elif lib_target.mode == 'exclude':
            eligible_ids = {item_id for item_id, item in all_items.items() if item['LibraryName'] not in lib_target.names}
        else:
            eligible_ids = set()

        genre_target = rule.target.genres
        if genre_target.mode == 'any' or not genre_target.names:
            return eligible_ids

        final_ids = set()
        filter_genres = set(genre_target.names)

        for item_id in eligible_ids:
            item_genres = all_items[item_id]['Genres']
            
            if genre_target.mode == 'include':
                if genre_target.match == 'or':
                    if item_genres.intersection(filter_genres):
                        final_ids.add(item_id)
                elif genre_target.match == 'and':
                    if filter_genres.issubset(item_genres):
                        final_ids.add(item_id)
            
            elif genre_target.mode == 'exclude':
                if genre_target.match == 'or':
                    if not item_genres.intersection(filter_genres):
                        final_ids.add(item_id)
                elif genre_target.match == 'and':
                    if not filter_genres.issubset(item_genres):
                        final_ids.add(item_id)
        
        return final_ids

    def _update_item_tags(self, item_id: str, final_tags: List[str]) -> bool:
        """向 Emby 更新单个媒体项的标签，采用经过验证的先GET后POST的完整对象更新模式"""
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

    def run_tagging_task(self, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "媒体标签器"
        ui_logger.info("➡️ [步骤 1/4] 开始预分析规则并确定需要扫描的媒体库...", task_category=task_cat)
        
        all_libraries = self._get_libraries()
        if not all_libraries:
            ui_logger.warning("⚠️ 未找到任何媒体库，任务中止。", task_category=task_cat)
            return
        
        all_lib_map_name_to_id = {lib['Name']: lib['Id'] for lib in all_libraries}
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
        change_set: Dict[str, Dict[str, Set[str]]] = {}
        for i, rule in enumerate(enabled_rules):
            ui_logger.info(f"   - [规则 {i+1}/{len(enabled_rules)}] 正在处理: “{rule.remark}”", task_category=task_cat)
            matched_ids = self._filter_items_by_rule(all_items, rule)
            ui_logger.info(f"     - 🔍 匹配到 {len(matched_ids)} 个媒体项。", task_category=task_cat)
            tags_to_add = set(rule.action.add_tags)
            tags_to_remove = set(rule.action.remove_tags)
            for item_id in matched_ids:
                if item_id not in change_set:
                    change_set[item_id] = {"add": set(), "remove": set()}
                change_set[item_id]["add"].update(tags_to_add)
                change_set[item_id]["remove"].update(tags_to_remove)
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
                    'initial_tags': initial_tags, 'final_tags': final_tags
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
            # --- 修改 ---
            item_id, item_name = item_data['id'], item_data['name']
            initial_tags, final_tags = item_data['initial_tags'], item_data['final_tags']
            
            added = sorted(list(final_tags - initial_tags))
            removed = sorted(list(initial_tags - final_tags))
            
            log_msg = f"   - 正在处理【{item_name}】: 当前标签 [{', '.join(sorted(list(initial_tags)))}]，"
            if added: log_msg += f" 新增 [{', '.join(added)}]"
            if removed: log_msg += f" 移除 [{', '.join(removed)}]"
            ui_logger.info(log_msg.strip(), task_category=task_cat)

            if self._update_item_tags(item_id, list(final_tags)):
                success_count += 1
            # --- 修改结束 ---
            processed_count += 1
            task_manager.update_task_progress(task_id, processed_count, len(items_to_update))

        ui_logger.info(f"✅ [步骤 4/4] 应用变更完成。", task_category=task_cat)
        ui_logger.info(f"🎉 任务执行完毕！共处理 {len(items_to_update)} 个媒体项，成功更新 {success_count} 个。", task_category=task_cat)

    def clear_all_tags_task(self, scope: Dict, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """清空指定范围内媒体项的所有标签"""
        task_cat = "清空所有标签"
        ui_logger.info(f"➡️ [步骤 1/2] 开始根据范围获取媒体项...", task_category=task_cat)
        
        all_libraries = self._get_libraries()
        all_lib_map_name_to_id = {lib['Name']: lib['Id'] for lib in all_libraries}
        
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
            
            # --- 修改 ---
            item_name = all_items[item_id].get('Name', f"ID {item_id}")
            current_tags = all_items[item_id].get('Tags', set())
            ui_logger.info(f"   - 正在处理【{item_name}】: 当前标签 [{', '.join(sorted(list(current_tags)))}]，将清空所有标签...", task_category=task_cat)
            if self._update_item_tags(item_id, []):
                success_count += 1
            # --- 修改结束 ---
            
            processed_count += 1
            task_manager.update_task_progress(task_id, processed_count, len(items_to_clear))
        
        ui_logger.info(f"🎉 任务执行完毕！共处理 {processed_count} 个媒体项，成功清空 {success_count} 个。", task_category=task_cat)

    def remove_specific_tags_task(self, tags_to_remove: List[str], scope: Dict, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """从指定范围的媒体项中移除指定的标签"""
        task_cat = "移除指定标签"
        tags_to_remove_set = set(tags_to_remove)
        ui_logger.info(f"➡️ [步骤 1/2] 开始根据范围获取媒体项，准备移除标签: {tags_to_remove}", task_category=task_cat)
        
        all_libraries = self._get_libraries()
        all_lib_map_name_to_id = {lib['Name']: lib['Id'] for lib in all_libraries}
        
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

            # --- 修改 ---
            item_name = all_items[item_id].get('Name', f"ID {item_id}")
            current_tags = all_items[item_id].get('Tags', set())
            removed = sorted(list(current_tags.intersection(tags_to_remove_set)))
            new_tags = list(current_tags - tags_to_remove_set)

            ui_logger.info(f"   - 正在处理【{item_name}】: 当前标签 [{', '.join(sorted(list(current_tags)))}]，将移除 [{', '.join(removed)}]...", task_category=task_cat)
            if self._update_item_tags(item_id, new_tags):
                success_count += 1
            # --- 修改结束 ---
            
            processed_count += 1
            task_manager.update_task_progress(task_id, processed_count, len(items_to_process))

        ui_logger.info(f"🎉 任务执行完毕！共处理 {processed_count} 个媒体项，成功更新 {success_count} 个。", task_category=task_cat)