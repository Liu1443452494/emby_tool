# backend/actor_gallery_router.py (完整代码)

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks, Form
from fastapi.responses import Response
import logging
from typing import Optional

from models import (
    AppConfig, ActorGalleryMatchRequest, ActorGalleryUploadRequest, 
    PosterUploadRequest, TmdbImageRequest, TmdbImageResponse, TmdbConfirmRequest,ActorTmdbImageFlowRequest, ActorTmdbImageFlowResponse,
    UpdateDoubanIdRequest, CombinedImageResponse, CombinedAvatarRequest, CombinedAvatarResponse
)
from actor_gallery_logic import ActorGalleryLogic
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
    try:
        logic = get_logic()
        return logic.get_library_items(library_id)
    except Exception as e:
        logging.error(f"【演员画廊】获取媒体库项目失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/actors/{item_id}")
def get_item_actors_route(item_id: str):
    try:
        logic = get_logic()
        return logic.get_item_actors(item_id)
    except Exception as e:
        logging.error(f"【演员画廊】获取演职员列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/actors/{person_id}/avatar-flow")
def avatar_flow_route(person_id: str, req: CombinedAvatarRequest, background_tasks: BackgroundTasks):
    try:
        logic = get_logic()
        # --- 核心修复：将 background_tasks 传递给 avatar_flow_logic ---
        return logic.avatar_flow_logic(person_id, req, background_tasks)
    except Exception as e:
        logging.error(f"【头像流程】执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"执行头像获取流程时发生内部错误: {e}")

@router.post("/actors/upload-from-url")
def upload_avatar_from_url_route(req: ActorGalleryUploadRequest, background_tasks: BackgroundTasks):
    try:
        logic = get_logic()
        logic.upload_image_from_url(req.person_id, req.image_url, "Primary", req.new_name, req.source)
        
        if req.source == 'tmdb' and req.tmdb_person_id:
            tmdb_logic = get_tmdb_logic()
            background_tasks.add_task(tmdb_logic.update_person_ids_task, req.person_id, req.tmdb_person_id)

        message = "头像上传成功！"
        if req.new_name:
            message = f"头像上传成功，且演员姓名已同步更新为 '{req.new_name}'。"
        return {"status": "success", "message": message}
    except Exception as e:
        logging.error(f"【演员画廊】从URL上传头像失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/actors/{person_id}/upload-local")
async def upload_avatar_from_local_route(person_id: str, file: UploadFile = File(...), new_name: Optional[str] = Form(None)):
    try:
        logic = get_logic()
        contents = await file.read()
        logic.upload_image_from_local(person_id, contents, new_name)
        message = "本地头像上传成功！"
        if new_name:
            message = f"本地头像上传成功，且演员姓名已同步更新为 '{new_name}'。"
        return {"status": "success", "message": message}
    except Exception as e:
        logging.error(f"【演员画廊】从本地上传头像失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/items/upload-poster-from-url")
def upload_poster_from_url_route(req: PosterUploadRequest):
    try:
        logic = get_logic()
        logic.upload_image_from_url(req.item_id, req.image_url, "Primary", source=req.source)
        return {"status": "success", "message": "海报上传任务已提交至 Emby。"}
    except Exception as e:
        logging.error(f"【演员画廊】从URL上传海报失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/items/upload-backdrop-from-url")
def upload_backdrop_from_url_route(req: PosterUploadRequest):
    try:
        logic = get_logic()
        logic.upload_image_from_url(req.item_id, req.image_url, "Backdrop")
        return {"status": "success", "message": "背景图上传任务已提交至 Emby。"}
    except Exception as e:
        logging.error(f"【演员画廊】从URL上传背景图失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/items/upload-logo-from-url")
def upload_logo_from_url_route(req: PosterUploadRequest):
    try:
        logic = get_logic()
        logic.upload_image_from_url(req.item_id, req.image_url, "Logo")
        return {"status": "success", "message": "Logo上传任务已提交至 Emby。"}
    except Exception as e:
        logging.error(f"【演员画廊】从URL上传Logo失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/proxy-image")
async def proxy_image_route(image_url: str):
    try:
        logic = get_logic()
        image_data, content_type = logic.get_image_from_url(image_url)
        return Response(content=image_data, media_type=content_type)
    except Exception as e:
        logging.error(f"【演员画廊】代理图片失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/tmdb-images", response_model=TmdbImageResponse)
def get_tmdb_images_route(req: TmdbImageRequest):
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
        logging.error(f"【TMDB】获取图片列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/confirm-and-fetch-images", response_model=TmdbImageResponse)
def confirm_and_fetch_images_route(req: TmdbConfirmRequest, background_tasks: BackgroundTasks):
    try:
        logic = get_tmdb_logic()
        item_details = logic._get_emby_item_details(req.item_id)
        item_type_str = "tv" if item_details.get("Type") == "Series" else "movie"
        images = logic._fetch_and_sort_images(req.tmdb_id, item_type_str, req.image_type)
        
        background_tasks.add_task(logic.update_ids_task, req.item_id, req.tmdb_id)
        
        return TmdbImageResponse(status="success", images=images)
    except Exception as e:
        logging.error(f"【TMDB】确认ID并获取图片时失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/actors/tmdb-images-flow", response_model=ActorTmdbImageFlowResponse)
def get_actor_images_flow_route(req: ActorTmdbImageFlowRequest):
    """统一的、流程驱动的演员TMDB图片获取接口"""
    try:
        logic = get_tmdb_logic()
        return logic.get_actor_images_flow(req)
    except Exception as e:
        logging.error(f"【演员画廊】获取演员TMDB图片流程失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/items/{item_id}/update-douban-id")
def update_douban_id_route(item_id: str, req: UpdateDoubanIdRequest):
    try:
        logic = get_logic()
        return logic.update_douban_id(item_id, req.douban_id)
    except Exception as e:
        logging.error(f"【演员画廊】更新豆瓣ID失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/combined-posters/{item_id}", response_model=CombinedImageResponse)
def get_combined_posters_route(item_id: str):
    """获取豆瓣和TMDB的合并海报列表"""
    try:
        logic = get_logic()
        return logic.get_combined_posters(item_id)
    except Exception as e:
        logging.error(f"【合并海报】获取海报列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))