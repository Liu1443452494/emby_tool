
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


from log_manager import ui_logger
from models import AppConfig, CombinedImage, CombinedImageResponse, CombinedAvatarResponse, CombinedActorImage, ActorTmdbImageFlowRequest, CombinedAvatarRequest
from douban_manager import DOUBAN_CACHE_FILE
from tmdb_logic import TmdbLogic
from proxy_manager import ProxyManager

EmbyImageType = Literal["Primary", "Backdrop", "Logo"]

class ActorGalleryLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.server_config = app_config.server_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.douban_map = self._load_douban_data()
        self.tmdb_logic = TmdbLogic(app_config)
        self.session = requests.Session()
        self.proxy_manager = ProxyManager(app_config)

    def _load_douban_data(self) -> Dict:
        task_cat = "媒体画廊-初始化"
        if not os.path.exists(DOUBAN_CACHE_FILE):
            ui_logger.warning("未找到豆瓣缓存文件，豆瓣匹配功能将无法使用。", task_category=task_cat)
            return {}
        try:
            with open(DOUBAN_CACHE_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
            ui_logger.info(f"成功加载 {len(data)} 条豆瓣缓存数据。", task_category=task_cat)
            return data
        except Exception as e:
            ui_logger.error(f"加载豆瓣缓存文件失败: {e}", task_category=task_cat)
            return {}

    def get_library_items(self, library_id: str) -> List[Dict]:
        task_cat = f"媒体画廊-媒体库({library_id})"
        ui_logger.info(f"开始加载媒体库内项目...", task_category=task_cat)
        items, start_index, limit = [], 0, 500
        while True:
            url = f"{self.base_url}/Users/{self.user_id}/Items"
            params = {**self.params, "ParentId": library_id, "Recursive": "true", "IncludeItemTypes": "Movie,Series", "Fields": "ProviderIds,Id,Name,ProductionYear,Genres,Overview,CommunityRating,OfficialRating,ImageTags,BackdropImageTags", "StartIndex": start_index, "Limit": limit}
            proxies = self.proxy_manager.get_proxies(url)
            response = self.session.get(url, params=params, timeout=120, proxies=proxies)
            response.raise_for_status()
            data = response.json().get("Items", [])
            if not data: break
            items.extend(data)
            start_index += len(data)
        ui_logger.info(f"媒体库加载完成，共找到 {len(items)} 个项目。", task_category=task_cat)
        return items

    def get_item_actors(self, item_id: str) -> List[Dict]:
        task_cat = f"媒体画廊-演员列表({item_id})"
        ui_logger.info(f"正在获取项目的演职员信息...", task_category=task_cat)
        url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
        params = {**self.params, "Fields": "People,PrimaryImageTag"}
        proxies = self.proxy_manager.get_proxies(url)
        response = self.session.get(url, params=params, timeout=30, proxies=proxies)
        response.raise_for_status()
        people = response.json().get("People", [])
        ui_logger.info(f"成功获取到 {len(people)} 位演职员信息。", task_category=task_cat)
        return people

    def avatar_flow_logic(self, person_id: str, req: CombinedAvatarRequest, background_tasks: Any) -> CombinedAvatarResponse:
        task_cat = f"头像流程({req.emby_person_name})"
        ui_logger.info(f"流程启动，演员ID: {person_id}, 请求: {req.model_dump_json(exclude_none=True, exclude_defaults=True)}", task_category=task_cat)
        
        douban_images = [CombinedActorImage(**img) for img in req.confirmed_douban_images]
        tmdb_images = []
        warnings = []

        ui_logger.info("=> 阶段1: 处理豆瓣数据...", task_category=task_cat)
        if req.confirmed_douban_actor:
            ui_logger.info("   - 检测到已确认的豆瓣演员，直接生成图片。", task_category=task_cat)
            actor_info = req.confirmed_douban_actor
            avatar_url = actor_info.get('avatar', {}).get('large')
            if avatar_url:
                if not any(img.file_path == avatar_url for img in douban_images):
                    douban_images.append(CombinedActorImage(file_path=avatar_url, source='douban', actor_name=actor_info.get('name')))
        elif not req.skip_douban:
            ui_logger.info("   - 无已确认演员，开始执行豆瓣匹配...", task_category=task_cat)
            douban_result = self._handle_douban_flow(req, task_cat)
            
            if isinstance(douban_result, CombinedAvatarResponse):
                ui_logger.info("   - 豆瓣匹配需要用户干预，流程中断。", task_category=task_cat)
                candidates_list = douban_result.intervention_details
                douban_result.intervention_details = {
                    'candidates': candidates_list,
                    'next_request_patch': {'skip_douban': True}
                }
                return douban_result
                
            new_douban_images, warnings = douban_result
            douban_images.extend(new_douban_images)
        else:
            ui_logger.info("   - 已跳过豆瓣匹配阶段。", task_category=task_cat)
        
        ui_logger.info(f"=> 阶段1完成，当前共有 {len(douban_images)} 张豆瓣图片。", task_category=task_cat)

        if not req.skip_tmdb:
            ui_logger.info("=> 阶段2: 进入TMDB匹配...", task_category=task_cat)
            tmdb_result = self._handle_tmdb_flow(person_id, req, background_tasks, task_cat)
            if isinstance(tmdb_result, CombinedAvatarResponse):
                ui_logger.info("   - TMDB匹配需要用户干预，流程中断。", task_category=task_cat)
                tmdb_result.intervention_details['next_request_patch'] = {
                    'skip_douban': True,
                    'confirmed_douban_images': [img.model_dump() for img in douban_images]
                }
                return tmdb_result
                
            tmdb_images, tmdb_warnings = tmdb_result
            warnings.extend(tmdb_warnings)
            ui_logger.info(f"=> 阶段2完成，找到 {len(tmdb_images)} 张TMDB图片。", task_category=task_cat)

        ui_logger.info("=> 阶段3: 合并图片...", task_category=task_cat)
        if douban_images and not tmdb_images:
            ui_logger.info("   - 仅豆瓣源有结果，返回豆瓣图片。", task_category=task_cat)
            return CombinedAvatarResponse(status='success', images=douban_images, warnings=warnings)
        
        combined_images = douban_images + tmdb_images
        if combined_images:
            ui_logger.info(f"   - 成功，共找到 {len(combined_images)} 张图片。", task_category=task_cat)
            return CombinedAvatarResponse(status='success', images=combined_images, warnings=warnings)
        else:
            final_warnings = warnings if warnings else ["所有数据源均未找到可用头像。"]
            ui_logger.warning(f"   - 失败，所有源均未找到图片。警告: {final_warnings}", task_category=task_cat)
            return CombinedAvatarResponse(status='all_failed', warnings=final_warnings)

    def _handle_douban_flow(self, req: CombinedAvatarRequest, task_cat: str) -> Tuple[List[CombinedActorImage], List[str]] | CombinedAvatarResponse:
        warnings = []
        if req.confirmed_douban_actor:
            ui_logger.info("   - [豆瓣] 使用已确认的豆瓣演员。", task_category=task_cat)
            actor_info = req.confirmed_douban_actor
        else:
            try:
                douban_media_item = self._get_douban_media_item(req.emby_media_item_id, task_cat)
                douban_actors = douban_media_item.get('actors', [])
                ui_logger.info(f"   - [豆瓣] 正在从 {len(douban_actors)} 位豆瓣演员中查找 '{req.emby_person_name}'...", task_category=task_cat)
                matched_actor = next((actor for actor in douban_actors if actor.get('name') == req.emby_person_name), None)
                if matched_actor and matched_actor.get('avatar', {}).get('large'):
                    ui_logger.info(f"   - [豆瓣] 精确匹配成功: {matched_actor.get('name')}", task_category=task_cat)
                    actor_info = matched_actor
                else:
                    ui_logger.info("   - [豆瓣] 精确匹配失败或无头像，需要手动选择。", task_category=task_cat)
                    return CombinedAvatarResponse(status='douban_manual_selection', intervention_details=douban_actors)
            except ValueError as e:
                warnings.append(f"豆瓣数据源不可用: {e}")
                return [], warnings
        
        avatar_url = actor_info.get('avatar', {}).get('large')
        if avatar_url:
            return [CombinedActorImage(file_path=avatar_url, source='douban', actor_name=actor_info.get('name'))], warnings
        return [], warnings

    def _handle_tmdb_flow(self, person_id: str, req: CombinedAvatarRequest, background_tasks: Any, task_cat: str) -> Tuple[List[CombinedActorImage], List[str]] | CombinedAvatarResponse:
        warnings = []
        
        tmdb_flow_req = ActorTmdbImageFlowRequest(
            emby_person_id=person_id,
            emby_person_name=req.emby_person_name,
            emby_media_item_id=req.emby_media_item_id,
            confirmed_tmdb_person_id=req.confirmed_tmdb_person_id,
            force_context_list=req.force_tmdb_context_list,
            force_manual_search=req.force_tmdb_global_search
        )
        
        tmdb_result = self.tmdb_logic.get_actor_images_flow(tmdb_flow_req, background_tasks)

        if tmdb_result.status == 'success':
            ui_logger.info(f"   - [TMDB] 成功获取到 {len(tmdb_result.images)} 张图片。", task_category=task_cat)
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
            
        else: 
            ui_logger.info(f"   - [TMDB] 需要用户干预，状态: {tmdb_result.status}", task_category=task_cat)
            response_payload = tmdb_result.model_dump()
            response_payload['next_request_patch'] = {'skip_douban': True}

            return CombinedAvatarResponse(
                status=f"tmdb_{tmdb_result.status}", 
                intervention_details=response_payload
            )

    def _get_douban_media_item(self, item_id: str, task_cat: str):
        if not self.douban_map: raise ValueError("本地豆瓣数据库为空")
        item_details_url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
        item_details_params = {**self.params, "Fields": "ProviderIds"}
        proxies = self.proxy_manager.get_proxies(item_details_url)
        item_resp = self.session.get(item_details_url, params=item_details_params, timeout=15, proxies=proxies)
        item_resp.raise_for_status()
        
        provider_ids = item_resp.json().get("ProviderIds", {})
        douban_id = next((v for k, v in provider_ids.items() if k.lower() == 'douban'), None)

        if not douban_id: raise ValueError("当前媒体项没有关联豆瓣ID")
        douban_media_item = self.douban_map.get(douban_id)
        if not douban_media_item: raise ValueError(f"在本地豆瓣数据中未找到ID为 {douban_id} 的媒体项")
        return douban_media_item

    def match_douban_poster(self, item_id: str) -> Dict:
        task_cat = f"媒体画廊-海报匹配({item_id})"
        ui_logger.info(f"开始为媒体匹配豆瓣海报...", task_category=task_cat)
        douban_media_item = self._get_douban_media_item(item_id, task_cat)
        poster_url = douban_media_item.get('pic', {}).get('large')
        if not poster_url:
            raise ValueError("该豆瓣条目没有海报信息。")
        ui_logger.info(f"成功匹配到海报URL: {poster_url}", task_category=task_cat)
        return {"poster_url": poster_url}

    def _update_person_name(self, person_id: str, new_name: str):
        task_cat = f"姓名更新({person_id})"
        ui_logger.info(f"开始为演员更新姓名为 '{new_name}'。", task_category=task_cat)
        try:
            person_url = f"{self.base_url}/Users/{self.user_id}/Items/{person_id}"
            proxies = self.proxy_manager.get_proxies(person_url)
            person_details = self.session.get(person_url, params=self.params, timeout=15, proxies=proxies).json()
            original_name = person_details.get("Name")
            if original_name == new_name: 
                ui_logger.info("新旧姓名一致，无需更新。", task_category=task_cat)
                return
            person_details["Name"] = new_name
            update_url = f"{self.base_url}/Items/{person_id}"
            headers = {'Content-Type': 'application/json'}
            proxies_update = self.proxy_manager.get_proxies(update_url)
            response = self.session.post(update_url, params=self.params, json=person_details, headers=headers, timeout=30, proxies=proxies_update)
            response.raise_for_status()
            ui_logger.info(f"成功将演员姓名从 '{original_name}' 更新为 '{new_name}'。", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"更新演员姓名时失败: {e}", task_category=task_cat, exc_info=True)
            
    def _upload_image_to_emby(self, item_id: str, image_data: bytes, content_type: str, image_type: EmbyImageType = "Primary") -> bool:
        task_cat = f"图片上传({item_id})"
        ui_logger.info(f"准备上传 {image_type} 图片到 Emby...", task_category=task_cat)
        url = f"{self.base_url}/Items/{item_id}/Images/{image_type}"
        headers = {'Content-Type': content_type, 'User-Agent': 'Mozilla/5.0'}
        base64_encoded_data = base64.b64encode(image_data).decode('utf-8')
        try:
            proxies = self.proxy_manager.get_proxies(url)
            self.session.delete(url, params=self.params, timeout=20, proxies=proxies)
        except Exception as e:
            ui_logger.warning(f"删除旧图片时发生错误: {e}", task_category=task_cat)
        proxies_post = self.proxy_manager.get_proxies(url)
        response = self.session.post(url, params=self.params, data=base64_encoded_data, headers=headers, timeout=60, proxies=proxies_post)
        response.raise_for_status()
        return True

    def upload_image_from_url(self, item_id: str, image_url: str, image_type: EmbyImageType = "Primary", new_name: str = None, source: str = 'tmdb') -> bool:
        task_cat = f"图片上传({item_id})"
        if new_name: self._update_person_name(item_id, new_name)
        ui_logger.info(f"正在从URL下载图片: {image_url} (来源: {source})", task_category=task_cat)
        image_data, content_type = self.get_image_from_url(image_url, task_cat)
        return self._upload_image_to_emby(item_id, image_data, content_type, image_type)

    def upload_image_from_local(self, item_id: str, file_content: bytes, new_name: str = None) -> bool:
        if new_name: self._update_person_name(item_id, new_name)
        if Image is None: raise ImportError("Pillow 库未安装")
        with Image.open(BytesIO(file_content)) as img:
            img = img.convert('RGB') if img.mode not in ('RGB', 'L') else img
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=95)
            return self._upload_image_to_emby(item_id, buffer.getvalue(), 'image/jpeg', "Primary")

    def get_image_from_url(self, image_url: str, task_cat: str) -> Tuple[bytes, str]:
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://movie.douban.com/'}
        proxies = self.proxy_manager.get_proxies(image_url)
        response = self.session.get(image_url, headers=headers, timeout=30, proxies=proxies)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', 'image/jpeg')
        if not content_type.startswith('image/'): raise ValueError(f"URL返回的不是有效的图片类型: {content_type}")
        return response.content, content_type

    def update_douban_id(self, item_id: str, new_douban_id: str):
        task_cat = f"豆瓣ID更新({item_id})"
        ui_logger.info(f"开始为项目更新豆瓣ID为 '{new_douban_id}'。", task_category=task_cat)
        try:
            item_url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
            proxies = self.proxy_manager.get_proxies(item_url)
            item_details = self.session.get(item_url, params=self.params, timeout=15, proxies=proxies).json()
            item_details.setdefault("ProviderIds", {})["Douban"] = new_douban_id
            update_url = f"{self.base_url}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            proxies_update = self.proxy_manager.get_proxies(update_url)
            
            self.session.post(update_url, params=self.params, json=item_details, headers=headers, timeout=30, proxies=proxies_update).raise_for_status()
            return {"status": "success", "message": "豆瓣ID更新成功！"}
        except Exception as e:
            ui_logger.error(f"更新项目的豆瓣ID时失败: {e}", task_category=task_cat, exc_info=True)
            raise e

    def get_combined_posters(self, item_id: str) -> CombinedImageResponse:
        task_cat = f"合并海报({item_id})"
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