# backend/tmdb_logic.py (修改后)
import logging
import requests
import time
import os
import json
from typing import Dict, List, Any, Optional, Tuple
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from models import (
    AppConfig, TmdbImageResponse, TmdbCandidate, TmdbImage,
    ActorTmdbImageFlowRequest, ActorTmdbImageFlowResponse, TmdbPersonCandidate, SingleActorConfirmContext
)

CACHE: Dict[str, Tuple[Any, float]] = {}
CACHE_DURATION = 3600

class TmdbLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.emby_config = app_config.server_config
        self.tmdb_config = app_config.tmdb_config
        self.proxy_config = app_config.proxy_config
        if not self.tmdb_config.api_key:
            raise ValueError("TMDB API Key 未配置。")
        self.tmdb_api_key = self.tmdb_config.api_key
        
        if self.tmdb_config.custom_api_domain_enabled and self.tmdb_config.custom_api_domain:
            self.tmdb_base_url = self.tmdb_config.custom_api_domain.rstrip('/') + "/3"
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

    def _get_proxies_for_target(self, target_url: str) -> Dict:
        config = self.proxy_config
        if not config.enabled or not config.url:
            return {}
        is_tmdb_target = "themoviedb.org" in target_url or (self.tmdb_config.custom_api_domain_enabled and self.tmdb_config.custom_api_domain in target_url)
        is_douban_target = "douban.com" in target_url or "doubanio.com" in target_url
        is_emby_target = self.emby_config.server in target_url
        should_use_proxy = False
        if config.mode == 'blacklist':
            should_use_proxy = True 
            if is_tmdb_target and config.target_tmdb: should_use_proxy = False
            if is_douban_target and config.target_douban: should_use_proxy = False
            if is_emby_target and config.target_emby: should_use_proxy = False
        elif config.mode == 'whitelist':
            should_use_proxy = False
            if is_tmdb_target and config.target_tmdb: should_use_proxy = True
            if is_douban_target and config.target_douban: should_use_proxy = True
            if is_emby_target and config.target_emby: should_use_proxy = True
        if should_use_proxy:
            logging.debug(f"【动态代理-{config.mode}】为请求启用代理: {target_url}")
            return {'http': config.url, 'https': config.url}
        else:
            logging.debug(f"【动态代理-{config.mode}】为请求禁用代理: {target_url}")
            return {}

    def _get_from_cache(self, key: str) -> Optional[Any]:
        if key in CACHE:
            data, timestamp = CACHE[key]
            if time.time() - timestamp < CACHE_DURATION:
                logging.info(f"【TMDB缓存】命中缓存: {key}")
                return data
            else:
                logging.info(f"【TMDB缓存】缓存已过期: {key}")
        return None

    def _set_to_cache(self, key: str, data: Any):
        logging.info(f"【TMDB缓存】设置缓存: {key}")
        CACHE[key] = (data, time.time())

    def _tmdb_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        full_params = {"api_key": self.tmdb_api_key, "language": "zh-CN", **(params or {})}
        cache_key = f"{endpoint}?{frozenset(full_params.items())}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data: return cached_data
        url = f"{self.tmdb_base_url}/{endpoint}"
        logging.info(f"【TMDB请求】向 TMDB 发起请求: {url}，参数: {params}")
        proxies = self._get_proxies_for_target(url)
        response = self.session.get(url, params=full_params, timeout=20, proxies=proxies)
        response.raise_for_status()
        data = response.json()
        self._set_to_cache(cache_key, data)
        return data

    def _get_emby_item_details(self, item_id: str, fields: str = "ProviderIds,People,ProductionYear") -> Dict:
        cache_key = f"emby_item_{item_id}_{fields}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            logging.info(f"【TMDB逻辑】命中请求级缓存，直接返回 Emby 项目 (ID: {item_id}) 的信息。")
            return cached_data

        logging.info(f"【TMDB逻辑】正在从 Emby 获取项目 (ID: {item_id}) 的详细信息，请求字段: {fields}...")
        url = f"{self.emby_config.server}/Users/{self.emby_config.user_id}/Items/{item_id}"
        params = {"api_key": self.emby_config.api_key, "Fields": fields}
        proxies = self._get_proxies_for_target(url)
        response = self.session.get(url, params=params, timeout=15, proxies=proxies)
        response.raise_for_status()
        data = response.json()
        logging.info(f"【TMDB逻辑】成功获取 Emby 项目 (ID: {item_id}) 的信息。")
        
        self._set_to_cache(cache_key, data)
        return data

    def _smart_match(self, item_details: Dict) -> TmdbImageResponse:
        item_type = "tv" if item_details.get("Type") == "Series" else "movie"
        title = item_details.get("Name")
        year = item_details.get("ProductionYear")
        if year:
            logging.info(f"【TMDB智能匹配】开始为 '{title}' ({year}) 进行智能匹配...")
            search_params = {"query": title, "year": year, "include_adult": False}
        else:
            logging.warning(f"【TMDB智能匹配】媒体项 '{title}' 缺少年份信息，将进行无年份搜索。")
            search_params = {"query": title, "include_adult": False}
        search_results = self._tmdb_request(f"search/{item_type}", search_params).get("results", [])
        if not search_results:
            logging.warning(f"【TMDB智能匹配】'{title}' 在TMDB中未搜索到任何结果。")
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
            logging.warning(f"【TMDB智能匹配】'{title}' 年份过滤后无匹配结果。")
            return TmdbImageResponse(status="not_found", message="在TMDB中未找到年份匹配的结果。")
        if len(candidates) == 1 and year:
            return TmdbImageResponse(status="single_candidate_confirm", candidates=[TmdbCandidate(**candidates[0])])
        else:
            return TmdbImageResponse(status="manual_selection", candidates=[TmdbCandidate(**c) for c in candidates[:10]])

    def _fetch_and_sort_images(self, tmdb_id: int, item_type: str, image_type: str) -> List[TmdbImage]:
        logging.info(f"【TMDB图片获取】正在为 TMDB ID: {tmdb_id} 获取 {image_type} 图片...")
        details = self._tmdb_request(f"{item_type}/{tmdb_id}")
        original_language = details.get("original_language")
        images_endpoint = f"{item_type}/{tmdb_id}/images"
        all_images_params = {"api_key": self.tmdb_api_key}
        cache_key = f"{images_endpoint}?{frozenset(all_images_params.items())}"
        all_images_data = self._get_from_cache(cache_key)
        if not all_images_data:
            url = f"{self.tmdb_base_url}/{images_endpoint}"
            proxies = self._get_proxies_for_target(url)
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
        
        # --- 核心修改 ---
        provider_ids = item_details.get("ProviderIds", {})
        provider_tmdb_id = next((v for k, v in provider_ids.items() if k.lower() == 'tmdb'), None)
        # --- 结束修改 ---

        if provider_tmdb_id:
            return int(provider_tmdb_id), None
        return None, self._smart_match(item_details)

    def update_ids_task(self, item_id: str, tmdb_id: int):
        logging.info(f"【后台任务】开始为 Emby 影视 ID {item_id} 更新 TMDB ID 为 {tmdb_id}")
        try:
            item_details = self._get_emby_item_details(item_id)
            item_details.setdefault("ProviderIds", {})["Tmdb"] = str(tmdb_id)
            url = f"{self.emby_config.server}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            params = {"api_key": self.emby_config.api_key}
            proxies = self._get_proxies_for_target(url)
            response = self.session.post(url, params=params, headers=headers, json=item_details, timeout=20, proxies=proxies)
            response.raise_for_status()
            logging.info(f"【后台任务】成功更新 Emby ProviderIds for item {item_id}。")
        except Exception as e:
            logging.error(f"【后台任务】更新 Emby ProviderIds for item {item_id} 失败: {e}")

    def update_person_ids_task(self, person_id: str, tmdb_person_id: int):
        """更新演员的 Emby ProviderIds"""
        logging.info(f"【ID关联】开始为 Emby 演员 ID {person_id} 更新 TMDB ID 为 {tmdb_person_id}")
        try:
            person_details = self._get_emby_item_details(person_id, fields="ProviderIds")
            
            provider_ids = person_details.get("ProviderIds", {})
            provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
            existing_id = provider_ids_lower.get('tmdb') or provider_ids_lower.get('moviedb id')

            if str(existing_id) == str(tmdb_person_id):
                logging.info(f"【ID关联】演员 {person_id} 的 TMDB ID 已是 {tmdb_person_id}，无需更新。")
                return

            person_details.setdefault("ProviderIds", {})["Tmdb"] = str(tmdb_person_id)
            
            url = f"{self.emby_config.server}/Items/{person_id}"
            headers = {'Content-Type': 'application/json'}
            params = {"api_key": self.emby_config.api_key}
            proxies = self._get_proxies_for_target(url)
            
            response = self.session.post(url, params=params, headers=headers, json=person_details, timeout=20, proxies=proxies)
            response.raise_for_status()
            logging.info(f"【ID关联】成功将演员 {person_id} 的 TMDB ID 更新为 {tmdb_person_id}。")
        except Exception as e:
            logging.error(f"【ID关联】更新 Emby ProviderIds for person {person_id} 失败: {e}")

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
        logging.info(f"【演员匹配-全局】开始全局搜索演员'{person_name}'")
        search_results = self._tmdb_request("search/person", {"query": person_name}).get("results", [])
        if not search_results:
            logging.warning(f"【演员匹配-全局】全局搜索未找到任何名为'{person_name}'的演员。")
            return ActorTmdbImageFlowResponse(status="not_found", message="未找到匹配的演员。")
        candidates = []
        for p in search_results:
            known_for_titles = [item.get('title') or item.get('name') for item in p.get('known_for', [])]
            candidates.append(TmdbPersonCandidate(id=p['id'], name=p['name'], profile_path=p.get('profile_path'), known_for_department=p.get('known_for_department'), known_for_titles=list(filter(None, known_for_titles))))
        return ActorTmdbImageFlowResponse(status="manual_actor_selection", candidates=candidates)

    def _fetch_person_images(self, person_id: int) -> List[TmdbImage]:
        logging.info(f"【演员图片获取】正在为演员(TMDB ID: {person_id})获取头像列表...")
        images_data = self._tmdb_request(f"person/{person_id}/images")
        profiles = images_data.get('profiles', [])
        profiles.sort(key=lambda x: x.get('vote_average', 0), reverse=True)
        return [TmdbImage(**img) for img in profiles]

   # backend/tmdb_logic.py (部分修改)

    def get_actor_images_flow(self, req: ActorTmdbImageFlowRequest, background_tasks: Any) -> ActorTmdbImageFlowResponse:
        logging.info(f"【演员图片流程-启动】请求: {req.model_dump_json(exclude_none=True, exclude_defaults=True)}")

        # --- 最终修复：将“检查已确认ID”作为最高优先级 ---
        if req.confirmed_tmdb_person_id:
            logging.info(f"【演员图片流程】检测到已确认的TMDB演员ID: {req.confirmed_tmdb_person_id}，直接处理。")
            background_tasks.add_task(self.update_person_ids_task, req.emby_person_id, req.confirmed_tmdb_person_id)
            images = self._fetch_person_images(req.confirmed_tmdb_person_id)
            person_details = self._tmdb_request(f"person/{req.confirmed_tmdb_person_id}")
            context = SingleActorConfirmContext(media={}, person={"name": person_details.get("name")})
            return ActorTmdbImageFlowResponse(status="success", images=images, context=context)

        # 只有在没有确认ID时，才检查强制标志
        if req.force_manual_search:
            logging.info("【TMDB匹配】接收到强制全局搜索指令，跳过所有自动匹配步骤。")
            return self._search_person_globally(req.emby_person_name)

        logging.info(f"【TMDB匹配】步骤A: 检查演员(ID: {req.emby_person_id})自身的ProviderIds...")
        emby_person_details = self._get_person_from_emby(req.emby_person_id)
        provider_ids = emby_person_details.get("ProviderIds", {})
        provider_ids_lower = {k.lower().replace(" ", ""): v for k, v in provider_ids.items()}
        possible_keys = ['tmdb', 'moviedbid']
        person_tmdb_id = next((provider_ids_lower[key] for key in possible_keys if key in provider_ids_lower), None)
        
        if person_tmdb_id:
            logging.info(f"【TMDB匹配】步骤A: 命中！找到TMDB演员ID: {person_tmdb_id}。")
            images = self._fetch_person_images(int(person_tmdb_id))
            person_details = self._tmdb_request(f"person/{person_tmdb_id}")
            context = SingleActorConfirmContext(media={}, person={"name": person_details.get("name")})
            return ActorTmdbImageFlowResponse(status="success", images=images, context=context)
        
        logging.info("【TMDB匹配】步骤A: 演员自身无TMDB ID。")

        logging.info(f"【TMDB匹配】步骤B: 尝试通过作品(ID: {req.emby_media_item_id})上下文匹配演员 '{req.emby_person_name}'...")
        media_details = self._get_emby_item_details(req.emby_media_item_id)
        media_tmdb_id, match_response = self.get_tmdb_id_flow(req.emby_media_item_id, item_details=media_details)
        
        if not media_tmdb_id:
            logging.warning(f"【TMDB匹配】步骤B: 无法确定作品的TMDB ID，上下文匹配失败。")
        else:
            if req.force_context_list:
                logging.info("【TMDB匹配】接收到强制上下文列表指令。")
                item_type = "tv" if media_details.get("Type") == "Series" else "movie"
                credits = self._tmdb_request(f"{item_type}/{media_tmdb_id}/credits")
                all_cast = credits.get('cast', [])
                candidates = [TmdbPersonCandidate(id=p['id'], name=p['name'], profile_path=p.get('profile_path'), known_for_department=p.get('known_for_department', 'Acting'), known_for_titles=[p.get('character', '')]) for p in all_cast]
                return ActorTmdbImageFlowResponse(status="context_manual_selection", candidates=candidates)

            context_result, media_info = self._get_tmdb_person_id_from_context(media_tmdb_id, req.emby_person_name, media_details)
            
            if media_info:
                logging.info(f"【TMDB匹配】步骤B: 上下文精确匹配成功，需要用户确认。")
                context = SingleActorConfirmContext(media={"title": media_info.get('title') or media_info.get('name'), "year": (media_info.get('release_date') or media_info.get('first_air_date', '----')).split('-')[0], "poster_path": media_info.get('poster_path')}, person={"id": context_result['id'], "name": context_result['name'], "character": context_result.get('character', 'N/A'), "profile_path": context_result.get('profile_path')})
                return ActorTmdbImageFlowResponse(status="single_actor_confirm", context=context)
            if isinstance(context_result, list):
                logging.info(f"【TMDB匹配】步骤B: 上下文匹配需要用户从列表中手动选择。")
                candidates = [TmdbPersonCandidate(id=p['id'], name=p['name'], profile_path=p.get('profile_path'), known_for_department=p.get('known_for_department', 'Acting'), known_for_titles=[p.get('character', '')]) for p in context_result]
                return ActorTmdbImageFlowResponse(status="context_manual_selection", candidates=candidates)
        
        logging.info("【TMDB匹配】步骤C: 降级为全局搜索。")
        return self._search_person_globally(req.emby_person_name)