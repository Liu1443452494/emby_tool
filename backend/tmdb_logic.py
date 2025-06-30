
import logging
import requests
import time
import os
import json
from typing import Dict, List, Any, Optional, Tuple
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 核心修改：导入 ui_logger ---
from log_manager import ui_logger
from models import (
    AppConfig, TmdbImageResponse, TmdbCandidate, TmdbImage,
    ActorTmdbImageFlowRequest, ActorTmdbImageFlowResponse, TmdbPersonCandidate, SingleActorConfirmContext
)
from proxy_manager import ProxyManager

CACHE: Dict[str, Tuple[Any, float]] = {}
CACHE_DURATION = 3600

class TmdbLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.emby_config = app_config.server_config
        self.tmdb_config = app_config.tmdb_config
        if not self.tmdb_config.api_key:
            raise ValueError("TMDB API Key 未配置。")
        self.tmdb_api_key = self.tmdb_config.api_key
        
        if self.tmdb_config.custom_api_domain_enabled and self.tmdb_config.custom_api_domain:
            self.tmdb_base_url = self.tmdb_config.custom_api_domain.rstrip('/') + "/3"
            # 底层日志，使用 logging
            logging.info(f"【TMDB逻辑】使用自定义API域名: {self.tmdb_base_url}")
        else:
            self.tmdb_base_url = "https://api.themoviedb.org/3"
            logging.info(f"【TMDB逻辑】使用默认API域名: {self.tmdb_base_url}")

        self.session = requests.Session()
        
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        self.proxy_manager = ProxyManager(app_config)

    def _get_from_cache(self, key: str) -> Optional[Any]:
        if key in CACHE:
            data, timestamp = CACHE[key]
            if time.time() - timestamp < CACHE_DURATION:
                logging.debug(f"【TMDB缓存】命中缓存: {key}")
                return data
            else:
                logging.debug(f"【TMDB缓存】缓存已过期: {key}")
        return None

    def _set_to_cache(self, key: str, data: Any):
        logging.debug(f"【TMDB缓存】设置缓存: {key}")
        CACHE[key] = (data, time.time())

    def _tmdb_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        full_params = {"api_key": self.tmdb_api_key, "language": "zh-CN", **(params or {})}
        cache_key = f"{endpoint}?{frozenset(full_params.items())}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data: return cached_data
        url = f"{self.tmdb_base_url}/{endpoint}"
        logging.debug(f"【TMDB请求】向 TMDB 发起请求: {url}，参数: {params}")
        proxies = self.proxy_manager.get_proxies(url)
        response = self.session.get(url, params=full_params, timeout=20, proxies=proxies)
        response.raise_for_status()
        data = response.json()
        self._set_to_cache(cache_key, data)
        return data

    def _get_emby_item_details(self, item_id: str, fields: str = "ProviderIds,People,ProductionYear") -> Dict:
        cache_key = f"emby_item_{item_id}_{fields}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            logging.debug(f"【TMDB逻辑】命中请求级缓存，直接返回 Emby 项目 (ID: {item_id}) 的信息。")
            return cached_data

        logging.debug(f"【TMDB逻辑】正在从 Emby 获取项目 (ID: {item_id}) 的详细信息，请求字段: {fields}...")
        url = f"{self.emby_config.server}/Users/{self.emby_config.user_id}/Items/{item_id}"
        params = {"api_key": self.emby_config.api_key, "Fields": fields}
        proxies = self.proxy_manager.get_proxies(url)
        response = self.session.get(url, params=params, timeout=15, proxies=proxies)
        response.raise_for_status()
        data = response.json()
        logging.debug(f"【TMDB逻辑】成功获取 Emby 项目 (ID: {item_id}) 的信息。")
        
        self._set_to_cache(cache_key, data)
        return data

    def _smart_match(self, item_details: Dict) -> TmdbImageResponse:
        task_cat = f"TMDB智能匹配({item_details.get('Name')})"
        item_type = "tv" if item_details.get("Type") == "Series" else "movie"
        title = item_details.get("Name")
        year = item_details.get("ProductionYear")
        if year:
            ui_logger.info(f"开始为 '{title}' ({year}) 进行智能匹配...", task_category=task_cat)
            search_params = {"query": title, "year": year, "include_adult": False}
        else:
            ui_logger.warning(f"媒体项 '{title}' 缺少年份信息，将进行无年份搜索。", task_category=task_cat)
            search_params = {"query": title, "include_adult": False}
        search_results = self._tmdb_request(f"search/{item_type}", search_params).get("results", [])
        if not search_results:
            ui_logger.warning(f"'{title}' 在TMDB中未搜索到任何结果。", task_category=task_cat)
            return TmdbImageResponse(status="not_found", message="在TMDB中未搜索到任何结果。")
        processed_results = []
        for res in search_results:
            if 'name' in res: res['title'] = res.pop('name')
            if 'first_air_date' in res: res['release_date'] = res.pop('first_air_date')
            if 'title' not in res:
                logging.warning(f"【TMDB调试】跳过一个缺少 title/name 字段的结果: {res.get('id')}")
                continue
            processed_results.append(res)
        if year:
            candidates = [r for r in processed_results if r.get('release_date') and abs(int(r['release_date'].split('-')[0] or 0) - year) <= 1]
        else:
            candidates = processed_results
        if not candidates:
            ui_logger.warning(f"'{title}' 年份过滤后无匹配结果。", task_category=task_cat)
            return TmdbImageResponse(status="not_found", message="在TMDB中未找到年份匹配的结果。")
        if len(candidates) == 1 and year:
            return TmdbImageResponse(status="single_candidate_confirm", candidates=[TmdbCandidate(**candidates[0])])
        else:
            return TmdbImageResponse(status="manual_selection", candidates=[TmdbCandidate(**c) for c in candidates[:10]])

    def _fetch_and_sort_images(self, tmdb_id: int, item_type: str, image_type: str) -> List[TmdbImage]:
        task_cat = f"TMDB图片获取({tmdb_id})"
        ui_logger.info(f"正在为 TMDB ID: {tmdb_id} 获取 {image_type} 图片...", task_category=task_cat)
        details = self._tmdb_request(f"{item_type}/{tmdb_id}")
        original_language = details.get("original_language")
        images_endpoint = f"{item_type}/{tmdb_id}/images"
        all_images_params = {"api_key": self.tmdb_api_key}
        cache_key = f"{images_endpoint}?{frozenset(all_images_params.items())}"
        all_images_data = self._get_from_cache(cache_key)
        if not all_images_data:
            url = f"{self.tmdb_base_url}/{images_endpoint}"
            proxies = self.proxy_manager.get_proxies(url)
            response = self.session.get(url, params=all_images_params, timeout=20, proxies=proxies)
            response.raise_for_status()
            all_images_data = response.json()
            self._set_to_cache(cache_key, all_images_data)
        target_images_key = f"{image_type}s"
        if image_type == 'poster': target_images_key = 'posters'
        elif image_type == 'backdrop': target_images_key = 'backdrops'
        elif image_type == 'logo': target_images_key = 'logos'
        target_images = all_images_data.get(target_images_key, [])
        MIN_POSTER_WIDTH, MIN_BACKDROP_WIDTH = 500, 1280
        if image_type == 'poster': target_images = [img for img in target_images if img.get('width', 0) >= MIN_POSTER_WIDTH]
        elif image_type == 'backdrop': target_images = [img for img in target_images if img.get('width', 0) >= MIN_BACKDROP_WIDTH]
        lang_buckets = {"zh": [], "orig": [], "null": [], "other": []}
        for img in target_images:
            lang = img.get("iso_639_1")
            if lang == "zh": lang_buckets["zh"].append(img)
            elif lang == original_language: lang_buckets["orig"].append(img)
            elif lang is None or lang == "xx": lang_buckets["null"].append(img)
            else: lang_buckets["other"].append(img)
        for key in lang_buckets: lang_buckets[key].sort(key=lambda x: x.get("vote_average", 0), reverse=True)
        sorted_list = lang_buckets["zh"] + lang_buckets["orig"] + lang_buckets["null"] + lang_buckets["other"]
        return [TmdbImage(**img) for img in sorted_list]

    def get_tmdb_id_flow(self, item_id: str, item_details: Optional[Dict] = None) -> Tuple[Optional[int], Optional[TmdbImageResponse]]:
        if not item_details:
            item_details = self._get_emby_item_details(item_id)
        
        provider_ids = item_details.get("ProviderIds", {})
        provider_tmdb_id = next((v for k, v in provider_ids.items() if k.lower() == 'tmdb'), None)

        if provider_tmdb_id:
            return int(provider_tmdb_id), None
        return None, self._smart_match(item_details)

    def update_ids_task(self, item_id: str, tmdb_id: int):
        task_cat = f"ID关联-影视({item_id})"
        ui_logger.info(f"开始为 Emby 影视更新 TMDB ID 为 {tmdb_id}", task_category=task_cat)
        try:
            item_details = self._get_emby_item_details(item_id)
            item_details.setdefault("ProviderIds", {})["Tmdb"] = str(tmdb_id)
            url = f"{self.emby_config.server}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            params = {"api_key": self.emby_config.api_key}
            proxies = self.proxy_manager.get_proxies(url)
            response = self.session.post(url, params=params, headers=headers, json=item_details, timeout=20, proxies=proxies)
            response.raise_for_status()
            ui_logger.info(f"成功更新 Emby ProviderIds。", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"更新 Emby ProviderIds 失败: {e}", task_category=task_cat)

    def update_person_ids_task(self, person_id: str, tmdb_person_id: int):
        task_cat = f"ID关联-演员({person_id})"
        ui_logger.info(f"开始为 Emby 演员更新 TMDB ID 为 {tmdb_person_id}", task_category=task_cat)
        try:
            person_details = self._get_emby_item_details(person_id, fields="ProviderIds")
            
            provider_ids = person_details.get("ProviderIds", {})
            provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
            existing_id = provider_ids_lower.get('tmdb') or provider_ids_lower.get('moviedb id')

            if str(existing_id) == str(tmdb_person_id):
                ui_logger.info(f"演员的 TMDB ID 已是 {tmdb_person_id}，无需更新。", task_category=task_cat)
                return

            person_details.setdefault("ProviderIds", {})["Tmdb"] = str(tmdb_person_id)
            
            url = f"{self.emby_config.server}/Items/{person_id}"
            headers = {'Content-Type': 'application/json'}
            params = {"api_key": self.emby_config.api_key}
            proxies = self.proxy_manager.get_proxies(url)
            
            response = self.session.post(url, params=params, headers=headers, json=person_details, timeout=20, proxies=proxies)
            response.raise_for_status()
            ui_logger.info(f"成功将演员的 TMDB ID 更新为 {tmdb_person_id}。", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"更新 Emby ProviderIds 失败: {e}", task_category=task_cat)

    def _get_person_from_emby(self, person_id: str) -> Dict:
        return self._get_emby_item_details(person_id, fields="ProviderIds")

    def _get_tmdb_person_id_from_context(self, media_tmdb_id: int, person_name: str, media_details: Dict) -> Tuple[Optional[Any], Optional[Dict]]:
        item_type = "tv" if media_details.get("Type") == "Series" else "movie"
        credits = self._tmdb_request(f"{item_type}/{media_tmdb_id}/credits")
        all_cast = credits.get('cast', [])
        matched_person = next((p for p in all_cast if p.get('name') == person_name), None)
        if matched_person:
            tmdb_media_info = self._tmdb_request(f"{item_type}/{media_tmdb_id}")
            return matched_person, tmdb_media_info
        logging.warning(f"【演员匹配-上下文】在作品(TMDB ID: {media_tmdb_id})的演职员表中未找到名为'{person_name}'的演员。将返回完整演职员列表供用户选择。")
        return all_cast, None

    def _search_person_globally(self, person_name: str) -> ActorTmdbImageFlowResponse:
        task_cat = f"TMDB演员搜索({person_name})"
        ui_logger.info(f"开始全局搜索演员...", task_category=task_cat)
        search_results = self._tmdb_request("search/person", {"query": person_name}).get("results", [])
        if not search_results:
            ui_logger.warning(f"全局搜索未找到任何名为'{person_name}'的演员。", task_category=task_cat)
            return ActorTmdbImageFlowResponse(status="not_found", message="未找到匹配的演员。")
        candidates = []
        for p in search_results:
            known_for_titles = [item.get('title') or item.get('name') for item in p.get('known_for', [])]
            candidates.append(TmdbPersonCandidate(id=p['id'], name=p['name'], profile_path=p.get('profile_path'), known_for_department=p.get('known_for_department'), known_for_titles=list(filter(None, known_for_titles))))
        return ActorTmdbImageFlowResponse(status="manual_actor_selection", candidates=candidates)

    def _fetch_person_images(self, person_id: int) -> List[TmdbImage]:
        task_cat = f"TMDB头像获取({person_id})"
        ui_logger.info(f"正在为演员获取头像列表...", task_category=task_cat)
        images_data = self._tmdb_request(f"person/{person_id}/images")
        profiles = images_data.get('profiles', [])
        profiles.sort(key=lambda x: x.get('vote_average', 0), reverse=True)
        return [TmdbImage(**img) for img in profiles]

    def get_actor_images_flow(self, req: ActorTmdbImageFlowRequest, background_tasks: Any) -> ActorTmdbImageFlowResponse:
        task_cat = f"TMDB演员流程({req.emby_person_name})"
        ui_logger.info(f"流程启动，请求: {req.model_dump_json(exclude_none=True, exclude_defaults=True)}", task_category=task_cat)

        if req.confirmed_tmdb_person_id:
            ui_logger.info(f"检测到已确认的TMDB演员ID: {req.confirmed_tmdb_person_id}，直接处理。", task_category=task_cat)
            background_tasks.add_task(self.update_person_ids_task, req.emby_person_id, req.confirmed_tmdb_person_id)
            images = self._fetch_person_images(req.confirmed_tmdb_person_id)
            person_details = self._tmdb_request(f"person/{req.confirmed_tmdb_person_id}")
            context = SingleActorConfirmContext(media={}, person={"name": person_details.get("name")})
            return ActorTmdbImageFlowResponse(status="success", images=images, context=context)

        if req.force_manual_search:
            ui_logger.info("接收到强制全局搜索指令，跳过所有自动匹配步骤。", task_category=task_cat)
            return self._search_person_globally(req.emby_person_name)

        ui_logger.info(f"步骤A: 检查演员(ID: {req.emby_person_id})自身的ProviderIds...", task_category=task_cat)
        emby_person_details = self._get_person_from_emby(req.emby_person_id)
        provider_ids = emby_person_details.get("ProviderIds", {})
        provider_ids_lower = {k.lower().replace(" ", ""): v for k, v in provider_ids.items()}
        possible_keys = ['tmdb', 'moviedbid']
        person_tmdb_id = next((provider_ids_lower[key] for key in possible_keys if key in provider_ids_lower), None)
        
        if person_tmdb_id:
            ui_logger.info(f"步骤A: 命中！找到TMDB演员ID: {person_tmdb_id}。", task_category=task_cat)
            images = self._fetch_person_images(int(person_tmdb_id))
            person_details = self._tmdb_request(f"person/{person_tmdb_id}")
            context = SingleActorConfirmContext(media={}, person={"name": person_details.get("name")})
            return ActorTmdbImageFlowResponse(status="success", images=images, context=context)
        
        ui_logger.info("步骤A: 演员自身无TMDB ID。", task_category=task_cat)

        ui_logger.info(f"步骤B: 尝试通过作品(ID: {req.emby_media_item_id})上下文匹配演员 '{req.emby_person_name}'...", task_category=task_cat)
        media_details = self._get_emby_item_details(req.emby_media_item_id)
        media_tmdb_id, match_response = self.get_tmdb_id_flow(req.emby_media_item_id, item_details=media_details)
        
        if not media_tmdb_id:
            ui_logger.warning(f"步骤B: 无法确定作品的TMDB ID，上下文匹配失败。", task_category=task_cat)
        else:
            if req.force_context_list:
                ui_logger.info("接收到强制上下文列表指令。", task_category=task_cat)
                item_type = "tv" if media_details.get("Type") == "Series" else "movie"
                credits = self._tmdb_request(f"{item_type}/{media_tmdb_id}/credits")
                all_cast = credits.get('cast', [])
                candidates = [TmdbPersonCandidate(id=p['id'], name=p['name'], profile_path=p.get('profile_path'), known_for_department=p.get('known_for_department', 'Acting'), known_for_titles=[p.get('character', '')]) for p in all_cast]
                return ActorTmdbImageFlowResponse(status="context_manual_selection", candidates=candidates)

            context_result, media_info = self._get_tmdb_person_id_from_context(media_tmdb_id, req.emby_person_name, media_details)
            
            if media_info:
                ui_logger.info(f"步骤B: 上下文精确匹配成功，需要用户确认。", task_category=task_cat)
                context = SingleActorConfirmContext(media={"title": media_info.get('title') or media_info.get('name'), "year": (media_info.get('release_date') or media_info.get('first_air_date', '----')).split('-')[0], "poster_path": media_info.get('poster_path')}, person={"id": context_result['id'], "name": context_result['name'], "character": context_result.get('character', 'N/A'), "profile_path": context_result.get('profile_path')})
                return ActorTmdbImageFlowResponse(status="single_actor_confirm", context=context)
            if isinstance(context_result, list):
                ui_logger.info(f"步骤B: 上下文匹配需要用户从列表中手动选择。", task_category=task_cat)
                candidates = [TmdbPersonCandidate(id=p['id'], name=p['name'], profile_path=p.get('profile_path'), known_for_department=p.get('known_for_department', 'Acting'), known_for_titles=[p.get('character', '')]) for p in context_result]
                return ActorTmdbImageFlowResponse(status="context_manual_selection", candidates=candidates)
        
        ui_logger.info("步骤C: 降级为全局搜索。", task_category=task_cat)
        return self._search_person_globally(req.emby_person_name)
    
    def get_episode_details(self, series_tmdb_id: int, season_number: int, episode_number: int) -> Optional[Dict]:
        """
        获取单个分集的TMDB详细信息。
        """
        try:
            endpoint = f"tv/{series_tmdb_id}/season/{season_number}/episode/{episode_number}"
            details = self._tmdb_request(endpoint)
            return details
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                logging.warning(f"【TMDB】未找到分集: TV ID {series_tmdb_id}, S{season_number}E{episode_number}")
                return None
            raise e
        except Exception as e:
            logging.error(f"【TMDB】获取分集详情时出错: {e}")
            return None
        
    def get_season_details(self, series_tmdb_id: int, season_number: int) -> Optional[Dict]:
        """
        获取整季的TMDB详细信息，包含所有分集列表。
        """
        try:
            endpoint = f"tv/{series_tmdb_id}/season/{season_number}"
            details = self._tmdb_request(endpoint)
            return details
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                logging.warning(f"【TMDB】未找到剧季: TV ID {series_tmdb_id}, Season {season_number}")
                return None
            raise e
        except Exception as e:
            logging.error(f"【TMDB】获取剧季详情时出错: {e}")
            return None