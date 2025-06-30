
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

# --- 核心修改：导入 ui_logger ---
from log_manager import ui_logger
from models import AppConfig, ScheduledTasksTargetScope
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
            # 底层错误，保留 logging
            logging.error(f"【豆瓣修复器】获取 Emby 媒体详情 (ID: {item_id}) 失败: {e}")
            return None

    def _update_emby_item_douban_id(self, item_id: str, douban_id: str, task_cat: str) -> bool:
        try:
            item_details = self._get_emby_item_details(item_id)
            if not item_details:
                return False
            
            if "ProviderIds" not in item_details:
                item_details["ProviderIds"] = {}
            
            original_id = item_details["ProviderIds"].get("Douban")
            item_name = item_details.get('Name', '未知媒体')
            if original_id == douban_id:
                ui_logger.info(f"媒体【{item_name}】的豆瓣ID已是 {douban_id}，无需更新。", task_category=task_cat)
                return True

            item_details["ProviderIds"]["Douban"] = douban_id
            
            update_url = f"{self.base_url}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            response = self.session.post(update_url, params=self.params, json=item_details, headers=headers, timeout=20)
            response.raise_for_status()
            
            log_msg = f"旧媒体: 【{item_name}】({item_details.get('ProductionYear', 'N/A')}) ---> 新媒体: 豆瓣ID {douban_id}"
            ui_logger.info(f"更新成功！{log_msg}", task_category=task_cat)
            
            return True
        except Exception as e:
            ui_logger.error(f"更新 Emby 媒体 (ID: {item_id}) 的豆瓣ID时失败: {e}", task_category=task_cat)
            return False

    def _search_douban(self, title: str, task_cat: str) -> Optional[List[Dict]]:
        try:
            time.sleep(self.fixer_config.api_cooldown)
            
            search_url = f"https://search.douban.com/movie/subject_search?search_text={quote(title)}&cat=1002"
            response = self.session.get(search_url, timeout=20)
            response.raise_for_status()

            match = re.search(r'window\.__DATA__ = (\{.*\});', response.text)
            if not match:
                ui_logger.warning(f"搜索【{title}】成功，但未在页面中找到 window.__DATA__ 数据块。", task_category=task_cat)
                return []

            data = json.loads(match.group(1))
            items = data.get('items', [])
            
            results = []
            for item in items:
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
            
            ui_logger.info(f"通过解析JSON数据成功为【{title}】找到 {len(results)} 个结果。", task_category=task_cat)
            return results
            
        except requests.RequestException as e:
            ui_logger.error(f"搜索豆瓣【{title}】失败: {e}", task_category=task_cat)
            return None
        except Exception as e:
            ui_logger.error(f"解析豆瓣搜索页面或JSON数据失败: {e}", task_category=task_cat, exc_info=True)
            return None

    def _find_match_in_results(self, emby_item: Dict, search_results: List[Dict], task_cat: str) -> Optional[str]:
        emby_title = emby_item.get("Name", "").strip()
        emby_year = emby_item.get("ProductionYear")

        if not emby_title or not emby_year:
            return None

        for result in search_results:
            douban_title = result.get("title", "")
            douban_year = result.get("year")
            douban_id = result.get("id")

            if douban_title.startswith(emby_title) and douban_year and abs(douban_year - emby_year) <= 1:
                ui_logger.info(f"为【{emby_item.get('Name')}】找到匹配: 【{result.get('title')}】({douban_year}) -> ID: {douban_id}", task_category=task_cat)
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
            # 底层错误，保留 logging
            logging.error(f"【豆瓣修复器】保存失败缓存文件失败: {e}")

    def add_to_cache(self, item_details: Dict, task_cat: str):
        cache = self._load_cache()
        item_id = str(item_details['Id'])
        item_name = item_details.get("Name", "未知媒体")
        if item_id not in cache:
            cache[item_id] = {
                "Id": item_id,
                "Name": item_name,
                "ProductionYear": item_details.get("ProductionYear"),
                "Type": item_details.get("Type"),
                "AddedTime": datetime.now().isoformat()
            }
            self._save_cache(cache)
            ui_logger.warning(f"媒体【{item_name}】匹配失败，已添加到缓存。", task_category=task_cat)

    def remove_from_cache(self, item_id: str, task_cat: str):
        cache = self._load_cache()
        if str(item_id) in cache:
            del cache[str(item_id)]
            self._save_cache(cache)
            ui_logger.info(f"媒体项 {item_id} 已从失败缓存中移除。", task_category=task_cat)

    def _process_single_item_for_fixing(self, item_id: str, task_cat: str) -> bool:
        """处理单个媒体项的ID修复逻辑，返回是否成功修复。"""
        item_details = self._get_emby_item_details(item_id)
        if not item_details:
            ui_logger.warning(f"  -> 获取 Emby 媒体详情 (ID: {item_id}) 失败，跳过。", task_category=task_cat)
            return False
        
        item_name = item_details.get("Name", "未知名称")
        ui_logger.info(f"  -> 正在处理【{item_name}】(ID: {item_id})", task_category=task_cat)

        provider_ids = item_details.get("ProviderIds", {})
        provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
        if 'douban' in provider_ids_lower:
            ui_logger.debug(f"     -- 跳过，已存在豆瓣ID: {provider_ids_lower['douban']}", task_category=task_cat)
            return False

        search_results = self._search_douban(item_name, task_cat)
        if search_results is None:
            ui_logger.warning(f"     -- 搜索豆瓣失败，将添加到缓存。", task_category=task_cat)
            self.add_to_cache(item_details, task_cat)
            return False

        matched_douban_id = self._find_match_in_results(item_details, search_results, task_cat)
        if matched_douban_id:
            if self._update_emby_item_douban_id(item_id, matched_douban_id, task_cat):
                ui_logger.info(f"     -- 匹配并更新成功！新ID: {matched_douban_id}", task_category=task_cat)
                self.remove_from_cache(item_id, task_cat)
                return True
            else:
                ui_logger.error(f"     -- 匹配成功但更新Emby失败，将添加到缓存。", task_category=task_cat)
                self.add_to_cache(item_details, task_cat)
                return False
        else:
            ui_logger.warning(f"     -- 未找到匹配结果，将添加到缓存。", task_category=task_cat)
            self.add_to_cache(item_details, task_cat)
            return False

    def run_fixer_for_items(self, item_ids: Iterable[str], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager, task_category: str):
        """为指定的媒体ID列表执行ID修复"""
        ui_logger.info("正在清空旧的失败缓存...", task_category=task_category)
        self._save_cache({})

        item_ids_list = list(item_ids)
        total_items = len(item_ids_list)
        ui_logger.info(f"任务启动，共需处理 {total_items} 个媒体项。", task_category=task_category)
        task_manager.update_task_progress(task_id, 0, total_items)

        if total_items == 0:
            ui_logger.info("没有需要处理的媒体项，任务结束。", task_category=task_category)
            return

        fixed_count = 0
        for i, item_id in enumerate(item_ids_list):
            if cancellation_event.is_set():
                ui_logger.warning("任务被用户取消。", task_category=task_category)
                break
            
            task_manager.update_task_progress(task_id, i + 1, total_items)
            if self._process_single_item_for_fixing(item_id, task_category):
                fixed_count += 1
        
        ui_logger.info(f"任务执行完毕，共成功修复了 {fixed_count} 个项目。", task_category=task_category)
        return {"fixed_count": fixed_count}

    def scan_and_match_task(self, scan_scope: str, media_type: Optional[str], library_ids: Optional[List[str]], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """(旧的全库扫描任务，现在作为包装器)"""
        task_cat = f"豆瓣修复器({scan_scope})"
        ui_logger.info(f"开始执行扫描，范围: {scan_scope}...", task_category=task_cat)
        
        from media_selector import MediaSelector
        
        scope_config = ScheduledTasksTargetScope(
            mode='all' if scan_scope == 'all' else ('by_type' if scan_scope == 'media_type' else 'by_library'),
            media_type=media_type,
            library_ids=library_ids or []
        )

        selector = MediaSelector(self.app_config)
        item_ids_to_process = selector.get_item_ids(scope_config)

        self.run_fixer_for_items(item_ids_to_process, cancellation_event, task_id, task_manager, task_cat)