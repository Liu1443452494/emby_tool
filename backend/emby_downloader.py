# backend/emby_downloader.py (修改后)

import os
import requests
import json
import logging
import threading
import re
from datetime import datetime
from xml.sax.saxutils import escape
from typing import Dict, Any, Optional

from log_manager import ui_logger
from models import AppConfig, BatchDownloadRequest, DownloadConfig
from task_manager import TaskManager

def create_nfo_from_details(details: dict, download_config: DownloadConfig) -> str:
    """
    根据从 Emby 获取的、经过处理的详细信息，生成一个功能完整的 NFO 文件。
    (此函数保持不变)
    """
    item_type = details.get("Type", "Movie")
    root_tag = "tvshow" if item_type == "Series" else "movie"
    
    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>',
        f'<{root_tag}>'
    ]

    def append_if_exists(tag, value, is_cdata=False):
        if value:
            if is_cdata:
                xml_parts.append(f"    <{tag}><![CDATA[{value}]]></{tag}>")
            else:
                xml_parts.append(f"    <{tag}>{escape(str(value))}</{tag}>")

    taglines = details.get("Taglines") or []
    first_tagline = taglines[0] if taglines else None
    
    overview = details.get("Overview", "")
    outline = first_tagline or overview
    append_if_exists("plot", overview, is_cdata=True)
    append_if_exists("outline", outline, is_cdata=True)
    
    xml_parts.append("    <lockdata>false</lockdata>")

    if date_added_str := details.get('DateCreated'):
        try:
            date_added_obj = datetime.fromisoformat(date_added_str.replace('Z', '+00:00'))
            append_if_exists("dateadded", date_added_obj.strftime('%Y-%m-%d %H:%M:%S'))
        except (ValueError, TypeError): pass

    append_if_exists("title", details.get("Name", ""))
    append_if_exists("originaltitle", details.get("OriginalTitle", ""))
    if item_type == "Movie":
        append_if_exists("sorttitle", details.get("SortName", ""))
    else:
        append_if_exists("showtitle", details.get("Name", ""))

    all_people = details.get('People', []) or []
    all_actors = [p for p in all_people if p and p.get('Type') == 'Actor']
    other_people = [p for p in all_people if p and p.get('Type') != 'Actor']
    
    limited_actors = all_actors[:download_config.nfo_actor_limit]
    logging.info(f"     -- NFO生成：共 {len(all_actors)} 位演员，将写入前 {len(limited_actors)} 位。")
    people_to_process = limited_actors + other_people

    for person in people_to_process:
        if not (person and person.get('Name')): continue
        p_type = person.get('Type')
        person_ids = person.get('ProviderIds', {}) or {}
        
        tmdbid = next((v for k, v in person_ids.items() if k.lower() == 'tmdb'), None)
        imdbid = next((v for k, v in person_ids.items() if k.lower() == 'imdb'), None)

        if p_type == 'Actor':
            actor_parts = ["    <actor>", f"        <name>{escape(person['Name'])}</name>", f"        <role>{escape(person.get('Role', ''))}</role>", "        <type>Actor</type>"]
            if tmdbid: actor_parts.append(f"        <tmdbid>{tmdbid}</tmdbid>")
            if imdbid: actor_parts.append(f"        <imdbid>{imdbid}</imdbid>")
            actor_parts.append("    </actor>")
            xml_parts.append('\n'.join(actor_parts))
        elif p_type == 'Director':
            director_attrs = []
            if tmdbid: director_attrs.append(f'tmdbid="{tmdbid}"')
            if imdbid: director_attrs.append(f'imdbid="{imdbid}"')
            attr_str = " " + " ".join(director_attrs) if director_attrs else ""
            xml_parts.append(f"    <director{attr_str}>{escape(person['Name'])}</director>")
        elif p_type == 'Writer':
            xml_parts.append(f"    <writer>{escape(person['Name'])}</writer>")

    append_if_exists("rating", details.get("CommunityRating"))
    append_if_exists("year", details.get("ProductionYear"))
    append_if_exists("mpaa", details.get("OfficialRating"))

    if premiere_date_str := details.get("PremiereDate"):
        try:
            premiere_date_obj = datetime.fromisoformat(premiere_date_str.replace('Z', '+00:00'))
            append_if_exists("premiered", premiere_date_obj.strftime('%Y-%m-%d'))
            append_if_exists("releasedate", premiere_date_obj.strftime('%Y-%m-%d'))
        except (ValueError, TypeError): pass
    
    append_if_exists("tagline", first_tagline)

    provider_ids = details.get('ProviderIds', {}) or {}
    imdb_id = next((v for k, v in provider_ids.items() if k.lower() == 'imdb'), None)
    tmdb_id = next((v for k, v in provider_ids.items() if k.lower() == 'tmdb'), None)
    douban_id = next((v for k, v in provider_ids.items() if k.lower() == 'douban'), None)

    if imdb_id:
        append_if_exists("id", imdb_id)
        xml_parts.append(f'    <uniqueid type="imdb">{imdb_id}</uniqueid>')
    if tmdb_id:
        xml_parts.append(f'    <uniqueid type="tmdb">{tmdb_id}</uniqueid>')
    if douban_id:
        xml_parts.append(f'    <uniqueid type="douban">{douban_id}</uniqueid>')
        append_if_exists("doubanid", douban_id)

    for genre in (details.get('Genres', []) or []):
        append_if_exists("genre", genre)
    for country in (details.get('ProductionLocations', []) or []):
        append_if_exists("country", country)

    if collection_info := details.get('CollectionInfo'):
        if collection_info.get("tmdbcolid") and collection_info.get("name"):
            set_parts = [f'    <set tmdbcolid="{collection_info["tmdbcolid"]}">']
            set_parts.append(f'        <name>{escape(collection_info["name"])}</name>')
            set_parts.append('    </set>')
            xml_parts.append('\n'.join(set_parts))

    xml_parts.append(f'</{root_tag}>')
    return '\n'.join(xml_parts)


class EmbyDownloader:
    def __init__(self, app_config: AppConfig, task_category: str = "媒体下载"):
        self.server_config = app_config.server_config
        self.download_config = app_config.download_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.session = requests.Session()
        self.task_category = task_category


    def _get_item_details(self, item_id: str, fields: str) -> Optional[Dict[str, Any]]:
        """获取媒体项的基础信息"""
        url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
        params = {**self.params, "Fields": fields}
        try:
            response = self.session.get(url, params=params, timeout=20)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            # --- 日志修改 ---
            ui_logger.error(f"❌ 获取媒体项(ID:{item_id})信息失败: {e}", task_category=self.task_category)
            return None


    def _get_full_item_details(self, item_id: str) -> Optional[Dict[str, Any]]:
        """获取一个媒体项的所有需要用于生成NFO的详细信息"""
        # --- 日志修改 ---
        ui_logger.debug(f"➡️ 正在获取媒体项 (ID: {item_id}) 的完整详情...", task_category=self.task_category)
        
        fields = "ProviderIds,People,Genres,Overview,OriginalTitle,SortName,DateCreated,ProductionYear,CommunityRating,Path,OfficialRating,PremiereDate,Taglines,ProductionLocations"
        details = self._get_item_details(item_id, fields)
        if not details:
            ui_logger.error(f"❌ 获取媒体项基础信息失败。任务中止。", task_category=self.task_category)
            return None

        if 'People' in details and details['People']:
            all_people = details.get('People', [])
            all_actors = [p for p in all_people if p and p.get('Type') == 'Actor']
            other_people = [p for p in all_people if p and p.get('Type') != 'Actor']
            
            actor_limit = self.download_config.nfo_actor_limit
            limited_actors = all_actors[:actor_limit]
            
            people_to_fetch_ids = limited_actors + other_people
            
            ui_logger.debug(f"  - 演职员总数: {len(all_people)} (演员: {len(all_actors)})。根据配置，将为 {len(people_to_fetch_ids)} 位关键演职员获取外部ID...", task_category=self.task_category)

            for person in people_to_fetch_ids:
                person_id = person.get('Id')
                if not person_id: continue
                
                person_details = self._get_item_details(person_id, "ProviderIds")
                if person_details:
                    person['ProviderIds'] = person_details.get('ProviderIds', {})
                else:
                    ui_logger.warning(f"  - ⚠️ 获取演职员(ID: {person_id})的详情失败。跳过此人。", task_category=self.task_category)
                    person['ProviderIds'] = {}
            
            details['People'] = people_to_fetch_ids

        ui_logger.debug(f"➡️ 正在查询项目 (ID: {item_id}) 所属的合集...", task_category=self.task_category)
        collections_url = f"{self.base_url}/Users/{self.user_id}/Items"
        collection_params = {
            **self.params,
            "ListItemIds": item_id,
            "IncludeItemTypes": "BoxSet",
            "Recursive": "true",
            "Fields": "ProviderIds"
        }
        try:
            c_resp = self.session.get(collections_url, params=collection_params, timeout=15)
            c_resp.raise_for_status()
            collections_summary = c_resp.json().get("Items", [])
            
            if not collections_summary:
                ui_logger.debug("  - 该项目不属于任何合集。", task_category=self.task_category)
            else:
                boxset_summary = collections_summary[0]
                collection_id = boxset_summary.get('Id')
                collection_name = boxset_summary.get('Name', '电影合集')
                
                if collection_id:
                    ui_logger.debug(f"  - 找到所属合集: '{collection_name}' (ID: {collection_id})。正在获取其ProviderIds...", task_category=self.task_category)
                    
                    collection_details = self._get_item_details(collection_id, "ProviderIds")
                    if collection_details:
                        collection_ids = collection_details.get('ProviderIds', {})
                        tmdb_col_id = next((v for k, v in collection_ids.items() if k.lower() == 'tmdb'), None)

                        if tmdb_col_id:
                            ui_logger.debug(f"  - ✅ 成功找到 TMDB 合集 ID: {tmdb_col_id}", task_category=self.task_category)
                            details['CollectionInfo'] = {"name": collection_name, "tmdbcolid": tmdb_col_id}
                        else:
                            ui_logger.warning("  - ⚠️ 未在该合集的 ProviderIds 中找到 TMDB 合集 ID。", task_category=self.task_category)
        except requests.RequestException as e:
            ui_logger.warning(f"  - ⚠️ 获取合集列表失败，将不写入合集信息: {e}", task_category=self.task_category)

        ui_logger.debug(f"➡️ 完整详情获取完毕。", task_category=self.task_category)
        return details


    def _download_file(self, url: str, save_path: str, item_name: str, content_name: str):
        if os.path.exists(save_path) and self.download_config.download_behavior == "skip":
            return "skipped"
        response = requests.get(url, params=self.params, stream=True, timeout=60)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return "success"

    def _sanitize_path(self, path: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', '_', path)

    def _get_relative_path(self, path: str) -> str:
        path = re.sub(r'^[a-zA-Z]:', '', path)
        return path.lstrip('/\\')



    def download_for_item(self, item_id: str, content_types: list[str]):
        if 'nfo' in content_types:
            details = self._get_full_item_details(item_id)
        else:
            fields_for_images = "ProviderIds,Path,Name,Type,ImageTags,BackdropImageTags"
            details = self._get_item_details(item_id, fields_for_images)

        if not details:
            ui_logger.error(f"❌ 无法获取项目 {item_id} 的信息，下载任务中止。", task_category=self.task_category)
            return {"error": "Failed to get item details"}

        item_name = details.get("Name", f"Item {item_id}")
        
        save_dir = ""
        rule = self.download_config.directory_naming_rule

        if rule == "media_path":
            ui_logger.debug(f"[{item_name}] 使用 'media_path' 规则创建目录。", task_category=self.task_category)
            media_path = details.get("Path")
            if not media_path:
                raise ValueError(f"项目 '{item_name}' (ID: {item_id}) 缺少 Path 字段，无法按媒体路径创建目录。")
            
            relative_dir = os.path.dirname(media_path) if details.get("Type") == "Movie" else media_path
            
            uncleaned_relative_path = self._get_relative_path(relative_dir)
            
            normalized_path = uncleaned_relative_path.replace('\\', '/')
            
            path_parts = normalized_path.split('/')
            
            safe_path_parts = [self._sanitize_path(part) for part in path_parts]
            
            save_dir = os.path.join(self.download_config.download_directory, *safe_path_parts)
            
        else: # tmdb_id 规则
            # --- 核心修改：增加媒体类型前缀 ---
            provider_ids = details.get("ProviderIds", {})
            tmdb_id = next((v for k, v in provider_ids.items() if k.lower() == 'tmdb'), None)
            if not tmdb_id:
                raise ValueError(f"项目 '{item_name}' (ID: {item_id}) 缺少 TMDB ID，无法创建目录。")

            item_type = details.get("Type")
            prefix = 'tv-' if item_type == 'Series' else 'movie-'
            folder_name = f"{prefix}{tmdb_id}"
            
            ui_logger.debug(f"[{item_name}] 使用 'tmdb_id' 规则创建目录，类型: {item_type}, 文件夹名: {folder_name}", task_category=self.task_category)
            save_dir = os.path.join(self.download_config.download_directory, folder_name)

        os.makedirs(save_dir, exist_ok=True)
        ui_logger.debug(f"[{item_name}] 最终文件保存目录为: {save_dir}", task_category=self.task_category)

        # --- 核心修改：日志聚合逻辑 ---
        results = {}
        log_details = []
        has_error = False

        if 'nfo' in content_types:
            try:
                nfo_content = create_nfo_from_details(details, self.download_config)
                filename = "movie.nfo" if details.get("Type") == "Movie" else "tvshow.nfo"
                save_path = os.path.join(save_dir, filename)
                if os.path.exists(save_path) and self.download_config.download_behavior == "skip":
                    results['nfo'] = 'skipped'
                    log_details.append(f"  - NFO 文件已存在，跳过。")
                else:
                    with open(save_path, 'w', encoding='utf-8') as f: f.write(nfo_content)
                    results['nfo'] = 'success'
                    log_details.append(f"  - NFO 文件创建成功: {filename}")
            except Exception as e: 
                results['nfo'] = f"Error: {e}"
                log_details.append(f"  - ❌ NFO 文件创建失败: {e}")
                has_error = True
        
        image_map = {
            "poster": ("Primary", "海报", "poster.jpg"), 
            "logo": ("Logo", "Logo", "clearlogo.png"), 
            "backdrop": ("Backdrop", "背景图", "fanart.jpg")
        }
        for content_type, (emby_type, content_name, save_filename) in image_map.items():
            if content_type not in content_types: continue
            try:
                if emby_type == "Backdrop":
                    if not details.get("BackdropImageTags"):
                        results[content_type] = 'not_found'
                        log_details.append(f"  - {content_name}不存在，跳过。")
                        continue
                    img_url = f"{self.base_url}/Items/{item_id}/Images/Backdrop/0"
                else:
                    if not details.get("ImageTags", {}).get(emby_type):
                        results[content_type] = 'not_found'
                        log_details.append(f"  - {content_name}不存在，跳过。")
                        continue
                    img_url = f"{self.base_url}/Items/{item_id}/Images/{emby_type}"
                
                save_path = os.path.join(save_dir, save_filename)
                status = self._download_file(img_url, save_path, item_name, content_name)
                results[content_type] = status
                
                if status == 'success':
                    log_details.append(f"  - {content_name}下载成功: {save_filename}")
                elif status == 'skipped':
                    log_details.append(f"  - {content_name}已存在，跳过。")

            except Exception as e: 
                results[content_type] = f"Error: {e}"
                log_details.append(f"  - ❌ {content_name}下载失败: {e}")
                has_error = True
        
        # 统一输出日志
        if log_details:
            log_icon = "⚠️" if has_error else "✅"
            log_message = f"{log_icon} [{item_name}]\n" + "\n".join(log_details)
            ui_logger.info(log_message, task_category=self.task_category)

        return results


def batch_download_task(config: AppConfig, request: BatchDownloadRequest, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
    task_cat = f"批量下载({request.mode})"
    downloader = EmbyDownloader(config, task_category=task_cat)
    server_conf = config.server_config
    all_items_to_process = []
    
    # --- 日志修改 ---
    ui_logger.info(f"🎉 批量下载任务启动，模式: {request.mode}", task_category=task_cat)

    fields_to_get = "Id,ParentId,Name"
    if request.mode == "byLibrary":
        if not request.library_ids: 
            ui_logger.error("❌ 模式 'byLibrary' 需要提供 library_ids，任务中止。", task_category=task_cat)
            return
        ui_logger.info(f"➡️ 将在媒体库 {request.library_ids} 中下载所有电影和电视剧", task_category=task_cat)
        for lib_id in request.library_ids:
            url = f"{server_conf.server}/Items"
            params = {"api_key": server_conf.api_key, "UserId": server_conf.user_id, "Recursive": "true", "ParentId": lib_id, "IncludeItemTypes": "Movie,Series", "Fields": fields_to_get}
            start_index = 0
            while True:
                if cancellation_event.is_set(): 
                    ui_logger.info("⚠️ 任务在获取列表阶段被取消。", task_category=task_cat)
                    return
                params["StartIndex"] = start_index
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                items_page = response.json().get("Items", [])
                if not items_page: break
                all_items_to_process.extend(items_page)
                start_index += len(items_page)
    elif request.mode == "byType":
        if not request.media_type: 
            ui_logger.error("❌ 模式 'byType' 需要提供 media_type，任务中止。", task_category=task_cat)
            return
        ui_logger.info(f"➡️ 将在所有媒体库中下载 {request.media_type} 类型", task_category=task_cat)
        url = f"{server_conf.server}/Items"
        params = {"api_key": server_conf.api_key, "UserId": server_conf.user_id, "Recursive": "true", "IncludeItemTypes": request.media_type, "Fields": fields_to_get}
        start_index = 0
        while True:
            if cancellation_event.is_set(): 
                ui_logger.info("⚠️ 任务在获取列表阶段被取消。", task_category=task_cat)
                return
            params["StartIndex"] = start_index
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            items_page = response.json().get("Items", [])
            if not items_page: break
            all_items_to_process.extend(items_page)
            start_index += len(items_page)
    elif request.mode == "all":
        ui_logger.info("➡️ 将下载所有媒体库中的 'Movie' 和 'Series' 类型", task_category=task_cat)
        url = f"{server_conf.server}/Items"
        params = {"api_key": server_conf.api_key, "UserId": server_conf.user_id, "Recursive": "true", "IncludeItemTypes": "Movie,Series", "Fields": fields_to_get}
        all_items = []
        start_index = 0
        while True:
            if cancellation_event.is_set(): 
                ui_logger.info("⚠️ 任务在获取列表阶段被取消。", task_category=task_cat)
                return
            params["StartIndex"] = start_index
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            items_page = response.json().get("Items", [])
            if not items_page: break
            all_items.extend(items_page)
            start_index += len(items_page)
        if request.blacklist:
            views_url = f"{server_conf.server}/Users/{server_conf.user_id}/Views"
            views_resp = requests.get(views_url, params={"api_key": server_conf.api_key})
            views = views_resp.json().get("Items", [])
            blacklist_names = {name.strip() for name in request.blacklist.split(',') if name.strip()}
            blacklisted_ids = {view['Id'] for view in views if view['Name'] in blacklist_names}
            ui_logger.info(f"  - 应用黑名单媒体库: {blacklist_names}, 对应ID: {blacklisted_ids}", task_category=task_cat)
            all_items_to_process = [item for item in all_items if item.get("ParentId") not in blacklisted_ids]
        else:
            all_items_to_process = all_items

    total_count = len(all_items_to_process)
    ui_logger.info(f"✅ 任务准备就绪，共需处理 {total_count} 个项目。", task_category=task_cat)
    task_manager.update_task_progress(task_id, 0, total_count)

    for i, item in enumerate(all_items_to_process):
        if cancellation_event.is_set():
            ui_logger.info(f"⚠️ 任务在处理第 {i+1} 个项目时被取消。", task_category=task_cat)
            return
        
        item_name_log = item.get('Name', f"Item {item['Id']}")
        ui_logger.debug(f"➡️ 进度 {i+1}/{total_count}: 正在处理 [{item_name_log}]", task_category=task_cat)
        
        try:
            downloader.download_for_item(item['Id'], request.content_types)
        except Exception as e:
            ui_logger.error(f"❌ 处理项目 [{item_name_log}] (ID: {item['Id']}) 时发生顶层错误: {e}", task_category=task_cat)
        
        task_manager.update_task_progress(task_id, i + 1, total_count)
    
    if not cancellation_event.is_set():
        ui_logger.info("🎉 批量下载任务正常完成。", task_category=task_cat)