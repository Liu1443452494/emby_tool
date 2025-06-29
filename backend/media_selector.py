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

  # backend/media_selector.py (修改 get_item_ids 方法)

    def get_item_ids(self, scope: ScheduledTasksTargetScope, target_collection_type: Optional[str] = None) -> List[str]:
        """
        根据范围配置获取媒体ID列表
        - 新增 target_collection_type 参数用于预过滤媒体库类型
        """
        logging.info(f"【媒体选择器】开始根据范围 '{scope.mode}' 获取媒体ID...")
        if target_collection_type:
            logging.info(f"  - 任务目标类型: {target_collection_type}")

        if scope.mode == 'latest':
            # 'latest' 模式不受影响，因为它直接查询最新的项目，不区分库
            logging.info(f"  - 模式: 最新入库 (最近 {scope.days} 天, 最多 {scope.limit} 条)")
            item_types_to_fetch = "Movie,Series,Episode" 
            logging.info(f"  - 正在请求的媒体类型: {item_types_to_fetch}")
            all_latest = self._get_latest_items(item_types_to_fetch, 500)
            logging.info(f"  - 从 Emby API 获取到 {len(all_latest)} 个原始最新项目。")

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
            
            logging.info(f"  - 按日期过滤后，剩下 {len(filtered_items)} 个项目。")
            final_items = filtered_items[:scope.limit]
            item_ids = [item['Id'] for item in final_items]
            logging.info(f"【媒体选择器】成功获取 {len(item_ids)} 个最新入库的媒体ID。")
            return item_ids

        item_types_to_scan = "Movie,Series"
        library_ids_to_scan = []
        
        all_views = []
        try:
            views_url = f"{self.base_url}/Users/{self.user_id}/Views"
            views_resp = self.session.get(views_url, params=self.params)
            all_views = views_resp.json().get("Items", [])
        except requests.RequestException as e:
            logging.error(f"【媒体选择器】获取媒体库列表时出错: {e}")
            return []

        if scope.mode == 'by_type':
            logging.info(f"  - 模式: 按媒体类型 ({scope.media_type})")
            if not scope.media_type: return []

            # --- 核心修改：增加任务目标与范围的兼容性检查 ---
            if target_collection_type == 'tvshows' and scope.media_type == 'Movie':
                logging.warning(f"【媒体选择器】任务目标是电视剧库 (tvshows)，但范围选择了仅电影 (Movie)，范围不匹配，返回空列表。")
                return []
            if target_collection_type == 'movies' and scope.media_type == 'Series':
                logging.warning(f"【媒体选择器】任务目标是电影库 (movies)，但范围选择了仅剧集 (Series)，范围不匹配，返回空列表。")
                return []
            # --- 结束修改 ---

            item_types_to_scan = scope.media_type
            library_ids_to_scan.append(None) # 代表扫描所有库
        
        elif scope.mode == 'by_library':
            logging.info(f"  - 模式: 按媒体库 (IDs: {scope.library_ids})")
            if not scope.library_ids: return []
            selected_views = [v for v in all_views if v['Id'] in scope.library_ids]
            if target_collection_type:
                selected_views = [v for v in selected_views if v.get("CollectionType") == target_collection_type]
                logging.info(f"  - 已过滤，仅保留类型为 '{target_collection_type}' 的媒体库。")
            library_ids_to_scan.extend([v['Id'] for v in selected_views])

        elif scope.mode == 'all':
            logging.info("  - 模式: 所有媒体库")
            if scope.library_blacklist:
                blacklist_names = {name.strip() for name in scope.library_blacklist.split(',') if name.strip()}
                all_views = [v for v in all_views if v['Name'] not in blacklist_names]
                logging.info(f"  - 已应用黑名单，排除: {blacklist_names}")
            if target_collection_type:
                all_views = [v for v in all_views if v.get("CollectionType") == target_collection_type]
                logging.info(f"  - 已应用目标类型过滤，仅保留类型为 '{target_collection_type}' 的媒体库。")
            library_ids_to_scan.extend([v['Id'] for v in all_views])

        all_items = []
        for p_id in library_ids_to_scan:
            url = f"{self.base_url}/Items"
            params = {**self.params, "Recursive": "true", "IncludeItemTypes": item_types_to_scan, "Fields": "Id"}
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

        item_ids = [item['Id'] for item in all_items]
        logging.info(f"【媒体选择器】成功获取 {len(item_ids)} 个媒体ID。")
        return item_ids