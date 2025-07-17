
import logging
import threading
import time
import requests
from typing import List, Dict, Any

# --- 核心修改 1: 导入 ui_logger ---
from log_manager import ui_logger
from models import AppConfig
from task_manager import TaskManager


def create_nfo_from_details(details: dict) -> str:
    from xml.sax.saxutils import escape
    item_type = details.get("Type", "Movie")
    root_tag = "movie" if item_type == "Movie" else "tvshow"
    xml_parts = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>', f'<{root_tag}>']
    plot = details.get('Overview', '')
    if plot:
        xml_parts.append(f"    <plot><![CDATA[{plot}]]></plot>")
        xml_parts.append(f"    <outline><![CDATA[{plot}]]></outline>")
    xml_parts.append("    <lockdata>false</lockdata>")
    try:
        from datetime import datetime
        if 'DateCreated' in details:
            date_added_obj = datetime.fromisoformat(details.get('DateCreated', '').replace('Z', '+00:00'))
            xml_parts.append(f"    <dateadded>{date_added_obj.strftime('%Y-%m-%d %H:%M:%S')}</dateadded>")
    except (ValueError, TypeError): pass
    xml_parts.append(f"    <title>{escape(details.get('Name', ''))}</title>")
    xml_parts.append(f"    <originaltitle>{escape(details.get('OriginalTitle', ''))}</originaltitle>")
    if item_type == "Movie":
        xml_parts.append(f"    <sorttitle>{escape(details.get('SortName', ''))}</sorttitle>")
    else:
        xml_parts.append(f"    <showtitle>{escape(details.get('Name', ''))}</showtitle>")
    for person in details.get('People', []):
        if not person.get('Name'): continue
        p_type = person.get('Type')
        # --- 核心修改：在处理演员的 ProviderIds 时也进行大小写不敏感处理 ---
        person_provider_ids_lower = {k.lower(): v for k, v in person.get('ProviderIds', {}).items()}
        if p_type == 'Actor':
            actor_parts = ["    <actor>", f"        <name>{escape(person['Name'])}</name>", f"        <role>{escape(person.get('Role', ''))}</role>", "        <type>Actor</type>"]
            if person_provider_ids_lower.get('tmdb'): actor_parts.append(f"        <tmdbid>{person_provider_ids_lower['tmdb']}</tmdbid>")
            actor_parts.append("    </actor>")
            xml_parts.append('\n'.join(actor_parts))
        # --- 修改结束 ---
        elif p_type == 'Director':
            xml_parts.append(f"    <director>{escape(person['Name'])}</director>")
        elif p_type == 'Writer':
            xml_parts.append(f"    <writer>{escape(person['Name'])}</writer>")
    if details.get('CommunityRating'): xml_parts.append(f"    <rating>{details['CommunityRating']}</rating>")
    if details.get('ProductionYear'): xml_parts.append(f"    <year>{details['ProductionYear']}</year>")
    
    # --- 核心修改：不区分大小写地获取 ProviderIds ---
    provider_ids_lower = {k.lower(): v for k, v in details.get('ProviderIds', {}).items()}
    if provider_ids_lower.get('imdb'): xml_parts.append(f'    <uniqueid type="imdb">{provider_ids_lower["imdb"]}</uniqueid>')
    if provider_ids_lower.get('tmdb'): xml_parts.append(f'    <uniqueid type="tmdb">{provider_ids_lower["tmdb"]}</uniqueid>')
    # --- 修改结束 ---

    for genre in details.get('Genres', []): xml_parts.append(f"    <genre>{escape(genre)}</genre>")
    xml_parts.append(f'</{root_tag}>')
    return '\n'.join(xml_parts)
    
class GenreLogic:
    def __init__(self, app_config: AppConfig):
        self.server_config = app_config.server_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}

    def get_all_genres(self) -> List[Dict[str, str]]:
        # 这个函数是同步的，且是获取基础数据，日志可以不那么详细
        url = f"{self.base_url}/Genres"
        params = {**self.params, "UserId": self.user_id}
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        genres = response.json().get("Items", [])
        return [{"id": g["Id"], "name": g["Name"]} for g in genres if "Id" in g and "Name" in g]

    def _get_items_to_scan(self, mode: str, media_type: str = None, library_ids: List[str] = None, blacklist: str = None, cancellation_event: threading.Event = None) -> List[Dict[str, str]]:
        task_cat = f"类型替换-扫描({mode})" # --- 定义任务类别 ---
        all_items = []
        if mode == 'byType':
            if not media_type: return []
            url = f"{self.base_url}/Items"
            params = {**self.params, "Recursive": "true", "IncludeItemTypes": media_type, "Fields": "Id,Name"}
            start_index = 0
            while True:
                if cancellation_event and cancellation_event.is_set(): 
                    ui_logger.info("任务在获取列表阶段被取消。", task_category=task_cat)
                    return []
                params["StartIndex"] = start_index
                response = requests.get(url, params=params, timeout=60)
                response.raise_for_status()
                items_page = response.json().get("Items", [])
                if not items_page: break
                all_items.extend(items_page)
                start_index += len(items_page)
        elif mode == 'byLibrary':
            if not library_ids: return []
            for lib_id in library_ids:
                if cancellation_event and cancellation_event.is_set(): 
                    ui_logger.info("任务在获取列表阶段被取消。", task_category=task_cat)
                    return []
                url = f"{self.base_url}/Items"
                params = {**self.params, "ParentId": lib_id, "Recursive": "true", "IncludeItemTypes": "Movie,Series", "Fields": "Id,Name"}
                start_index = 0
                while True:
                    if cancellation_event and cancellation_event.is_set(): 
                        ui_logger.info("任务在获取列表阶段被取消。", task_category=task_cat)
                        return []
                    params["StartIndex"] = start_index
                    response = requests.get(url, params=params, timeout=60)
                    response.raise_for_status()
                    items_page = response.json().get("Items", [])
                    if not items_page: break
                    all_items.extend(items_page)
                    start_index += len(items_page)
        elif mode == 'all':
            url = f"{self.base_url}/Items"
            params = {**self.params, "Recursive": "true", "IncludeItemTypes": "Movie,Series", "Fields": "Id,Name,ParentId"}
            start_index = 0
            while True:
                if cancellation_event and cancellation_event.is_set(): 
                    ui_logger.info("任务在获取列表阶段被取消。", task_category=task_cat)
                    return []
                params["StartIndex"] = start_index
                response = requests.get(url, params=params, timeout=60)
                response.raise_for_status()
                items_page = response.json().get("Items", [])
                if not items_page: break
                all_items.extend(items_page)
                start_index += len(items_page)
            if blacklist:
                views_url = f"{self.base_url}/Users/{self.user_id}/Views"
                views_resp = requests.get(views_url, params=self.params)
                views = views_resp.json().get("Items", [])
                blacklist_names = {name.strip() for name in blacklist.split(',') if name.strip()}
                blacklisted_ids = {view['Id'] for view in views if view['Name'] in blacklist_names}
                all_items = [item for item in all_items if item.get("ParentId") not in blacklisted_ids]
        return [{"id": item["Id"], "name": item["Name"]} for item in all_items]

    def _get_full_item(self, item_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
        params = {**self.params, "Fields": "GenreItems"}
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        return response.json()

    def _update_item_on_server(self, item_id: str, item_json: Dict[str, Any]) -> bool:
        url = f"{self.base_url}/Items/{item_id}"
        headers = {'Content-Type': 'application/json'}
        response = requests.post(url, params=self.params, json=item_json, headers=headers, timeout=30)
        response.raise_for_status()
        return response.status_code == 204

    def _build_new_genre_items(self, current_genre_items: List[Dict], mapping: Dict[str, str]):
        processed_genres = set()
        new_items = []
        has_change = False

        original_genre_set = {g['Name'] for g in current_genre_items}

        for item in current_genre_items:
            original_name = item.get('Name')
            replacement_name = mapping.get(original_name)

            if replacement_name and replacement_name.strip():
                if replacement_name not in processed_genres:
                    new_items.append({'Name': replacement_name, 'Id': replacement_name})
                    processed_genres.add(replacement_name)
            else:
                if original_name not in processed_genres:
                    new_items.append(item)
                    processed_genres.add(original_name)

        new_genre_set = {g['Name'] for g in new_items}

        if new_genre_set != original_genre_set:
            has_change = True
            
        return new_items, has_change

    # --- 核心修改 2: 重构 preview_changes_task 函数 ---
    def preview_changes_task(self, mapping: Dict[str, str], mode: str, media_type: str, library_ids: List[str], blacklist: str, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = f"类型替换预览({mode})"
        ui_logger.info(f"【步骤 1/3】任务启动，模式: {mode}", task_category=task_cat)
        
        items_to_scan = self._get_items_to_scan(mode, media_type, library_ids, blacklist, cancellation_event)
        total_count = len(items_to_scan)
        
        ui_logger.info(f"【步骤 2/3】范围扫描完成，共找到 {total_count} 个媒体项需要检查。", task_category=task_cat)
        ui_logger.info("【步骤 3/3】开始逐一检查媒体类型，这可能需要一些时间...", task_category=task_cat)
        task_manager.update_task_progress(task_id, 0, total_count)
        
        changes_found = []
        console_log_lines = []

        for i, item in enumerate(items_to_scan):
            if cancellation_event.is_set():
                ui_logger.warning("预览任务被用户取消。", task_category=task_cat)
                break

            item_name = item.get('name', f"Item {item['id']}")
            ui_logger.debug(f"进度 {i+1}/{total_count}: 正在扫描 [{item_name}]", task_category=task_cat)
            
            try:
                full_item = self._get_full_item(item['id'])
                current_genres = full_item.get('GenreItems', [])
                if not current_genres:
                    ui_logger.debug(f"  -> 跳过 [{item_name}]，无类型信息。", task_category=task_cat)
                    continue
                
                new_genre_items, has_change = self._build_new_genre_items(current_genres, mapping)
                
                if has_change:
                    old_names = sorted([g['Name'] for g in current_genres])
                    new_names = sorted([g['Name'] for g in new_genre_items])
                    log_message = f"发现变更: [{item_name}] | 旧: {old_names} -> 新: {new_names}"
                    ui_logger.info(log_message, task_category=task_cat)
                    console_log_lines.append(log_message)
                    
                    changes_found.append({
                        "id": item['id'],
                        "name": item_name,
                        "old_genres": old_names,
                        "new_genres": new_names,
                        "new_genre_items_for_apply": new_genre_items
                    })
            except Exception as e:
                error_message = f"扫描项目 [{item_name}] (ID: {item['id']}) 时出错: {e}"
                ui_logger.error(error_message, task_category=task_cat)
                console_log_lines.append(error_message)
            
            task_manager.update_task_progress(task_id, i + 1, total_count)
        
        if not cancellation_event.is_set():
            final_log = f"预览完成。共发现 {len(changes_found)} 个可应用的修改。"
            ui_logger.info(final_log, task_category=task_cat)
            console_log_lines.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {final_log}")
        
        return {"logs": "\n".join(console_log_lines), "results": changes_found}

    # --- 核心修改 3: 重构 apply_changes_task 函数 ---
    def apply_changes_task(self, items_to_apply: List[Dict], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "类型替换应用"
        total_count = len(items_to_apply)
        ui_logger.info(f"任务启动，开始应用类型替换，共 {total_count} 个项目。", task_category=task_cat)
        task_manager.update_task_progress(task_id, 0, total_count)
        
        for i, item_data in enumerate(items_to_apply):
            if cancellation_event.is_set():
                ui_logger.warning(f"类型替换任务在处理第 {i+1} 个项目时被取消。", task_category=task_cat)
                break
                
            item_id, item_name, new_genre_items = item_data['id'], item_data['name'], item_data['new_genre_items_for_apply']
            ui_logger.info(f"进度 {i+1}/{total_count}: 正在应用到 [{item_name}]", task_category=task_cat)
            
            try:
                full_item = self._get_full_item(item_id)
                full_item['GenreItems'] = new_genre_items
                if self._update_item_on_server(item_id, full_item):
                    ui_logger.debug(f"  -> 成功更新 [{item_name}]", task_category=task_cat)
                else:
                    ui_logger.warning(f"  -> 更新 [{item_name}] 失败，服务器未返回成功状态。", task_category=task_cat)
                time.sleep(0.1)
            except Exception as e:
                ui_logger.error(f"  -> 应用到 [{item_name}] (ID: {item_id}) 时出错: {e}", task_category=task_cat)
            
            task_manager.update_task_progress(task_id, i + 1, total_count)
            
        if not cancellation_event.is_set():
            ui_logger.info("类型替换应用任务完成。", task_category=task_cat)