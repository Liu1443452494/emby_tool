# backend/file_scraper_router.py (新文件)

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from typing import Dict, List
from pydantic import BaseModel

import config as app_config
from models import FileScraperConfig
from file_scraper_logic import FileScraperLogic
from task_manager import task_manager

router = APIRouter()

@router.get("/config", response_model=FileScraperConfig)
def get_file_scraper_config():
    """获取文件刮削器配置"""
    config = app_config.load_app_config()
    return config.file_scraper_config

@router.post("/config")
def save_file_scraper_config(config: FileScraperConfig):
    """保存文件刮削器配置"""
    try:
        current_app_config = app_config.load_app_config()
        current_app_config.file_scraper_config = config
        app_config.save_app_config(current_app_config)
        return {"success": True, "message": "文件刮削器设置已保存！"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存设置时发生错误: {e}")

@router.post("/scan")
def start_scan_task():
    """启动后台扫描任务"""
    config = app_config.load_app_config()
    if not config.file_scraper_config.scan_directory:
        raise HTTPException(status_code=400, detail="请先在设置中配置扫描目录。")
    
    logic = FileScraperLogic(config)
    task_id = task_manager.register_task(
        logic.scan_directory_task,
        "文件刮削器-扫描目录"
    )
    return {"success": True, "message": "扫描任务已启动", "task_id": task_id}

class UpdateUrlsRequest(BaseModel):
    file_path: str
    urls: Dict[str, str]

@router.post("/update-urls")
def update_file_urls(req: UpdateUrlsRequest):
    """更新单个文件的刮削URL并保存到缓存"""
    import os
    from file_scraper_logic import FileScraperLogic, CACHE_FILE_PATH
    from filelock import FileLock, Timeout
    import json

    task_cat = "文件刮削器-URL更新"
    config = app_config.load_app_config()
    scan_dir = config.file_scraper_config.scan_directory
    
    lock_path = CACHE_FILE_PATH + ".lock"
    try:
        with FileLock(lock_path, timeout=10):
            if not os.path.exists(CACHE_FILE_PATH):
                raise HTTPException(status_code=404, detail="缓存文件不存在，请先执行一次扫描。")
            
            with open(CACHE_FILE_PATH, 'r+', encoding='utf-8') as f:
                cache_data = json.load(f)
                
                if scan_dir not in cache_data:
                    raise HTTPException(status_code=400, detail="当前扫描目录与缓存不匹配。")
                
                if req.file_path not in cache_data[scan_dir]["files"]:
                     # 如果文件不存在，可能是新扫描出来的，创建一个空条目
                    cache_data[scan_dir]["files"][req.file_path] = {}

                cache_data[scan_dir]["files"][req.file_path]["urls"] = req.urls
                
                f.seek(0)
                json.dump(cache_data, f, ensure_ascii=False, indent=4)
                f.truncate()

        return {"success": True, "message": "URL已成功更新并保存！"}
    except Timeout:
        raise HTTPException(status_code=503, detail="无法获取缓存文件锁，请稍后再试。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新URL时发生错误: {e}")

class ScrapeRequest(BaseModel):
    file_path: str
    urls: Dict[str, str]

@router.post("/scrape")
def start_scrape_task(req: ScrapeRequest):
    """启动单个文件的刮削任务"""
    config = app_config.load_app_config()
    logic = FileScraperLogic(config)
    # 注意：这是一个快速任务，直接在当前线程执行并返回结果，不注册到task_manager
    try:
        # 模拟cancellation_event
        class MockEvent:
            def is_set(self): return False
        
        result = logic.scrape_url_task(req.file_path, req.urls, MockEvent())
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/batch-scrape")
def start_batch_scrape_task():
    """启动批量刮削后台任务"""
    config = app_config.load_app_config()
    if not config.file_scraper_config.scan_directory:
        raise HTTPException(status_code=400, detail="请先在设置中配置扫描目录。")
    
    logic = FileScraperLogic(config)
    task_id = task_manager.register_task(
        logic.batch_scrape_task,
        "文件刮削器-批量刮削"
    )
    return {"success": True, "message": "批量刮削任务已启动", "task_id": task_id}

@router.get("/media-file")
async def get_media_file(path: str = Query(...), file_type: str = Query("poster")):
    """获取本地的媒体文件，如海报或NFO"""
    config = app_config.load_app_config()
    logic = FileScraperLogic(config)
    
    file_path, mime_type = logic.get_media_file(path, file_type)

    if file_path and mime_type:
        if file_type == 'nfo':
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return Response(content=content, media_type="text/plain; charset=utf-8")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"读取NFO文件失败: {e}")
        else: # poster
            return FileResponse(file_path, media_type=mime_type)
    
    raise HTTPException(status_code=404, detail=f"未找到类型为 '{file_type}' 的文件")