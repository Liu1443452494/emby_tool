# backend/media_selector.py (新文件)

import logging
import requests
from typing import List, Optional
from datetime import datetime, timedelta, timezone

from models import AppConfig, ScheduledTasksTargetScope

class MediaSelector:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.server_config = app_config.server_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.session = requests.Session()

    def _get_latest_items(self, item_types: str, fetch_limit: int) -> List[dict]:
        """从 Emby 获取最新入库的项目"""
        url = f"{self.base_url}/Users/{self.user_id}/Items/Latest"
        params = {
            **self.params,
            "Limit": fetch_limit,
            "IncludeItemTypes": item_types,
            "Fields": "Id,Name,DateCreated"
        }
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"【媒体选择器】获取最新项目失败: {e}")
            return []

    def get_item_ids(self, scope: ScheduledTasksTargetScope) -> List[str]:
        """根据范围配置获取媒体ID列表"""
        logging.info(f"【媒体选择器】开始根据范围 '{scope.mode}' 获取媒体ID...")

        if scope.mode == 'latest':
            # 获取最近N天，最多M条
            logging.info(f"  - 模式: 最新入库 (最近 {scope.days} 天, 最多 {scope.limit} 条)")
            
            # --- 修改：不再硬编码，而是允许所有类型，便于未来扩展 ---
            # 虽然当前UI没地方选，但这样更健壮
            item_types_to_fetch = "Movie,Series,Episode" 
            logging.info(f"  - 正在请求的媒体类型: {item_types_to_fetch}")
            # --- 结束修改 ---

            # 请求500条作为基数进行过滤
            all_latest = self._get_latest_items(item_types_to_fetch, 500)
            
            # --- 新增日志 ---
            logging.info(f"  - 从 Emby API 获取到 {len(all_latest)} 个原始最新项目。")
            # --- 结束新增 ---

            filtered_items = []
            now = datetime.now(timezone.utc)
            cutoff_date = now - timedelta(days=scope.days)
            
            for item in all_latest:
                date_created_str = item.get("DateCreated")
                if not date_created_str: continue
                try:
                    date_created = datetime.fromisoformat(date_created_str.replace('Z', '+00:00'))
                    
                    if date_created >= cutoff_date:
                        filtered_items.append(item)
                    else:
                        break
                except ValueError:
                    continue
            
            # --- 新增日志 ---
            logging.info(f"  - 按日期过滤后，剩下 {len(filtered_items)} 个项目。")
            # --- 结束新增 ---

            # 应用最终数量限制
            final_items = filtered_items[:scope.limit]
            item_ids = [item['Id'] for item in final_items]
            logging.info(f"【媒体选择器】成功获取 {len(item_ids)} 个最新入库的媒体ID。")
            return item_ids

        # --- 处理全库、按类型、按媒体库的逻辑 (这部分可以从 genre_logic.py 借鉴和改造) ---
        
        item_types_to_scan = "Movie,Series"
        parent_ids_to_scan = []
        
        if scope.mode == 'by_type':
            logging.info(f"  - 模式: 按媒体类型 ({scope.media_type})")
            if not scope.media_type: return []
            item_types_to_scan = scope.media_type
            parent_ids_to_scan.append(None) # 代表扫描所有库
        elif scope.mode == 'by_library':
            logging.info(f"  - 模式: 按媒体库 (IDs: {scope.library_ids})")
            if not scope.library_ids: return []
            parent_ids_to_scan.extend(scope.library_ids)
        elif scope.mode == 'all':
            logging.info("  - 模式: 所有媒体库")
            parent_ids_to_scan.append(None) # 代表扫描所有库

        all_items = []
        for p_id in parent_ids_to_scan:
            url = f"{self.base_url}/Items"
            params = {**self.params, "Recursive": "true", "IncludeItemTypes": item_types_to_scan, "Fields": "Id,ParentId"}
            if p_id:
                params["ParentId"] = p_id
            
            start_index = 0
            while True:
                params["StartIndex"] = start_index
                try:
                    response = self.session.get(url, params=params, timeout=60)
                    response.raise_for_status()
                    page_items = response.json().get("Items", [])
                    if not page_items: break
                    all_items.extend(page_items)
                    start_index += len(page_items)
                except requests.RequestException as e:
                    logging.error(f"【媒体选择器】获取媒体列表时出错: {e}")
                    break
        
        # 应用黑名单
        if scope.mode == 'all' and scope.library_blacklist:
            views_url = f"{self.base_url}/Users/{self.user_id}/Views"
            try:
                views_resp = self.session.get(views_url, params=self.params)
                views = views_resp.json().get("Items", [])
                blacklist_names = {name.strip() for name in scope.library_blacklist.split(',') if name.strip()}
                blacklisted_ids = {view['Id'] for view in views if view['Name'] in blacklist_names}
                all_items = [item for item in all_items if item.get("ParentId") not in blacklisted_ids]
            except requests.RequestException as e:
                logging.error(f"【媒体选择器】获取媒体库黑名单时出错: {e}")

        item_ids = [item['Id'] for item in all_items]
        logging.info(f"【媒体选择器】成功获取 {len(item_ids)} 个媒体ID。")
        return item_ids