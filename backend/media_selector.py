import logging
import requests
from typing import List, Optional, Dict
from datetime import datetime, timedelta, timezone
import json 

from log_manager import ui_logger
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
            # 底层错误，保留 logging
            logging.error(f"【媒体选择器】获取最新项目失败: {e}")
            return []
        
    def _get_emby_item_details(self, item_id: str, fields: str) -> Dict:
        """
        从 Emby 获取媒体项的详细信息。
        这是一个通用的内部方法，可以被其他逻辑复用。
        """
        # --- 核心修改：导入 ProxyManager 并使用它 ---
        from proxy_manager import ProxyManager
        proxy_manager = ProxyManager(self.app_config)
        
        try:
            url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
            params = {**self.params, "Fields": fields}
            
            # 动态获取代理设置
            proxies = proxy_manager.get_proxies(url)
            
            response = self.session.get(url, params=params, timeout=15, proxies=proxies)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"【媒体选择器】获取媒体项 {item_id} 的详情失败: {e}")
            raise e


    def get_item_ids(self, scope: ScheduledTasksTargetScope, target_collection_type: Optional[str] = None) -> List[str]:
        """
        根据范围配置获取媒体ID列表
        - 新增 target_collection_type 参数用于预过滤媒体库类型
        """
        task_cat = "媒体选择器"
        ui_logger.info(f"开始根据范围 '{scope.mode}' 获取媒体ID...", task_category=task_cat)
        if target_collection_type:
            ui_logger.info(f"  - 任务目标类型: {target_collection_type}", task_category=task_cat)

        if scope.mode == 'by_search':
            ui_logger.info(f"  - 模式: 按搜索结果 (共 {len(scope.item_ids)} 项)", task_category=task_cat)
            return scope.item_ids
        
        if scope.mode == 'favorites':
            ui_logger.info("  - 模式: 仅收藏", task_category=task_cat)
            final_ids = set()
            
            try:
                # --- 核心修改：分类型请求，然后合并去重 ---
                
                # 1. 获取收藏的电影 (仅当任务需要电影时)
                if target_collection_type != 'tvshows':
                    movie_params = {**self.params, "Filters": "IsFavorite", "IncludeItemTypes": "Movie", "Recursive": "true", "Fields": "Id"}
                    ui_logger.debug(f"  - [调试] 正在请求收藏的电影...", task_category=task_cat)
                    movie_resp = self.session.get(f"{self.base_url}/Users/{self.user_id}/Items", params=movie_params, timeout=60).json()
                    movie_ids = {item['Id'] for item in movie_resp.get("Items", [])}
                    final_ids.update(movie_ids)
                    ui_logger.debug(f"  - [调试] 找到 {len(movie_ids)} 个收藏的电影。", task_category=task_cat)

                # 2. 获取收藏的剧集和分集 (仅当任务需要剧集时)
                if target_collection_type != 'movies':
                    # 2a. 获取整个被收藏的剧集
                    series_params = {**self.params, "Filters": "IsFavorite", "IncludeItemTypes": "Series", "Recursive": "true", "Fields": "Id"}
                    ui_logger.debug(f"  - [调试] 正在请求收藏的剧集...", task_category=task_cat)
                    series_resp = self.session.get(f"{self.base_url}/Users/{self.user_id}/Items", params=series_params, timeout=60).json()
                    series_ids = {item['Id'] for item in series_resp.get("Items", [])}
                    final_ids.update(series_ids)
                    ui_logger.debug(f"  - [调试] 找到 {len(series_ids)} 个被完整收藏的剧集。", task_category=task_cat)

                    # 2b. 获取被单独收藏的分集，并提取其所属剧集ID
                    episode_params = {**self.params, "Filters": "IsFavorite", "IncludeItemTypes": "Episode", "Recursive": "true", "Fields": "SeriesId"}
                    ui_logger.debug(f"  - [调试] 正在请求收藏的分集...", task_category=task_cat)
                    episode_resp = self.session.get(f"{self.base_url}/Users/{self.user_id}/Items", params=episode_params, timeout=60).json()
                    episode_parent_series_ids = {item['SeriesId'] for item in episode_resp.get("Items", []) if item.get('SeriesId')}
                    final_ids.update(episode_parent_series_ids)
                    ui_logger.debug(f"  - [调试] 从 {len(episode_resp.get('Items', []))} 个收藏的分集中提取出 {len(episode_parent_series_ids)} 个不重复的剧集ID。", task_category=task_cat)

                item_ids = list(final_ids)
                ui_logger.info(f"成功获取 {len(item_ids)} 个收藏的媒体ID (电影/剧集去重后)。", task_category=task_cat)
                return item_ids

            except requests.RequestException as e:
                ui_logger.error(f"获取收藏项目列表时出错: {e}", task_category=task_cat)
                return []

        if scope.mode == 'latest':
            ui_logger.info(f"  - 模式: 最新入库 (最近 {scope.days} 天, 最多 {scope.limit} 条)", task_category=task_cat)
            item_types_to_fetch = "Movie,Series,Episode" 
            ui_logger.info(f"  - 正在请求的媒体类型: {item_types_to_fetch}", task_category=task_cat)
            all_latest = self._get_latest_items(item_types_to_fetch, 500)
            ui_logger.info(f"  - 从 Emby API 获取到 {len(all_latest)} 个原始最新项目。", task_category=task_cat)

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
            
            ui_logger.info(f"  - 按日期过滤后，剩下 {len(filtered_items)} 个项目。", task_category=task_cat)
            final_items = filtered_items[:scope.limit]
            item_ids = [item['Id'] for item in final_items]
            ui_logger.info(f"成功获取 {len(item_ids)} 个最新入库的媒体ID。", task_category=task_cat)
            return item_ids

        item_types_to_scan = "Movie,Series"
        library_ids_to_scan = []
        
        all_views = []
        try:
            views_url = f"{self.base_url}/Users/{self.user_id}/Views"
            views_resp = self.session.get(views_url, params=self.params)
            all_views = views_resp.json().get("Items", [])
        except requests.RequestException as e:
            ui_logger.error(f"获取媒体库列表时出错: {e}", task_category=task_cat)
            return []

        if scope.mode == 'by_type':
            ui_logger.info(f"  - 模式: 按媒体类型 ({scope.media_type})", task_category=task_cat)
            if not scope.media_type: return []

            if target_collection_type == 'tvshows' and scope.media_type == 'Movie':
                ui_logger.warning(f"任务目标是电视剧库 (tvshows)，但范围选择了仅电影 (Movie)，范围不匹配，返回空列表。", task_category=task_cat)
                return []
            if target_collection_type == 'movies' and scope.media_type == 'Series':
                ui_logger.warning(f"任务目标是电影库 (movies)，但范围选择了仅剧集 (Series)，范围不匹配，返回空列表。", task_category=task_cat)
                return []

            item_types_to_scan = scope.media_type
            library_ids_to_scan.append(None)
        
        elif scope.mode == 'by_library':
            ui_logger.info(f"  - 模式: 按媒体库 (IDs: {scope.library_ids})", task_category=task_cat)
            if not scope.library_ids: return []
            selected_views = [v for v in all_views if v['Id'] in scope.library_ids]
            if target_collection_type:
                selected_views = [v for v in selected_views if v.get("CollectionType") == target_collection_type]
                ui_logger.info(f"  - 已过滤，仅保留类型为 '{target_collection_type}' 的媒体库。", task_category=task_cat)
            library_ids_to_scan.extend([v['Id'] for v in selected_views])

        elif scope.mode == 'all':
            ui_logger.info("  - 模式: 所有媒体库", task_category=task_cat)
            if scope.library_blacklist:
                blacklist_names = {name.strip() for name in scope.library_blacklist.split(',') if name.strip()}
                all_views = [v for v in all_views if v['Name'] not in blacklist_names]
                ui_logger.info(f"  - 已应用黑名单，排除: {blacklist_names}", task_category=task_cat)
            if target_collection_type:
                all_views = [v for v in all_views if v.get("CollectionType") == target_collection_type]
                ui_logger.info(f"  - 已应用目标类型过滤，仅保留类型为 '{target_collection_type}' 的媒体库。", task_category=task_cat)
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
                    ui_logger.error(f"获取媒体列表时出错: {e}", task_category=task_cat)
                    break

        item_ids = [item['Id'] for item in all_items]
        ui_logger.info(f"成功获取 {len(item_ids)} 个媒体ID。", task_category=task_cat)
        return item_ids