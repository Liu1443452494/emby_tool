# backend/actor_gallery_logic.py (完整代码)

import logging
import os
import json
import requests
import base64
from io import BytesIO
from typing import Dict, List, Any, Tuple, Literal
from urllib.parse import unquote, urlparse, parse_qs

try:
    from PIL import Image, UnidentifiedImageError
except ImportError:
    Image = None
    UnidentifiedImageError = None
    logging.warning("【演员画廊】Pillow 库未安装，本地图片上传功能将受限。请运行 'pip install Pillow'")

from models import AppConfig, CombinedImage, CombinedImageResponse, CombinedAvatarResponse, CombinedActorImage, ActorTmdbImageFlowRequest, CombinedAvatarRequest
from douban_manager import DOUBAN_CACHE_FILE
from tmdb_logic import TmdbLogic

EmbyImageType = Literal["Primary", "Backdrop", "Logo"]

class ActorGalleryLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.server_config = app_config.server_config
        self.proxy_config = app_config.proxy_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.douban_map = self._load_douban_data()
        self.tmdb_logic = TmdbLogic(app_config)
        self.session = requests.Session()

    def _get_proxies_for_target(self, target_url: str) -> Dict:
        config = self.proxy_config
        if not config.enabled or not config.url: return {}
        is_tmdb_target = "themoviedb.org" in target_url or (self.tmdb_logic.tmdb_config.custom_api_domain_enabled and self.tmdb_logic.tmdb_config.custom_api_domain in target_url)
        is_douban_target = "douban.com" in target_url or "doubanio.com" in target_url
        is_emby_target = self.base_url in target_url
        should_use_proxy = False
        if config.mode == 'blacklist':
            should_use_proxy = True 
            if is_tmdb_target and config.target_tmdb: should_use_proxy = False
            if is_douban_target and config.target_douban: should_use_proxy = False
            if is_emby_target and config.target_emby: should_use_proxy = False
        elif config.mode == 'whitelist':
            if is_tmdb_target and config.target_tmdb: should_use_proxy = True
            if is_douban_target and config.target_douban: should_use_proxy = True
            if is_emby_target and config.target_emby: should_use_proxy = True
        if should_use_proxy:
            logging.debug(f"【动态代理-{config.mode}】为请求启用代理: {target_url}")
            return {'http': config.url, 'https': config.url}
        else:
            logging.debug(f"【动态代理-{config.mode}】为请求禁用代理: {target_url}")
            return {}

    def _load_douban_data(self) -> Dict:
        if not os.path.exists(DOUBAN_CACHE_FILE):
            logging.warning("【演员画廊】未找到豆瓣缓存文件，豆瓣匹配功能将无法使用。")
            return {}
        try:
            with open(DOUBAN_CACHE_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
            logging.info(f"【演员画廊】成功加载 {len(data)} 条豆瓣缓存数据。")
            return data
        except Exception as e:
            logging.error(f"【演员画廊】加载豆瓣缓存文件失败: {e}")
            return {}

    def get_library_items(self, library_id: str) -> List[Dict]:
        logging.info(f"【演员画廊】开始加载媒体库 (ID: {library_id}) 内的项目...")
        items, start_index, limit = [], 0, 500
        while True:
            url = f"{self.base_url}/Users/{self.user_id}/Items"
            params = {**self.params, "ParentId": library_id, "Recursive": "true", "IncludeItemTypes": "Movie,Series", "Fields": "ProviderIds,Id,Name,ProductionYear,Genres,Overview,CommunityRating,OfficialRating,ImageTags,BackdropImageTags", "StartIndex": start_index, "Limit": limit}
            proxies = self._get_proxies_for_target(url)
            response = self.session.get(url, params=params, timeout=120, proxies=proxies)
            response.raise_for_status()
            data = response.json().get("Items", [])
            if not data: break
            items.extend(data)
            start_index += len(data)
        logging.info(f"【演员画廊】媒体库 (ID: {library_id}) 加载完成，共找到 {len(items)} 个项目。")
        return items

    def get_item_actors(self, item_id: str) -> List[Dict]:
        logging.info(f"【演员画廊】正在获取项目 (ID: {item_id}) 的演职员信息...")
        url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
        params = {**self.params, "Fields": "People,PrimaryImageTag"}
        proxies = self._get_proxies_for_target(url)
        response = self.session.get(url, params=params, timeout=30, proxies=proxies)
        response.raise_for_status()
        people = response.json().get("People", [])
        logging.info(f"【演员画廊】项目 (ID: {item_id}) 成功获取到 {len(people)} 位演职员信息。")
        return people


    # backend/actor_gallery_logic.py (部分修改)

    # backend/actor_gallery_logic.py (部分修改)

    def avatar_flow_logic(self, person_id: str, req: CombinedAvatarRequest, background_tasks: Any) -> CombinedAvatarResponse:
        logging.info(f"【头像流程】开始执行，演员ID: {person_id}, 请求上下文: {req.model_dump_json(exclude_none=True, exclude_defaults=True)}")
        
        # --- 核心修改：从请求中恢复已确认的豆瓣图片 ---
        douban_images = [CombinedActorImage(**img) for img in req.confirmed_douban_images]
        tmdb_images = []
        warnings = []

        logging.info("【头像流程】=> 处理豆瓣数据...")
        if req.confirmed_douban_actor:
            logging.info("【豆瓣匹配】检测到已确认的豆瓣演员，直接生成图片。")
            actor_info = req.confirmed_douban_actor
            avatar_url = actor_info.get('avatar', {}).get('large')
            if avatar_url:
                # 避免重复添加
                if not any(img.file_path == avatar_url for img in douban_images):
                    douban_images.append(CombinedActorImage(file_path=avatar_url, source='douban', actor_name=actor_info.get('name')))
        elif not req.skip_douban:
            logging.info("【豆瓣匹配】无已确认演员，开始执行豆瓣匹配流程...")
            douban_result = self._handle_douban_flow(req)
            
            if isinstance(douban_result, CombinedAvatarResponse):
                logging.info("【头像流程】豆瓣匹配需要用户干预，流程中断。")
                candidates_list = douban_result.intervention_details
                douban_result.intervention_details = {
                    'candidates': candidates_list,
                    'next_request_patch': {'skip_douban': True}
                }
                return douban_result
                
            # 将新找到的图片存入 douban_images
            new_douban_images, warnings = douban_result
            douban_images.extend(new_douban_images)
        else:
            logging.info("【头像流程】已跳过豆瓣匹配阶段。")
        
        logging.info(f"【头像流程】豆瓣处理阶段完成，当前共有 {len(douban_images)} 张豆瓣图片。")

        if not req.skip_tmdb:
            logging.info("【头像流程】=> 进入TMDB匹配阶段...")
            tmdb_result = self._handle_tmdb_flow(person_id, req, background_tasks)
            if isinstance(tmdb_result, CombinedAvatarResponse):
                logging.info("【头像流程】TMDB匹配需要用户干预，流程中断。")
                # --- 核心修改：在中断时，把当前已有的豆瓣图片信息附加到返回结果中 ---
                tmdb_result.intervention_details['next_request_patch'] = {
                    'skip_douban': True,
                    'confirmed_douban_images': [img.model_dump() for img in douban_images]
                }
                return tmdb_result
                
            tmdb_images, tmdb_warnings = tmdb_result
            warnings.extend(tmdb_warnings)
            logging.info(f"【头像流程】TMDB匹配阶段完成，找到 {len(tmdb_images)} 张图片。")

        # ... 合并逻辑保持不变 ...
        logging.info("【合并图片】开始合并豆瓣和TMDB的结果。")
        if douban_images and not tmdb_images:
            logging.info("【合并图片】仅豆瓣源有结果，返回豆瓣图片。")
            return CombinedAvatarResponse(status='success', images=douban_images, warnings=warnings)
        
        combined_images = douban_images + tmdb_images
        if combined_images:
            logging.info(f"【合并图片】成功，共找到 {len(combined_images)} 张图片。")
            return CombinedAvatarResponse(status='success', images=combined_images, warnings=warnings)
        else:
            final_warnings = warnings if warnings else ["所有数据源均未找到可用头像。"]
            logging.warning(f"【合并图片】失败，所有源均未找到图片。警告: {final_warnings}")
            return CombinedAvatarResponse(status='all_failed', warnings=final_warnings)

    def _handle_douban_flow(self, req: CombinedAvatarRequest) -> Tuple[List[CombinedActorImage], List[str]] | CombinedAvatarResponse:
        warnings = []
        if req.confirmed_douban_actor:
            logging.info("【豆瓣匹配】使用已确认的豆瓣演员。")
            actor_info = req.confirmed_douban_actor
        else:
            try:
                douban_media_item = self._get_douban_media_item(req.emby_media_item_id)
                douban_actors = douban_media_item.get('actors', [])
                logging.info(f"【豆瓣匹配】正在从 {len(douban_actors)} 位豆瓣演员中查找 '{req.emby_person_name}'...")
                matched_actor = next((actor for actor in douban_actors if actor.get('name') == req.emby_person_name), None)
                if matched_actor and matched_actor.get('avatar', {}).get('large'):
                    logging.info(f"【豆瓣匹配】精确匹配成功: {matched_actor.get('name')}")
                    actor_info = matched_actor
                else:
                    logging.info("【豆瓣匹配】精确匹配失败或无头像，需要手动选择。")
                    return CombinedAvatarResponse(status='douban_manual_selection', intervention_details=douban_actors)
            except ValueError as e:
                warnings.append(f"豆瓣数据源不可用: {e}")
                return [], warnings
        
        avatar_url = actor_info.get('avatar', {}).get('large')
        if avatar_url:
            return [CombinedActorImage(file_path=avatar_url, source='douban', actor_name=actor_info.get('name'))], warnings
        return [], warnings

    # backend/actor_gallery_logic.py (部分修改)

    def _handle_tmdb_flow(self, person_id: str, req: CombinedAvatarRequest, background_tasks: Any) -> Tuple[List[CombinedActorImage], List[str]] | CombinedAvatarResponse:
        warnings = []
        
        # 1. 构造请求
        tmdb_flow_req = ActorTmdbImageFlowRequest(
            emby_person_id=person_id,
            emby_person_name=req.emby_person_name,
            emby_media_item_id=req.emby_media_item_id,
            confirmed_tmdb_person_id=req.confirmed_tmdb_person_id,
            force_context_list=req.force_tmdb_context_list,
            force_manual_search=req.force_tmdb_global_search
        )
        
        # 2. 调用TMDB逻辑层的统一流程
        tmdb_result = self.tmdb_logic.get_actor_images_flow(tmdb_flow_req, background_tasks)

        # 3. 处理返回结果
        if tmdb_result.status == 'success':
            logging.info(f"【TMDB流程】成功获取到 {len(tmdb_result.images)} 张图片。")
            actor_name = tmdb_result.context.person.get("name", req.emby_person_name) if tmdb_result.context else req.emby_person_name
            images = [
                CombinedActorImage(
                    file_path=img.file_path, 
                    source='tmdb', 
                    vote_average=img.vote_average, 
                    iso_639_1=img.iso_639_1, 
                    actor_name=actor_name
                ) for img in tmdb_result.images
            ]
            return images, warnings
        
        elif tmdb_result.status == 'not_found':
            warnings.append(f"TMDB未能找到演员 '{req.emby_person_name}'。")
            return [], warnings
            
        else: # 需要用户干预
            logging.info(f"【TMDB流程】需要用户干预，状态: {tmdb_result.status}")
            
            # --- 最终修复：当TMDB需要干预时，也告诉前端下一步跳过豆瓣 ---
            response_payload = tmdb_result.model_dump()
            response_payload['next_request_patch'] = {'skip_douban': True}

            return CombinedAvatarResponse(
                status=f"tmdb_{tmdb_result.status}", 
                intervention_details=response_payload
            )

    def _get_douban_media_item(self, item_id: str):
        if not self.douban_map: raise ValueError("本地豆瓣数据库为空")
        item_details_url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
        item_details_params = {**self.params, "Fields": "ProviderIds"}
        proxies = self._get_proxies_for_target(item_details_url)
        item_resp = self.session.get(item_details_url, params=item_details_params, timeout=15, proxies=proxies)
        item_resp.raise_for_status()
        
        # --- 核心修改 ---
        provider_ids = item_resp.json().get("ProviderIds", {})
        douban_id = next((v for k, v in provider_ids.items() if k.lower() == 'douban'), None)
        # --- 结束修改 ---

        if not douban_id: raise ValueError("当前媒体项没有关联豆瓣ID")
        douban_media_item = self.douban_map.get(douban_id)
        if not douban_media_item: raise ValueError(f"在本地豆瓣数据中未找到ID为 {douban_id} 的媒体项")
        return douban_media_item

    def match_douban_poster(self, item_id: str) -> Dict:
        logging.info(f"【演员画廊】开始为媒体 (ID: {item_id}) 匹配豆瓣海报...")
        douban_media_item = self._get_douban_media_item(item_id)
        poster_url = douban_media_item.get('pic', {}).get('large')
        if not poster_url:
            raise ValueError("该豆瓣条目没有海报信息。")
        logging.info(f"【演员画廊】成功匹配到海报URL: {poster_url}")
        return {"poster_url": poster_url}

    def _update_person_name(self, person_id: str, new_name: str):
        logging.info(f"【姓名更新】开始为演员 (ID: {person_id}) 更新姓名为 '{new_name}'。")
        try:
            person_url = f"{self.base_url}/Users/{self.user_id}/Items/{person_id}"
            proxies = self._get_proxies_for_target(person_url)
            person_details = self.session.get(person_url, params=self.params, timeout=15, proxies=proxies).json()
            original_name = person_details.get("Name")
            if original_name == new_name: return
            person_details["Name"] = new_name
            update_url = f"{self.base_url}/Items/{person_id}"
            headers = {'Content-Type': 'application/json'}
            proxies = self._get_proxies_for_target(update_url)
            response = self.session.post(update_url, params=self.params, json=person_details, headers=headers, timeout=30, proxies=proxies)
            response.raise_for_status()
            logging.info(f"【姓名更新】成功将演员 (ID: {person_id}) 的姓名从 '{original_name}' 更新为 '{new_name}'。")
        except Exception as e:
            logging.error(f"【姓名更新】更新演员 (ID: {person_id}) 姓名时失败: {e}", exc_info=True)
            
    def _upload_image_to_emby(self, item_id: str, image_data: bytes, content_type: str, image_type: EmbyImageType = "Primary") -> bool:
        logging.info(f"【图片上传】准备上传 {image_type} 图片到 Emby，目标ID: {item_id}")
        url = f"{self.base_url}/Items/{item_id}/Images/{image_type}"
        headers = {'Content-Type': content_type, 'User-Agent': 'Mozilla/5.0'}
        base64_encoded_data = base64.b64encode(image_data).decode('utf-8')
        try:
            proxies = self._get_proxies_for_target(url)
            self.session.delete(url, params=self.params, timeout=20, proxies=proxies)
        except Exception as e:
            logging.warning(f"【图片上传】删除旧图片时发生错误: {e}")
        proxies = self._get_proxies_for_target(url)
        response = self.session.post(url, params=self.params, data=base64_encoded_data, headers=headers, timeout=60, proxies=proxies)
        response.raise_for_status()
        return True

    def upload_image_from_url(self, item_id: str, image_url: str, image_type: EmbyImageType = "Primary", new_name: str = None, source: str = 'tmdb') -> bool:
        if new_name: self._update_person_name(item_id, new_name)
        logging.info(f"【图片上传】正在从URL下载图片: {image_url} (来源: {source})")
        image_data, content_type = self.get_image_from_url(image_url)
        return self._upload_image_to_emby(item_id, image_data, content_type, image_type)

    def upload_image_from_local(self, item_id: str, file_content: bytes, new_name: str = None) -> bool:
        if new_name: self._update_person_name(item_id, new_name)
        if Image is None: raise ImportError("Pillow 库未安装")
        with Image.open(BytesIO(file_content)) as img:
            img = img.convert('RGB') if img.mode not in ('RGB', 'L') else img
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=95)
            return self._upload_image_to_emby(item_id, buffer.getvalue(), 'image/jpeg', "Primary")

    def get_image_from_url(self, image_url: str) -> Tuple[bytes, str]:
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://movie.douban.com/'}
        proxies = self._get_proxies_for_target(image_url)
        response = self.session.get(image_url, headers=headers, timeout=30, proxies=proxies)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', 'image/jpeg')
        if not content_type.startswith('image/'): raise ValueError(f"URL返回的不是有效的图片类型: {content_type}")
        return response.content, content_type

    def update_douban_id(self, item_id: str, new_douban_id: str):
        logging.info(f"【豆瓣ID更新】开始为项目 (ID: {item_id}) 更新豆瓣ID为 '{new_douban_id}'。")
        try:
            item_url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
            proxies = self._get_proxies_for_target(item_url)
            item_details = self.session.get(item_url, params=self.params, timeout=15, proxies=proxies).json()
            item_details.setdefault("ProviderIds", {})["Douban"] = new_douban_id
            update_url = f"{self.base_url}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            proxies = self._get_proxies_for_target(update_url)
            self.session.post(update_url, params=self.params, json=item_details, headers=headers, timeout=30, proxies=proxies).raise_for_status()
            return {"status": "success", "message": "豆瓣ID更新成功！"}
        except Exception as e:
            logging.error(f"【豆瓣ID更新】更新项目 (ID: {item_id}) 的豆瓣ID时失败: {e}", exc_info=True)
            raise e

    def get_combined_posters(self, item_id: str) -> CombinedImageResponse:
        images, warnings = [], []
        try:
            douban_poster_info = self.match_douban_poster(item_id)
            if poster_url := douban_poster_info.get("poster_url"):
                images.append(CombinedImage(file_path=poster_url, source='douban'))
        except Exception as e:
            warnings.append(f"无法获取豆瓣海报: {e}")
        try:
            tmdb_id, _ = self.tmdb_logic.get_tmdb_id_flow(item_id)
            if tmdb_id:
                item_details = self.tmdb_logic._get_emby_item_details(item_id)
                item_type_str = "tv" if item_details.get("Type") == "Series" else "movie"
                tmdb_posters = self.tmdb_logic._fetch_and_sort_images(tmdb_id, item_type_str, 'poster')
                for poster in tmdb_posters:
                    images.append(CombinedImage(file_path=poster.file_path, source='tmdb', vote_average=poster.vote_average, iso_639_1=poster.iso_639_1))
            else:
                warnings.append("媒体项缺少TMDB ID，无法获取TMDB海报。")
        except Exception as e:
            warnings.append(f"无法获取TMDB海报: {e}")
        if not images and warnings: return CombinedImageResponse(success=False, warnings=warnings)
        return CombinedImageResponse(success=True, images=images, warnings=warnings)