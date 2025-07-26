# backend/trakt_manager.py (完整文件覆盖 - 严格遵循参考脚本逻辑)

import logging
import requests
from typing import Dict, Any, Optional, Tuple
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from models import AppConfig
from proxy_manager import ProxyManager
from log_manager import ui_logger

TRAKT_API_BASE_URL = "https://api.trakt.tv"

class TraktManager:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.trakt_config = app_config.trakt_config
        self.proxy_manager = ProxyManager(app_config)
        
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _get_headers(self) -> Dict[str, str]:
        """构建 Trakt API 请求头"""
        return {
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": self.trakt_config.client_id
        }

    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """向 Trakt API 发起请求的通用方法"""
        task_cat = "Trakt API"
        if not self.trakt_config.enabled or not self.trakt_config.client_id:
            logging.debug("【Trakt】Trakt 功能未启用或未配置 Client ID，跳过请求。")
            return None

        url = f"{TRAKT_API_BASE_URL}{endpoint}"
        proxies = self.proxy_manager.get_proxies(url)
        
        try:
            logging.debug(f"【Trakt】准备请求 Trakt API: {url}，参数: {params}")
            response = self.session.get(url, headers=self._get_headers(), params=params, timeout=20, proxies=proxies)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else "N/A"
            ui_logger.error(f"❌ [Trakt] 请求 Trakt API 失败 (状态码: {status_code})。URL: {e.request.url}, 错误: {e}", task_category=task_cat)
            return None
        except Exception as e:
            ui_logger.error(f"❌ [Trakt] 处理 Trakt API 请求时发生未知错误: {e}", task_category=task_cat, exc_info=True)
            return None

    def _get_trakt_id_from_tmdb_id(self, tmdb_id: str) -> Tuple[Optional[str], Optional[str]]:
        """第一步：通过 TMDB ID 搜索，获取 Trakt 内部 ID 和剧集标题"""
        task_cat = "Trakt API"
        ui_logger.debug(f"   - [Trakt-步骤1/3] 正在通过 TMDB ID ({tmdb_id}) 查找 Trakt 内部 ID...", task_category=task_cat)
        endpoint = f"/search/tmdb/{tmdb_id}"
        params = {"type": "show"}
        search_results = self._make_request(endpoint, params)

        if not search_results:
            ui_logger.warning(f"   - [Trakt-步骤1/3] ⚠️ 在 Trakt 中未找到 TMDB ID 为 {tmdb_id} 的剧集。", task_category=task_cat)
            return None, None

        show_info = search_results[0].get('show', {})
        show_title = show_info.get('title', '未知标题')
        trakt_id = show_info.get('ids', {}).get('trakt')

        if not trakt_id:
            ui_logger.warning(f"   - [Trakt-步骤1/3] ⚠️ 找到了剧集《{show_title}》，但它缺少 Trakt 内部 ID。", task_category=task_cat)
            return None, show_title
        
        ui_logger.debug(f"   - [Trakt-步骤1/3] ✅ 成功找到剧集《{show_title}》的 Trakt ID: {trakt_id}", task_category=task_cat)
        return str(trakt_id), show_title

    def get_show_seasons_with_episodes(self, tmdb_id: str) -> Optional[Dict[str, Any]]:
        """
        通过 TMDB ID 获取剧集【最新一季】分集的详细信息。
        采用经过验证的三步查询法。
        """
        task_cat = "Trakt API"
        ui_logger.info(f"➡️ [Trakt] 正在为 TMDB ID: {tmdb_id} 获取精确分集播出时间...", task_category=task_cat)
        
        trakt_id, show_title = self._get_trakt_id_from_tmdb_id(tmdb_id)
        if not trakt_id:
            return None

        ui_logger.debug(f"   - [Trakt-步骤2/3] 正在为《{show_title}》(Trakt ID: {trakt_id}) 获取季摘要列表...", task_category=task_cat)
        seasons_summary_endpoint = f"/shows/{trakt_id}/seasons"
        seasons_summary_data = self._make_request(seasons_summary_endpoint)
        
        if not seasons_summary_data:
            ui_logger.warning(f"   - [Trakt-步骤2/3] ⚠️ 未能获取到《{show_title}》的季摘要信息。", task_category=task_cat)
            return None

        latest_season_summary = max(
            (s for s in seasons_summary_data if s.get("number", 0) > 0),
            key=lambda x: x.get("number"),
            default=None
        )

        if not latest_season_summary:
            ui_logger.warning(f"   - [Trakt-步骤2/3] ⚠️ 在《{show_title}》中未找到有效的最新季摘要。", task_category=task_cat)
            return None
        
        latest_season_number = latest_season_summary.get("number")
        ui_logger.debug(f"   - [Trakt-步骤3/3] 已定位到最新季: 第 {latest_season_number} 季，开始获取其详细分集...", task_category=task_cat)

        season_detail_endpoint = f"/shows/{trakt_id}/seasons/{latest_season_number}"
        params = {"extended": "full"}
        episodes_in_season = self._make_request(season_detail_endpoint, params)

        if not episodes_in_season:
            ui_logger.warning(f"   - [Trakt-步骤3/3] ⚠️ 获取第 {latest_season_number} 季的详细信息失败。", task_category=task_cat)
            return None

        episodes_map = {}
        for episode in episodes_in_season:
            episode_number = episode.get("number")
            first_aired = episode.get("first_aired")
            if episode_number is not None and first_aired:
                key = f"S{latest_season_number}E{episode_number}"
                episodes_map[key] = first_aired
        
        ui_logger.info(f"✅ [Trakt] 成功为《{show_title}》的第 {latest_season_number} 季获取到 {len(episodes_map)} 条精确播出时间记录。", task_category=task_cat)
        return episodes_map