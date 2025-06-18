# backend/douban_fixer_logic.py (最终修正版)

import logging
import threading
import time
import requests
import json
import os
from typing import List, Dict, Optional, Tuple, Iterable
from urllib.parse import quote
from datetime import datetime
from bs4 import BeautifulSoup
import re

from models import AppConfig
from task_manager import TaskManager

DOUBAN_FIXER_CACHE_FILE = os.path.join('/app/data', 'douban_fix_cache.json')

class DoubanFixerLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.server_config = app_config.server_config
        self.fixer_config = app_config.douban_fixer_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.session = requests.Session()
        
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
            'Cookie': self.fixer_config.cookie
        })

    def _get_emby_item_details(self, item_id: str) -> Optional[Dict]:
        try:
            url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
            params = {**self.params, "Fields": "ProviderIds,ProductionYear,Name"}
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"【豆瓣修复器】获取 Emby 媒体详情 (ID: {item_id}) 失败: {e}")
            return None

    def _update_emby_item_douban_id(self, item_id: str, douban_id: str) -> bool:
        try:
            item_details = self._get_emby_item_details(item_id)
            if not item_details:
                return False
            
            if "ProviderIds" not in item_details:
                item_details["ProviderIds"] = {}
            
            original_id = item_details["ProviderIds"].get("Douban")
            if original_id == douban_id:
                logging.info(f"【豆瓣修复器】媒体 '{item_details['Name']}' 的豆瓣ID已是 {douban_id}，无需更新。")
                return True

            item_details["ProviderIds"]["Douban"] = douban_id
            
            update_url = f"{self.base_url}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            response = self.session.post(update_url, params=self.params, json=item_details, headers=headers, timeout=20)
            response.raise_for_status()
            
            log_msg = f"旧媒体: {item_details['Name']} ({item_details.get('ProductionYear', 'N/A')}) ---> 新媒体: 豆瓣ID {douban_id}"
            logging.info(f"【豆瓣修复器-更新成功】{log_msg}")
            
            return True
        except Exception as e:
            logging.error(f"【豆瓣修复器】更新 Emby 媒体 (ID: {item_id}) 的豆瓣ID时失败: {e}")
            return False

    # --- 关键修改：使用正则表达式提取 window.__DATA__ ---
    def _search_douban(self, title: str) -> Optional[List[Dict]]:
        try:
            time.sleep(self.fixer_config.api_cooldown)
            
            search_url = f"https://search.douban.com/movie/subject_search?search_text={quote(title)}&cat=1002"
            response = self.session.get(search_url, timeout=20)
            response.raise_for_status()

            # 使用正则表达式查找 window.__DATA__ = 后面的 JSON 对象
            match = re.search(r'window\.__DATA__ = (\{.*\});', response.text)
            if not match:
                logging.warning(f"【豆瓣修复器】搜索 '{title}' 成功，但未在页面中找到 window.__DATA__ 数据块。")
                return []

            data = json.loads(match.group(1))
            items = data.get('items', [])
            
            results = []
            for item in items:
                # 从 title 字段中提取纯标题和年份
                full_title = item.get('title', '')
                year_match = re.search(r'\((\d{4})\)$', full_title.strip())
                year = int(year_match.group(1)) if year_match else None
                clean_title = re.sub(r'\s*\(\d{4}\)$', '', full_title).strip()

                results.append({
                    "id": str(item.get('id')),
                    "title": clean_title,
                    "year": year,
                    "info": item.get('abstract', ''),
                    "poster": item.get('cover_url', '')
                })
            
            logging.info(f"【豆瓣修复器】通过解析JSON数据成功为 '{title}' 找到 {len(results)} 个结果。")
            return results
            
        except requests.RequestException as e:
            logging.error(f"【豆瓣修复器】搜索豆瓣 '{title}' 失败: {e}")
            return None
        except Exception as e:
            logging.error(f"【豆瓣修复器】解析豆瓣搜索页面或JSON数据失败: {e}", exc_info=True)
            return None

    def _find_match_in_results(self, emby_item: Dict, search_results: List[Dict]) -> Optional[str]:
        emby_title = emby_item.get("Name", "").strip()
        emby_year = emby_item.get("ProductionYear")

        if not emby_title or not emby_year:
            return None

        for result in search_results:
            douban_title = result.get("title", "")
            douban_year = result.get("year")
            douban_id = result.get("id")

            if douban_title.startswith(emby_title) and douban_year and abs(douban_year - emby_year) <= 1:
                logging.info(f"【豆瓣修复器】为 '{emby_item.get('Name')}' 找到匹配: '{result.get('title')}' ({douban_year}) -> ID: {douban_id}")
                return douban_id
        
        return None

    def _load_cache(self) -> Dict[str, Dict]:
        if not os.path.exists(DOUBAN_FIXER_CACHE_FILE):
            return {}
        try:
            with open(DOUBAN_FIXER_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError):
            return {}

    def _save_cache(self, cache_data: Dict[str, Dict]):
        try:
            with open(DOUBAN_FIXER_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=4, ensure_ascii=False)
        except IOError as e:
            logging.error(f"【豆瓣修复器】保存失败缓存文件失败: {e}")

    def add_to_cache(self, item_details: Dict):
        cache = self._load_cache()
        item_id = str(item_details['Id'])
        if item_id not in cache:
            cache[item_id] = {
                "Id": item_id,
                "Name": item_details.get("Name"),
                "ProductionYear": item_details.get("ProductionYear"),
                "Type": item_details.get("Type"),
                "AddedTime": datetime.now().isoformat()
            }
            self._save_cache(cache)
            logging.warning(f"【豆瓣修复器】媒体 '{item_details.get('Name')}' 匹配失败，已添加到缓存。")

    def remove_from_cache(self, item_id: str):
        cache = self._load_cache()
        if str(item_id) in cache:
            del cache[str(item_id)]
            self._save_cache(cache)
            logging.info(f"【豆瓣修复器】媒体项 {item_id} 已从失败缓存中移除。")

    # backend/douban_fixer_logic.py (部分修改)

    def scan_and_match_task(self, scan_scope: str, media_type: Optional[str], library_ids: Optional[List[str]], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        logging.info(f"【豆瓣修复器】开始执行扫描与匹配任务，范围: {scan_scope}...")
        
        # --- 最终修复：在任务开始时，清空上一次的失败缓存 ---
        logging.info("【豆瓣修复器】正在清空旧的失败缓存...")
        self._save_cache({})
        
        all_items = []
        task_manager.update_task_progress(task_id, 0, -1)
        
        item_types_to_scan = "Movie,Series"
        if scan_scope == "media_type" and media_type:
            item_types_to_scan = media_type
        
        parent_ids_to_scan = []
        if scan_scope == "library" and library_ids:
            parent_ids_to_scan.extend(library_ids)
        elif scan_scope in ["all", "media_type"]:
            views_url = f"{self.base_url}/Users/{self.user_id}/Views"
            try:
                views_resp = self.session.get(views_url, params=self.params, timeout=15)
                views_resp.raise_for_status()
                views = views_resp.json().get("Items", [])
                parent_ids_to_scan.extend([v['Id'] for v in views if v.get("CollectionType") in ["movies", "tvshows"]])
            except requests.RequestException as e:
                logging.error(f"【豆瓣修复器】获取媒体库列表失败: {e}")
                return

        for p_id in parent_ids_to_scan:
            if cancellation_event.is_set(): return
            
            url = f"{self.base_url}/Items"
            params = {**self.params, "Recursive": "true", "IncludeItemTypes": item_types_to_scan, "Fields": "Id,ProviderIds,Name,ProductionYear,Type", "ParentId": p_id}
            start_index = 0
            while True:
                if cancellation_event.is_set(): return
                params["StartIndex"] = start_index
                try:
                    response = self.session.get(url, params=params, timeout=60)
                    response.raise_for_status()
                    page_items = response.json().get("Items", [])
                    if not page_items: break
                    all_items.extend(page_items)
                    start_index += len(page_items)
                    task_manager.update_task_progress(task_id, len(all_items), -1)
                except requests.RequestException as e:
                    logging.error(f"【豆瓣修复器】获取媒体列表时出错: {e}")
                    break
        
        total_items = len(all_items)
        logging.info(f"【豆瓣修复器】共找到 {total_items} 个媒体项，开始筛选和处理。")
        
        def has_douban_id(item):
            provider_ids = item.get("ProviderIds", {})
            provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
            return 'douban' in provider_ids_lower

        potentially_missing_id_items = [item for item in all_items if not has_douban_id(item)]
        logging.info(f"【豆瓣修复器】粗筛后，有 {len(potentially_missing_id_items)} 个项目可能缺少豆瓣ID，开始精确检查...")

        items_to_process = []
        for item_stub in potentially_missing_id_items:
            if cancellation_event.is_set(): break
            
            item_details = self._get_emby_item_details(item_stub['Id'])
            
            if item_details and not has_douban_id(item_details):
                items_to_process.append(item_details)
        
        total_to_process = len(items_to_process)
        logging.info(f"【豆瓣修复器】精筛后，最终确认有 {total_to_process} 个项目需要处理。")

        if total_to_process > 0:
            logging.info("--- 需要处理的项目列表 开始 ---")
            for item in items_to_process:
                logging.info(f"  - ID: {item.get('Id')}, 名称: {item.get('Name')}, 年份: {item.get('ProductionYear')}")
            logging.info("--- 需要处理的项目列表 结束 ---")
        
        task_manager.update_task_progress(task_id, 0, total_to_process)

        for i, item_details in enumerate(items_to_process):
            if cancellation_event.is_set():
                logging.warning("【豆瓣修复器】任务被用户取消。")
                break
            
            task_manager.update_task_progress(task_id, i + 1, total_to_process)
            
            item_id = item_details['Id']

            search_results = self._search_douban(item_details.get("Name", ""))
            if search_results is None:
                self.add_to_cache(item_details)
                continue

            matched_douban_id = self._find_match_in_results(item_details, search_results)
            if matched_douban_id:
                if self._update_emby_item_douban_id(item_id, matched_douban_id):
                    self.remove_from_cache(item_id)
            else:
                self.add_to_cache(item_details)

        logging.info("【豆瓣修复器】扫描与匹配任务执行完毕。")



    def _process_single_item_for_fixing(self, item_id: str) -> bool:
        """处理单个媒体项的ID修复逻辑，返回是否成功修复。"""
        item_details = self._get_emby_item_details(item_id)
        if not item_details:
            logging.warning(f"  -> 获取 Emby 媒体详情 (ID: {item_id}) 失败，跳过。")
            return False
        
        item_name = item_details.get("Name", "未知名称")
        logging.info(f"  -> 正在处理: [{item_name}] (ID: {item_id})")

        provider_ids = item_details.get("ProviderIds", {})
        provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
        if 'douban' in provider_ids_lower:
            logging.info(f"     -- 跳过，已存在豆瓣ID: {provider_ids_lower['douban']}")
            return False

        search_results = self._search_douban(item_name)
        if search_results is None:
            logging.warning(f"     -- 搜索豆瓣失败，将添加到缓存。")
            self.add_to_cache(item_details)
            return False

        matched_douban_id = self._find_match_in_results(item_details, search_results)
        if matched_douban_id:
            if self._update_emby_item_douban_id(item_id, matched_douban_id):
                logging.info(f"     -- 匹配并更新成功！新ID: {matched_douban_id}")
                self.remove_from_cache(item_id)
                return True
            else:
                logging.error(f"     -- 匹配成功但更新Emby失败，将添加到缓存。")
                self.add_to_cache(item_details)
                return False
        else:
            logging.warning(f"     -- 未找到匹配结果，将添加到缓存。")
            self.add_to_cache(item_details)
            return False

    def run_fixer_for_items(self, item_ids: Iterable[str], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """为指定的媒体ID列表执行ID修复"""
        logging.info("【豆瓣修复器-任务】正在清空旧的失败缓存...")
        self._save_cache({})

        item_ids_list = list(item_ids)
        total_items = len(item_ids_list)
        logging.info(f"【豆瓣修复器-任务】启动，共需处理 {total_items} 个媒体项。")
        task_manager.update_task_progress(task_id, 0, total_items)

        if total_items == 0:
            logging.info("【豆瓣修复器-任务】没有需要处理的媒体项，任务结束。")
            return

        fixed_count = 0
        for i, item_id in enumerate(item_ids_list):
            if cancellation_event.is_set():
                logging.warning("【豆瓣修复器-任务】任务被用户取消。")
                break
            
            task_manager.update_task_progress(task_id, i + 1, total_items)
            if self._process_single_item_for_fixing(item_id):
                fixed_count += 1
        
        logging.info(f"【豆瓣修复器-任务】执行完毕，共成功修复了 {fixed_count} 个项目。")
        return {"fixed_count": fixed_count}

    def scan_and_match_task(self, scan_scope: str, media_type: Optional[str], library_ids: Optional[List[str]], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """(旧的全库扫描任务)"""
        logging.info(f"【豆瓣修复器-全库扫描】开始执行，范围: {scan_scope}...")
        
        # 使用 MediaSelector 获取 item_ids
        from media_selector import MediaSelector
        scope_config = ScheduledTasksTargetScope(
            mode='all' if scan_scope == 'all' else ('by_type' if scan_scope == 'media_type' else 'by_library'),
            media_type=media_type,
            library_ids=library_ids
        )
        selector = MediaSelector(self.app_config)
        item_ids_to_process = selector.get_item_ids(scope_config)

        self.run_fixer_for_items(item_ids_to_process, cancellation_event, task_id, task_manager)