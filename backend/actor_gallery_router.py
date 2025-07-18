
from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks, Form
from fastapi.responses import Response
import logging
from typing import Optional


from log_manager import ui_logger
from models import (
    AppConfig, ActorGalleryMatchRequest, ActorGalleryUploadRequest, 
    PosterUploadRequest, TmdbImageRequest, TmdbImageResponse, TmdbConfirmRequest,ActorTmdbImageFlowRequest, ActorTmdbImageFlowResponse,
    UpdateDoubanIdRequest, CombinedImageResponse, CombinedAvatarRequest, CombinedAvatarResponse
)
from actor_gallery_logic import ActorGalleryLogic
from actor_avatar_mapper_logic import ActorAvatarMapperLogic
from tmdb_logic import TmdbLogic
import config as app_config

router = APIRouter()

def get_logic() -> ActorGalleryLogic:
    config = app_config.load_app_config()
    if not all([config.server_config.server, config.server_config.api_key, config.server_config.user_id]):
        raise HTTPException(status_code=400, detail="Emby 服务器未配置，请先在配置页面完成设置。")
    return ActorGalleryLogic(config)

def get_tmdb_logic() -> TmdbLogic:
    config = app_config.load_app_config()
    if not config.tmdb_config.api_key:
        raise HTTPException(status_code=400, detail="TMDB API Key 未配置，请先在配置页面完成设置。")
    return TmdbLogic(config)


@router.get("/items/{library_id}")
def get_library_items_route(library_id: str):
    task_cat = "API-画廊"
    try:
        logic = get_logic()
        return logic.get_library_items(library_id)
    except Exception as e:
        ui_logger.error(f"获取媒体库({library_id})项目失败: {e}", task_category=task_cat)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/actors/{item_id}")
def get_item_actors_route(item_id: str):
    task_cat = "API-画廊"
    try:
        logic = get_logic()
        return logic.get_item_actors(item_id)
    except Exception as e:
        ui_logger.error(f"获取演职员列表({item_id})失败: {e}", task_category=task_cat)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/actors/{person_id}/avatar-flow")
def avatar_flow_route(person_id: str, req: CombinedAvatarRequest, background_tasks: BackgroundTasks):
    task_cat = "API-画廊"
    try:
        logic = get_logic()
        return logic.avatar_flow_logic(person_id, req, background_tasks)
    except Exception as e:
        ui_logger.error(f"执行头像流程({person_id})失败: {e}", task_category=task_cat, exc_info=True)
        raise HTTPException(status_code=500, detail=f"执行头像获取流程时发生内部错误: {e}")


@router.post("/actors/upload-from-url")
def upload_avatar_from_url_route(req: ActorGalleryUploadRequest, background_tasks: BackgroundTasks):
    task_cat = "API-画廊"
    try:
        logic = get_logic()
        logic.upload_image_from_url(req.person_id, req.image_url, "Primary", req.new_name, req.source)
        
        if req.tmdb_person_id:
            try:
                avatar_mapper_logic = ActorAvatarMapperLogic(app_config.load_app_config())
                
                from urllib.parse import urlparse
                image_path = ""
                if req.source == 'tmdb':
                    parsed_url = urlparse(req.image_url)
                    path_parts = parsed_url.path.split('/')
                    if len(path_parts) > 1:
                        # 提取最后一个部分作为文件名，并加上前导斜杠
                        image_path = "/" + path_parts[-1]
                    else:
                        image_path = parsed_url.path
                else: # douban
                    image_path = req.image_url

                actor_details = logic._get_emby_item_details(req.person_id, "Name")
                actor_name = req.new_name or actor_details.get("Name", "未知")

                image_info = {
                    "actor_name": actor_name,
                    "source": req.source,
                    "image_path": image_path
                }
                
                background_tasks.add_task(
                    avatar_mapper_logic.save_avatar_choice_to_map,
                    req.tmdb_person_id, 
                    image_info
                )
                
                tmdb_logic = get_tmdb_logic()
                background_tasks.add_task(tmdb_logic.update_person_ids_task, req.person_id, req.tmdb_person_id)

            except Exception as e:
                ui_logger.error(f"❌ 保存演员头像选择到映射表时失败: {e}", task_category=task_cat, exc_info=True)

        message = "头像上传成功！"
        if req.new_name:
            message = f"头像上传成功，且演员姓名已同步更新为 '{req.new_name}'。"
        return {"status": "success", "message": message}
    except Exception as e:
        ui_logger.error(f"从URL上传头像({req.person_id})失败: {e}", task_category=task_cat)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/actors/{person_id}/upload-local")
async def upload_avatar_from_local_route(person_id: str, file: UploadFile = File(...), new_name: Optional[str] = Form(None)):
    task_cat = "API-画廊"
    try:
        logic = get_logic()
        contents = await file.read()
        logic.upload_image_from_local(person_id, contents, new_name)
        message = "本地头像上传成功！"
        if new_name:
            message = f"本地头像上传成功，且演员姓名已同步更新为 '{new_name}'。"
        return {"status": "success", "message": message}
    except Exception as e:
        ui_logger.error(f"从本地上传头像({person_id})失败: {e}", task_category=task_cat)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/items/upload-poster-from-url")
def upload_poster_from_url_route(req: PosterUploadRequest):
    task_cat = "API-画廊"
    try:
        logic = get_logic()
        logic.upload_image_from_url(req.item_id, req.image_url, "Primary", source=req.source)
        return {"status": "success", "message": "海报上传任务已提交至 Emby。"}
    except Exception as e:
        ui_logger.error(f"从URL上传海报({req.item_id})失败: {e}", task_category=task_cat, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/items/upload-backdrop-from-url")
def upload_backdrop_from_url_route(req: PosterUploadRequest):
    task_cat = "API-画廊"
    try:
        logic = get_logic()
        logic.upload_image_from_url(req.item_id, req.image_url, "Backdrop")
        return {"status": "success", "message": "背景图上传任务已提交至 Emby。"}
    except Exception as e:
        ui_logger.error(f"从URL上传背景图({req.item_id})失败: {e}", task_category=task_cat)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/items/upload-logo-from-url")
def upload_logo_from_url_route(req: PosterUploadRequest):
    task_cat = "API-画廊"
    try:
        logic = get_logic()
        logic.upload_image_from_url(req.item_id, req.image_url, "Logo")
        return {"status": "success", "message": "Logo上传任务已提交至 Emby。"}
    except Exception as e:
        ui_logger.error(f"从URL上传Logo({req.item_id})失败: {e}", task_category=task_cat)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/proxy-image")
async def proxy_image_route(image_url: str):
    task_cat = "API-画廊"
    try:
        logic = get_logic()
        image_data, content_type = logic.get_image_from_url(image_url, task_cat)
        return Response(content=image_data, media_type=content_type)
    except Exception as e:
        ui_logger.error(f"代理图片失败: {e}", task_category=task_cat)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/tmdb-images", response_model=TmdbImageResponse)
def get_tmdb_images_route(req: TmdbImageRequest):
    task_cat = "API-画廊"
    try:
        logic = get_tmdb_logic()
        tmdb_id, match_response = logic.get_tmdb_id_flow(req.item_id)
        
        if tmdb_id:
            item_details = logic._get_emby_item_details(req.item_id)
            item_type_str = "tv" if item_details.get("Type") == "Series" else "movie"
            images = logic._fetch_and_sort_images(tmdb_id, item_type_str, req.image_type)
            return TmdbImageResponse(status="success", images=images)
        
        return match_response
    except Exception as e:
        ui_logger.error(f"获取TMDB图片列表({req.item_id})失败: {e}", task_category=task_cat)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/confirm-and-fetch-images", response_model=TmdbImageResponse)
def confirm_and_fetch_images_route(req: TmdbConfirmRequest, background_tasks: BackgroundTasks):
    task_cat = "API-画廊"
    try:
        logic = get_tmdb_logic()
        item_details = logic._get_emby_item_details(req.item_id)
        item_type_str = "tv" if item_details.get("Type") == "Series" else "movie"
        images = logic._fetch_and_sort_images(req.tmdb_id, item_type_str, req.image_type)
        
        background_tasks.add_task(logic.update_ids_task, req.item_id, req.tmdb_id)
        
        return TmdbImageResponse(status="success", images=images)
    except Exception as e:
        ui_logger.error(f"确认ID并获取图片({req.item_id})时失败: {e}", task_category=task_cat)
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/actors/tmdb-images-flow", response_model=ActorTmdbImageFlowResponse)
def get_actor_images_flow_route(req: ActorTmdbImageFlowRequest):
    """统一的、流程驱动的演员TMDB图片获取接口"""
    task_cat = "API-画廊"
    try:
        logic = get_tmdb_logic()
        return logic.get_actor_images_flow(req)
    except Exception as e:
        ui_logger.error(f"获取演员TMDB图片流程({req.emby_person_id})失败: {e}", task_category=task_cat, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/items/{item_id}/update-douban-id")
def update_douban_id_route(item_id: str, req: UpdateDoubanIdRequest):
    task_cat = "API-画廊"
    try:
        logic = get_logic()
        return logic.update_douban_id(item_id, req.douban_id)
    except Exception as e:
        ui_logger.error(f"更新豆瓣ID({item_id})失败: {e}", task_category=task_cat)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/combined-posters/{item_id}", response_model=CombinedImageResponse)
def get_combined_posters_route(item_id: str):
    """获取豆瓣和TMDB的合并海报列表"""
    task_cat = "API-画廊"
    try:
        logic = get_logic()
        return logic.get_combined_posters(item_id)
    except Exception as e:
        ui_logger.error(f"获取合并海报列表({item_id})失败: {e}", task_category=task_cat, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))