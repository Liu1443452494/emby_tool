# backend/emby_downloader.py (修改后)

import os
import requests
import json
import logging
import threading
import re # --- 新增：导入 re 模块 ---
from datetime import datetime
from xml.sax.saxutils import escape
from models import AppConfig, BatchDownloadRequest
from task_manager import TaskManager

# --- NFO 生成逻辑 (保持不变) ---
def create_nfo_from_details(details: dict) -> str:
    item_type = details.get("Type", "Movie")
    root_tag = "movie" if item_type == "Movie" else "tvshow"
    xml_parts = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>', f'<{root_tag}>']
    plot = details.get('Overview', '')
    if plot:
        xml_parts.append(f"    <plot><![CDATA[{plot}]]></plot>")
        xml_parts.append(f"    <outline><![CDATA[{plot}]]></outline>")
    xml_parts.append("    <lockdata>false</lockdata>")
    try:
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
        if p_type == 'Actor':
            actor_parts = ["    <actor>", f"        <name>{escape(person['Name'])}</name>", f"        <role>{escape(person.get('Role', ''))}</role>", "        <type>Actor</type>"]
            if person.get('ProviderIds', {}).get('Tmdb'): actor_parts.append(f"        <tmdbid>{person['ProviderIds']['Tmdb']}</tmdbid>")
            actor_parts.append("    </actor>")
            xml_parts.append('\n'.join(actor_parts))
        elif p_type == 'Director':
            xml_parts.append(f"    <director>{escape(person['Name'])}</director>")
        elif p_type == 'Writer':
            xml_parts.append(f"    <writer>{escape(person['Name'])}</writer>")
    if details.get('CommunityRating'): xml_parts.append(f"    <rating>{details['CommunityRating']}</rating>")
    if details.get('ProductionYear'): xml_parts.append(f"    <year>{details['ProductionYear']}</year>")
    provider_ids = details.get('ProviderIds', {})
    if provider_ids.get('Imdb'): xml_parts.append(f'    <uniqueid type="imdb">{provider_ids["Imdb"]}</uniqueid>')
    if provider_ids.get('Tmdb'): xml_parts.append(f'    <uniqueid type="tmdb">{provider_ids["Tmdb"]}</uniqueid>')
    for genre in details.get('Genres', []): xml_parts.append(f"    <genre>{escape(genre)}</genre>")
    xml_parts.append(f'</{root_tag}>')
    return '\n'.join(xml_parts)

# --- 核心下载器类 (修改) ---
class EmbyDownloader:
    def __init__(self, app_config: AppConfig):
        self.server_config = app_config.server_config
        self.download_config = app_config.download_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}

    def _get_item_details(self, item_id: str):
        # --- 修改：增加 Path 字段 ---
        url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
        fields = "ProviderIds,People,Genres,Overview,OriginalTitle,SortName,DateCreated,ProductionYear,CommunityRating,Path"
        params = {**self.params, "Fields": fields}
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def _download_file(self, url: str, save_path: str, item_name: str, content_name: str):
        if os.path.exists(save_path) and self.download_config.download_behavior == "skip":
            logging.info(f"[{item_name}] 的 {content_name} 已存在，跳过下载: {save_path}")
            return "skipped"
        response = requests.get(url, params=self.params, stream=True, timeout=60)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logging.info(f"[{item_name}] 的 {content_name} 下载成功: {save_path}")
        return "success"

    # --- 新增：路径清理和转换辅助函数 ---
    def _sanitize_path(self, path: str) -> str:
        """移除路径中的非法字符"""
        # 移除Windows和Linux/macOS的非法字符
        return re.sub(r'[<>:"/\\|?*]', '_', path)

    def _get_relative_path(self, path: str) -> str:
        """将绝对路径转换为安全的相对路径"""
        # 移除Windows盘符 (e.g., "C:")
        path = re.sub(r'^[a-zA-Z]:', '', path)
        # 移除开头的所有斜杠或反斜杠
        return path.lstrip('/\\')

    def download_for_item(self, item_id: str, content_types: list[str]):
        details = self._get_item_details(item_id)
        item_name = details.get("Name", f"Item {item_id}")
        
        logging.info(f"开始处理媒体: [{item_name}]")
        
        # --- 修改：动态确定保存目录 ---
        save_dir = ""
        rule = self.download_config.directory_naming_rule

        if rule == "media_path":
            logging.info(f"[{item_name}] 使用 'media_path' 规则创建目录。")
            media_path = details.get("Path")
            if not media_path:
                raise ValueError(f"项目 '{item_name}' (ID: {item_id}) 缺少 Path 字段，无法按媒体路径创建目录。")
            
            # 根据媒体类型处理路径
            if details.get("Type") == "Movie":
                # 对于电影，获取其父目录
                relative_dir = os.path.dirname(media_path)
            else: # Series, etc.
                # 对于剧集，路径本身就是目录
                relative_dir = media_path
            
            # 转换为安全的相对路径
            sanitized_relative_path = self._get_relative_path(relative_dir)
            # 清理路径中每一部分的非法字符
            safe_path_parts = [self._sanitize_path(part) for part in sanitized_relative_path.split(os.sep)]
            
            save_dir = os.path.join(self.download_config.download_directory, *safe_path_parts)

        else: # 默认为 tmdb_id
            logging.info(f"[{item_name}] 使用 'tmdb_id' 规则创建目录。")
            tmdb_id = details.get("ProviderIds", {}).get("Tmdb")
            if not tmdb_id:
                raise ValueError(f"项目 '{item_name}' (ID: {item_id}) 缺少 TMDB ID，无法创建目录。")
            save_dir = os.path.join(self.download_config.download_directory, tmdb_id)

        os.makedirs(save_dir, exist_ok=True)
        logging.info(f"[{item_name}] 最终文件保存目录为: {save_dir}")

        results = {}
        if 'nfo' in content_types:
            try:
                nfo_content = create_nfo_from_details(details)
                filename = "movie.nfo" if details.get("Type") == "Movie" else "tvshow.nfo"
                save_path = os.path.join(save_dir, filename)
                if os.path.exists(save_path) and self.download_config.download_behavior == "skip":
                    results['nfo'] = 'skipped'
                    logging.info(f"[{item_name}] 的 NFO 文件已存在，跳过。")
                else:
                    with open(save_path, 'w', encoding='utf-8') as f: f.write(nfo_content)
                    results['nfo'] = 'success'
                    logging.info(f"[{item_name}] 的 NFO 文件创建成功: {save_path}")
            except Exception as e: 
                results['nfo'] = f"Error: {e}"
                logging.error(f"[{item_name}] 创建NFO文件失败: {e}")
        
        image_map = {"poster": ("Primary", "海报"), "logo": ("Logo", "Logo"), "backdrop": ("Backdrop", "背景图")}
        for content_type, (emby_type, content_name) in image_map.items():
            if content_type not in content_types: continue
            try:
                if emby_type == "Backdrop":
                    if not details.get("BackdropImageTags"):
                        results[content_type] = 'not_found'
                        continue
                    img_url = f"{self.base_url}/Items/{item_id}/Images/Backdrop/0"
                else:
                    if not details.get("ImageTags", {}).get(emby_type):
                        results[content_type] = 'not_found'
                        continue
                    img_url = f"{self.base_url}/Items/{item_id}/Images/{emby_type}"
                save_path = os.path.join(save_dir, f"{content_type}.jpg")
                status = self._download_file(img_url, save_path, item_name, content_name)
                results[content_type] = status
            except Exception as e: 
                results[content_type] = f"Error: {e}"
                logging.error(f"[{item_name}] 下载 {content_name} 失败: {e}")
        return results

# --- 批量下载任务函数 (保持不变) ---
def batch_download_task(config: AppConfig, request: BatchDownloadRequest, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
    downloader = EmbyDownloader(config)
    server_conf = config.server_config
    all_items_to_process = []
    
    logging.info(f"批量下载任务启动，模式: {request.mode}")

    fields_to_get = "Id,ParentId,Name"
    if request.mode == "byLibrary":
        if not request.library_ids: logging.error("模式 'byLibrary' 需要提供 library_ids，任务中止。"); return
        logging.info(f"将在媒体库 {request.library_ids} 中下载所有电影和电视剧")
        for lib_id in request.library_ids:
            url = f"{server_conf.server}/Items"
            params = {"api_key": server_conf.api_key, "UserId": server_conf.user_id, "Recursive": "true", "ParentId": lib_id, "IncludeItemTypes": "Movie,Series", "Fields": fields_to_get}
            start_index = 0
            while True:
                if cancellation_event.is_set(): logging.info("任务在获取列表阶段被取消。"); return
                params["StartIndex"] = start_index
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                items_page = response.json().get("Items", [])
                if not items_page: break
                all_items_to_process.extend(items_page)
                start_index += len(items_page)
    elif request.mode == "byType":
        if not request.media_type: logging.error("模式 'byType' 需要提供 media_type，任务中止。"); return
        logging.info(f"将在所有媒体库中下载 {request.media_type} 类型")
        url = f"{server_conf.server}/Items"
        params = {"api_key": server_conf.api_key, "UserId": server_conf.user_id, "Recursive": "true", "IncludeItemTypes": request.media_type, "Fields": fields_to_get}
        start_index = 0
        while True:
            if cancellation_event.is_set(): logging.info("任务在获取列表阶段被取消。"); return
            params["StartIndex"] = start_index
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            items_page = response.json().get("Items", [])
            if not items_page: break
            all_items_to_process.extend(items_page)
            start_index += len(items_page)
    elif request.mode == "all":
        logging.info("将下载所有媒体库中的 'Movie' 和 'Series' 类型")
        url = f"{server_conf.server}/Items"
        params = {"api_key": server_conf.api_key, "UserId": server_conf.user_id, "Recursive": "true", "IncludeItemTypes": "Movie,Series", "Fields": fields_to_get}
        all_items = []
        start_index = 0
        while True:
            if cancellation_event.is_set(): logging.info("任务在获取列表阶段被取消。"); return
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
            logging.info(f"黑名单媒体库: {blacklist_names}, 对应ID: {blacklisted_ids}")
            all_items_to_process = [item for item in all_items if item.get("ParentId") not in blacklisted_ids]
        else:
            all_items_to_process = all_items

    total_count = len(all_items_to_process)
    logging.info(f"任务准备就绪，共需处理 {total_count} 个项目。")
    task_manager.update_task_progress(task_id, 0, total_count)

    for i, item in enumerate(all_items_to_process):
        if cancellation_event.is_set():
            logging.info(f"任务在处理第 {i+1} 个项目时被取消。")
            return
        
        item_name_log = item.get('Name', f"Item {item['Id']}")
        logging.info(f"进度 {i+1}/{total_count}: 正在处理 [{item_name_log}]")
        
        try:
            downloader.download_for_item(item['Id'], request.content_types)
        except Exception as e:
            logging.error(f"处理项目 [{item_name_log}] (ID: {item['Id']}) 时发生顶层错误: {e}")
        
        task_manager.update_task_progress(task_id, i + 1, total_count)
    
    if not cancellation_event.is_set():
        logging.info("批量下载任务正常完成。")