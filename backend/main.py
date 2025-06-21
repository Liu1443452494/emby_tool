# backend/main.py (最终架构版)

import sys
import os
import requests
import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import json
import time

from media_selector import MediaSelector
from models import ScheduledTasksConfig
from douban_poster_updater_logic import DoubanPosterUpdaterLogic
from models import DoubanPosterUpdaterConfig
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List, Dict, Optional, Literal, Tuple
from local_extractor import extract_local_media_task
from models import LocalExtractRequest
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


from models import (
    ServerConfig, DownloadConfig, AppConfig, MediaSearchQuery, 
    DownloadRequest, BatchDownloadRequest, DoubanConfig, DoubanCacheStatus,
    ActorLocalizerConfig, ActorLocalizerPreviewRequest, ActorLocalizerApplyRequest,
    TencentApiConfig, SiliconflowApiConfig,
    TmdbConfig, ProxyConfig,
    DoubanFixerConfig,
    LocalExtractRequest,
    EmbyWebhookPayload,
    WebhookConfig

)
import config as app_config
from emby_downloader import EmbyDownloader, batch_download_task
from log_manager import setup_logging, broadcaster as log_broadcaster
from task_manager import task_manager
from genre_logic import GenreLogic
from douban_manager import scan_douban_directory_task, DOUBAN_CACHE_FILE
from actor_localizer_logic import ActorLocalizerLogic
from actor_gallery_router import router as actor_gallery_router
from douban_fixer_logic import DoubanFixerLogic
from douban_fixer_router import router as douban_fixer_router
from webhook_logic import WebhookLogic

setup_logging()
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

# --- 核心修改 1: 引入全局的异步队列和集合 ---
webhook_queue = asyncio.Queue()
# 使用集合来快速判断一个 item_id 是否已在队列中，实现高效去重
webhook_processing_set = set()
# --- 结束修改 ---

# --- 核心修改 2: 创建后台工作者函数 ---
async def webhook_worker():
    logging.info("【Webhook工作者】已启动，等待处理任务...")
    while True:
        try:
            # 从队列中获取一个任务
            item_id, item_name = await webhook_queue.get()
            
            # 注册一个可见的后台任务，方便在前端监控
            task_id = task_manager.register_task(
                _webhook_task_runner, 
                f"Webhook-自动处理-【{item_name}】",
                item_id=item_id
            )
            
            # 等待任务完成（虽然 register_task 是异步的，但我们在这里可以等待）
            # 这里的等待不是必须的，但可以确保任务真正串行
            while task_id in task_manager.tasks:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            logging.info("【Webhook工作者】收到关闭信号，正在退出...")
            break
        except Exception as e:
            logging.error(f"【Webhook工作者】处理任务时发生未知错误: {e}", exc_info=True)
            # 即使出错也继续循环，保证工作者的健壮性
            await asyncio.sleep(5)
        finally:
            # 任务处理完成后，从集合中移除
            if item_id in webhook_processing_set:
                webhook_processing_set.remove(item_id)
            # 标记队列任务已完成
            webhook_queue.task_done()

def _webhook_task_runner(item_id: str, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
    """
    这是一个简单的包装函数，用于被 TaskManager 调用。
    它会加载最新的配置并执行 WebhookLogic 的核心处理方法。
    """
    current_config = app_config.load_app_config()
    logic = WebhookLogic(current_config)
    # 注意：这里我们不再需要传递 task_manager 和 task_id，因为进度更新已不适用
    logic.process_new_media_task(item_id, cancellation_event)

# --- 结束修改 ---


def trigger_douban_refresh():
    logging.info("【调度任务】开始执行豆瓣数据强制刷新...")
    config = app_config.load_app_config()
    douban_conf = config.douban_config
    if douban_conf.directory and os.path.isdir(douban_conf.directory):
        task_manager.register_task(scan_douban_directory_task, "定时刷新豆瓣数据", douban_conf.directory, douban_conf.extra_fields)
    else:
        logging.warning("【调度任务】未配置有效的豆瓣目录，跳过定时刷新。")

def trigger_douban_fixer_scan():
    logging.info("【调度任务】开始执行豆瓣ID修复器全量扫描...")
    config = app_config.load_app_config()
    for task in task_manager.get_all_tasks():
        if task['name'].startswith("豆瓣ID修复"):
            logging.warning("【调度任务】检测到已有豆瓣ID修复任务正在运行，本次调度跳过。")
            return
    logic = DoubanFixerLogic(config)
    task_manager.register_task(logic.scan_and_match_task, "豆瓣ID修复-all", "all", None, None)

def trigger_actor_localizer_apply():
    logging.info("【调度任务】开始执行演员中文化自动应用任务...")
    config = app_config.load_app_config()
    for task in task_manager.get_all_tasks():
        if task['name'].startswith("演员中文化"):
            logging.warning("【调度任务】检测到已有演员中文化任务正在运行，本次调度跳过。")
            return
    logic = ActorLocalizerLogic(config)
    task_manager.register_task(logic.apply_actor_changes_directly_task, "演员中文化-定时自动应用", config.actor_localizer_config)

def trigger_scheduled_task(task_id: str):
    logging.info(f"【调度任务】开始执行定时任务: {task_id}")
    
    config = app_config.load_app_config()
    
    scope = config.scheduled_tasks_config.target_scope
    selector = MediaSelector(config)
    item_ids = selector.get_item_ids(scope)

    if not item_ids:
        logging.info(f"【调度任务-{task_id}】未根据范围找到任何媒体项，任务结束。")
        return

    if task_id == "actor_localizer":
        logic = ActorLocalizerLogic(config)
        task_name = f"定时任务-演员中文化({scope.mode})"
        task_manager.register_task(
            logic.run_localization_for_items, 
            task_name, 
            item_ids, 
            config.actor_localizer_config
        )
    elif task_id == "douban_fixer":
        logic = DoubanFixerLogic(config)
        task_name = f"定时任务-豆瓣ID修复({scope.mode})"
        task_manager.register_task(
            logic.run_fixer_for_items,
            task_name,
            item_ids
        )

    elif task_id == "douban_poster_updater":
        logic = DoubanPosterUpdaterLogic(config)
        task_name = f"定时任务-豆瓣海报更新({scope.mode})"
        task_manager.register_task(
            logic.run_poster_update_for_items,
            task_name,
            item_ids,
            config.douban_poster_updater_config
        )
    else:
        logging.warning(f"【调度任务】未知的任务ID: {task_id}")



@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("应用启动...")
    # --- 核心修改 3: 在应用启动时，启动所有后台任务 ---
    task_manager_consumer = asyncio.create_task(task_manager.broadcast_consumer())
    webhook_worker_task = asyncio.create_task(webhook_worker())
    # --- 结束修改 ---

    config = app_config.load_app_config()
    
    douban_conf = config.douban_config
    if douban_conf.directory and os.path.isdir(douban_conf.directory):
        if not os.path.exists(DOUBAN_CACHE_FILE):
            logging.info("【启动检查】未发现豆瓣缓存文件，将自动执行首次扫描。")
            task_manager.register_task(scan_douban_directory_task, "首次启动豆瓣扫描", douban_conf.directory, douban_conf.extra_fields)
        else:
            logging.info(f"【启动检查】已找到豆瓣缓存文件: {DOUBAN_CACHE_FILE}，跳过自动扫描。")
    else:
        logging.warning("【启动检查】未配置有效的豆瓣目录，无法执行扫描。")

    if douban_conf.refresh_cron:
        try:
            scheduler.add_job(trigger_douban_refresh, CronTrigger.from_crontab(douban_conf.refresh_cron), id="douban_refresh_job", replace_existing=True)
            logging.info(f"【调度任务】已成功设置豆瓣数据定时刷新任务，CRON表达式: '{douban_conf.refresh_cron}'")
        except Exception as e:
            logging.error(f"【调度任务】设置定时刷新任务失败，CRON表达式可能无效: {e}")

    fixer_conf = config.douban_fixer_config
    if fixer_conf.scan_cron:
        try:
            scheduler.add_job(trigger_douban_fixer_scan, CronTrigger.from_crontab(fixer_conf.scan_cron), id="douban_fixer_scan_job", replace_existing=True)
            logging.info(f"【调度任务】已成功设置豆瓣ID修复器定时扫描任务，CRON表达式: '{fixer_conf.scan_cron}'")
        except Exception as e:
            logging.error(f"【调度任务】设置豆瓣ID修复器定时扫描任务失败，CRON表达式可能无效: {e}")

    actor_conf = config.actor_localizer_config
    if actor_conf.apply_cron:
        try:
            scheduler.add_job(trigger_actor_localizer_apply, CronTrigger.from_crontab(actor_conf.apply_cron), id="actor_localizer_apply_job", replace_existing=True)
            logging.info(f"【调度任务】已成功设置演员中文化自动应用任务，CRON表达式: '{actor_conf.apply_cron}'")
        except Exception as e:
            logging.error(f"【调度任务】设置演员中文化自动应用任务失败，CRON表达式可能无效: {e}")
    
    logging.info("【调度任务】开始设置通用定时任务...")
    scheduled_conf = config.scheduled_tasks_config
    for task in scheduled_conf.tasks:
        if task.enabled and task.cron:
            try:
                scheduler.add_job(
                    trigger_scheduled_task, 
                    CronTrigger.from_crontab(task.cron), 
                    id=f"scheduled_{task.id}", 
                    replace_existing=True,
                    args=[task.id]
                )
                logging.info(f"  - 已成功设置定时任务 '{task.name}'，CRON表达式: '{task.cron}'")
            except Exception as e:
                logging.error(f"  - 设置定时任务 '{task.name}' 失败，CRON表达式可能无效: {e}")

    if not scheduler.running:
        scheduler.start()

    yield
    
    logging.info("应用关闭，正在停止后台服务...")
    
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logging.info("APScheduler 已被指令关闭。")

    # --- 核心修改 4: 在应用关闭时，优雅地取消后台任务 ---
    webhook_worker_task.cancel()
    task_manager_consumer.cancel()
    await asyncio.gather(webhook_worker_task, task_manager_consumer, return_exceptions=True)
    logging.info("所有后台任务已成功取消。")
    # --- 结束修改 ---

app = FastAPI(lifespan=lifespan)
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(actor_gallery_router, prefix="/api/gallery")
app.include_router(douban_fixer_router, prefix="/api/douban-fixer")

# ... (其他路由保持不变) ...
@app.get("/api/image-proxy")
async def image_proxy(url: str):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
            'Referer': 'https://movie.douban.com/'
        }
        response = requests.get(url, headers=headers, stream=True, timeout=20)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', 'image/jpeg')
        if not content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="URL did not point to a valid image.")

        return Response(content=response.content, media_type=content_type)
    except requests.RequestException as e:
        logging.error(f"【图片代理】请求外部图片失败: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch image from external URL: {e}")

@app.websocket("/ws/logs")
async def websocket_logs_endpoint(websocket: WebSocket):
    await log_broadcaster.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        log_broadcaster.disconnect(websocket)
        logging.info("日志 WebSocket 客户端断开连接。")
@app.websocket("/ws/tasks")
async def websocket_tasks_endpoint(websocket: WebSocket):
    await task_manager.broadcaster.connect(websocket)
    await websocket.send_json(task_manager.get_all_tasks())
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        task_manager.broadcaster.disconnect(websocket)
        logging.info("任务 WebSocket 客户端断开连接。")

@app.get("/api/emby-image-proxy")
async def emby_image_proxy(path: str):
    try:
        config = app_config.load_app_config()
        server_conf = config.server_config
        if not server_conf.server:
            raise HTTPException(status_code=400, detail="Emby server not configured.")
        full_url = f"{server_conf.server}/{path}"
        logging.info(f"【Emby图片代理】正在代理请求: {full_url}")
        req = requests.get(full_url, stream=True, timeout=20)
        req.raise_for_status()
        content_type = req.headers.get('Content-Type', 'image/jpeg')
        return Response(content=req.content, media_type=content_type)
    except requests.exceptions.RequestException as e:
        logging.error(f"【Emby图片代理】请求 Emby 图片失败: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch image from Emby server.")
    except Exception as e:
        logging.error(f"【Emby图片代理】发生未知错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def read_root(): return {"message": "欢迎来到 Emby 工具箱后端!"}
@app.get("/api/config", response_model=AppConfig)
def get_app_config_api():
    config = app_config.load_app_config()
    is_scanning = any("豆瓣" in task['name'] for task in task_manager.get_all_tasks())
    if not os.path.exists(DOUBAN_CACHE_FILE):
        status = DoubanCacheStatus(exists=False, item_count=0, last_modified=None, is_scanning=is_scanning)
    else:
        try:
            mtime = os.path.getmtime(DOUBAN_CACHE_FILE)
            last_modified = datetime.fromtimestamp(mtime).isoformat()
            with open(DOUBAN_CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            item_count = len(data)
            status = DoubanCacheStatus(exists=True, item_count=item_count, last_modified=last_modified, is_scanning=is_scanning)
        except Exception:
            status = DoubanCacheStatus(exists=True, item_count=0, last_modified=None, is_scanning=is_scanning)
    config.douban_cache_status = status
    return config
@app.post("/api/config/server")
def save_server_config_api(server_config: ServerConfig):
    try:
        logging.info("正在测试并保存 Emby 服务器配置...")
        current_app_config = app_config.load_app_config()
        proxies = {}
        if current_app_config.proxy_config.enabled and current_app_config.proxy_config.url:
            proxy_url = current_app_config.proxy_config.url
            proxies = {'http': proxy_url, 'https': proxy_url}
            logging.info(f"【连接测试】将通过代理 {proxy_url} 连接 Emby 服务器。")
        test_url = f"{server_config.server}/Users/{server_config.user_id}"
        params = {"api_key": server_config.api_key}
        response = requests.get(test_url, params=params, timeout=15, proxies=proxies)
        response.raise_for_status()
        user_data = response.json()
        if not user_data.get("Name"): raise ValueError("服务器响应异常，未找到有效的用户信息。")
        system_info_url = f"{server_config.server}/System/Info"
        response_system = requests.get(system_info_url, params=params, timeout=15, proxies=proxies)
        response_system.raise_for_status()
        system_info = response_system.json()
        current_app_config.server_config = server_config
        app_config.save_app_config(current_app_config)
        logging.info("Emby 服务器配置保存成功！")
        return {"success": True, "message": "配置已保存，连接成功！", "details": {"serverName": system_info.get("ServerName", "未知"), "serverVersion": system_info.get("Version", "未知"), "userName": user_data.get("Name", "未知")}}
    except Exception as e:
        logging.error(f"保存服务器配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@app.post("/api/config/download")
def save_download_config_api(download_config: DownloadConfig):
    try:
        logging.info("正在保存下载设置...")
        current_app_config = app_config.load_app_config()
        current_app_config.download_config = download_config
        app_config.save_app_config(current_app_config)
        logging.info("下载设置保存成功！")
        return {"success": True, "message": "下载设置已保存！"}
    except Exception as e:
        logging.error(f"保存下载设置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存下载设置时发生错误: {e}")
@app.post("/api/config/proxy")
def save_proxy_config_api(proxy_config: ProxyConfig):
    try:
        logging.info(f"正在保存代理设置: {proxy_config.model_dump_json()}")
        if proxy_config.url and not (proxy_config.url.startswith("http://") or proxy_config.url.startswith("https://")):
             raise ValueError("代理地址格式不正确，必须以 http:// 或 https:// 开头。")
        current_app_config = app_config.load_app_config()
        current_app_config.proxy_config = proxy_config
        app_config.save_app_config(current_app_config)
        logging.info("代理设置保存成功！")
        return {"success": True, "message": "代理设置已保存！"}
    except Exception as e:
        logging.error(f"保存代理设置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存代理设置时发生错误: {e}")
@app.post("/api/config/proxy/test")
def test_proxy_config_api(proxy_config: ProxyConfig):
    if not proxy_config.enabled:
        logging.info("【代理测试】代理未启用，跳过测试。")
        return {"success": True, "message": "代理未启用，无需测试。"}
    proxy_url = proxy_config.url
    if not proxy_url:
        raise HTTPException(status_code=400, detail="代理已启用，但代理地址不能为空。")
    if not (proxy_url.startswith("http://") or proxy_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="代理地址格式不正确，必须以 http:// 或 https:// 开头。")
    logging.info(f"【代理测试】开始测试，将通过代理 '{proxy_url}' 连接外部网络...")
    proxies = {'http': proxy_url, 'https': proxy_url}
    test_target_url = "https://www.baidu.com" 
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'}
    try:
        start_time = time.perf_counter()
        response = requests.head(test_target_url, proxies=proxies, headers=headers, timeout=10, allow_redirects=True)
        end_time = time.perf_counter()
        latency_ms = (end_time - start_time) * 1000
        response.raise_for_status()
        success_msg = f"代理连接成功！能够访问 {test_target_url}。"
        logging.info(f"【代理测试】成功！服务器返回状态码: {response.status_code}。延迟: {latency_ms:.2f} ms。")
        return {"success": True, "message": success_msg, "latency": f"{latency_ms:.2f} ms"}
    except requests.exceptions.ProxyError as e:
        logging.error(f"【代理测试】失败！代理错误: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"代理服务器错误，请检查地址和端口是否正确，以及代理服务是否正常运行。")
    except requests.exceptions.ConnectTimeout:
        logging.error(f"【代理测试】失败！连接代理服务器超时。")
        raise HTTPException(status_code=500, detail="连接代理服务器超时，请检查网络或代理设置。")
    except requests.exceptions.RequestException as e:
        logging.error(f"【代理测试】失败！发生网络请求异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"通过代理访问外部网络失败，请检查代理是否能访问公网。错误: {e}")
    except Exception as e:
        logging.error(f"【代理测试】失败！发生未知错误: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"发生未知错误: {e}")
@app.post("/api/config/tmdb")
def save_and_test_tmdb_config_api(tmdb_config: TmdbConfig):
    try:
        logging.info(f"正在测试 TMDB API Key...")
        current_app_config = app_config.load_app_config()
        proxies = {}
        if current_app_config.proxy_config.enabled and current_app_config.proxy_config.url:
            proxy_url = current_app_config.proxy_config.url
            proxies = {'http': proxy_url, 'https': proxy_url}
            logging.info(f"【TMDB测试】将通过代理 {proxy_url} 连接 TMDB。")
        if tmdb_config.custom_api_domain_enabled and tmdb_config.custom_api_domain:
            base_domain = tmdb_config.custom_api_domain.rstrip('/')
            logging.info(f"【TMDB测试】使用自定义API域名: {base_domain}")
        else:
            base_domain = "https://api.themoviedb.org"
            logging.info(f"【TMDB测试】使用默认API域名: {base_domain}")
        test_url = f"{base_domain}/3/configuration"
        params = {"api_key": tmdb_config.api_key}
        response = requests.get(test_url, params=params, timeout=10, proxies=proxies)
        if response.status_code == 401:
            logging.error("【TMDB测试】TMDB API Key 测试失败: 无效的 Key。")
            raise HTTPException(status_code=500, detail="TMDB API Key 无效或已过期。")
        response.raise_for_status()
        logging.info("【TMDB测试】TMDB API Key 测试成功！")
        logging.info("正在保存 TMDB 配置...")
        current_app_config.tmdb_config = tmdb_config
        app_config.save_app_config(current_app_config)
        logging.info("TMDB 配置已保存。")
        return {"success": True, "message": "TMDB 配置已保存，API Key 有效！"}
    except HTTPException as e:
        raise e
    except requests.exceptions.RequestException as e:
        logging.error(f"【TMDB测试】TMDB API 测试失败: 网络请求错误: {e}")
        raise HTTPException(status_code=500, detail=f"无法连接到 TMDB 服务，请检查网络、代理或自定义域名设置。")
    except Exception as e:
        logging.error(f"【TMDB测试】保存 TMDB 配置时发生未知错误: {e}")
        raise HTTPException(status_code=500, detail=f"处理 TMDB 配置时发生未知错误: {e}")
@app.post("/api/config/douban")
def save_douban_config_api(douban_config: DoubanConfig):
    try:
        logging.info("正在保存豆瓣数据源设置...")
        current_app_config = app_config.load_app_config()
        current_app_config.douban_config = douban_config
        app_config.save_app_config(current_app_config)
        if scheduler.running:
            existing_job = scheduler.get_job("douban_refresh_job")
            if existing_job:
                scheduler.remove_job("douban_refresh_job")
            if douban_config.refresh_cron:
                try:
                    scheduler.add_job(trigger_douban_refresh, CronTrigger.from_crontab(douban_config.refresh_cron), id="douban_refresh_job", replace_existing=True)
                    logging.info(f"【调度任务】已更新定时刷新任务，新CRON表达式: '{douban_config.refresh_cron}'")
                except Exception as e:
                    logging.error(f"【调度任务】更新定时任务失败: {e}")
                    raise HTTPException(status_code=400, detail=f"CRON表达式无效: {e}")
        logging.info("豆瓣数据源设置保存成功！")
        return {"success": True, "message": "豆瓣设置已保存！目录修改将在下次刷新或重启后生效。"}
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"保存豆瓣设置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存豆瓣设置时发生错误: {e}")

@app.post("/api/config/douban-fixer")
def save_douban_fixer_config_api(config: DoubanFixerConfig):
    try:
        logging.info("正在保存豆瓣ID修复器设置...")
        current_app_config = app_config.load_app_config()
        current_app_config.douban_fixer_config = config
        app_config.save_app_config(current_app_config)
        
        if scheduler.running:
            job_id = "douban_fixer_scan_job"
            existing_job = scheduler.get_job(job_id)
            if existing_job:
                scheduler.remove_job(job_id)
                logging.info(f"【调度任务】已移除旧的豆瓣ID修复器任务。")
            if config.scan_cron:
                try:
                    scheduler.add_job(trigger_douban_fixer_scan, CronTrigger.from_crontab(config.scan_cron), id=job_id, replace_existing=True)
                    logging.info(f"【调度任务】已更新豆瓣ID修复器定时扫描任务，新CRON表达式: '{config.scan_cron}'")
                except Exception as e:
                    logging.error(f"【调度任务】更新豆瓣ID修复器任务失败: {e}")
                    raise HTTPException(status_code=400, detail=f"CRON表达式无效: {e}")

        logging.info("豆瓣ID修复器设置保存成功！")
        return {"success": True, "message": "豆瓣ID修复器设置已保存！"}
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"保存豆瓣ID修复器设置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存设置时发生错误: {e}")

@app.post("/api/douban/force-refresh")
def force_refresh_douban_data_api():
    config = app_config.load_app_config()
    douban_conf = config.douban_config
    if not douban_conf.directory or not os.path.isdir(douban_conf.directory):
        raise HTTPException(status_code=400, detail="请先在配置页面设置一个有效的豆瓣数据根目录。")
    task_id = task_manager.register_task(scan_douban_directory_task, "手动强制刷新豆瓣数据", douban_conf.directory, douban_conf.extra_fields)
    return {"status": "success", "message": "强制刷新任务已启动，请在“运行任务”页面查看进度。", "task_id": task_id}
LOG_FILE = os.path.join('/app/data', "app.log")

@app.get("/api/logs")
def get_logs_api(page: int = Query(1, ge=1), page_size: int = Query(100, ge=1)):
    if not os.path.exists(LOG_FILE):
        return {"total": 0, "logs": []}
    
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        total_logs = len(lines)
        start_index = total_logs - ((page - 1) * page_size) - 1
        end_index = start_index - page_size
        
        paginated_logs = []
        for i in range(start_index, end_index, -1):
            if i < 0:
                break
            paginated_logs.append(lines[i].strip())
            
        return {"total": total_logs, "logs": paginated_logs}
    except Exception as e:
        logging.error(f"读取日志文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"读取日志文件失败: {e}")

@app.delete("/api/logs")
def clear_logs_api():
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("")
        logging.info("日志文件已被用户清空。")
        return {"success": True, "message": "日志已清空"}
    except Exception as e:
        logging.error(f"清空日志文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"清空日志失败: {e}")
    
@app.get("/api/media/libraries")
def get_libraries_api():
    config = app_config.load_app_config()
    server_conf = config.server_config
    if not all([server_conf.server, server_conf.api_key, server_conf.user_id]): raise HTTPException(status_code=400, detail="Emby服务器未配置")
    try:
        logging.info(f"正在从 {server_conf.server} 获取媒体库列表...")
        url = f"{server_conf.server}/Users/{server_conf.user_id}/Views"
        proxies = {}
        if config.proxy_config.enabled and config.proxy_config.url:
            proxy_url = config.proxy_config.url
            proxies = {'http': proxy_url, 'https': proxy_url}
        response = requests.get(url, params={"api_key": server_conf.api_key}, timeout=15, proxies=proxies)
        response.raise_for_status()
        views = response.json().get("Items", [])
        libraries = [{"id": v["Id"], "name": v["Name"]} for v in views if v.get("CollectionType") in ["movies", "tvshows", "homevideos", "music"]]
        logging.info(f"成功获取到 {len(libraries)} 个媒体库。")
        return libraries
    except Exception as e:
        logging.error(f"获取媒体库列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取媒体库列表时出错: {e}")
@app.post("/api/media/search")
def search_media_api(query: MediaSearchQuery):
    config = app_config.load_app_config()
    server_conf = config.server_config
    if not all([server_conf.server, server_conf.api_key, server_conf.user_id]): raise HTTPException(status_code=400, detail="Emby服务器未配置")
    logging.info(f"正在搜索媒体: '{query.query}'")
    url = f"{server_conf.server}/Users/{server_conf.user_id}/Items"
    params = {"api_key": server_conf.api_key, "Recursive": "true", "IncludeItemTypes": "Movie,Series", "SearchTerm": query.query, "Fields": "ProviderIds,ProductionYear,Genres"}
    try:
        proxies = {}
        if config.proxy_config.enabled and config.proxy_config.url:
            proxy_url = config.proxy_config.url
            proxies = {'http': proxy_url, 'https': proxy_url}
        response = requests.get(url, params=params, timeout=20, proxies=proxies)
        response.raise_for_status()
        items = response.json().get("Items", [])
        if not items and query.query.isdigit():
            try:
                item_url = f"{server_conf.server}/Users/{server_conf.user_id}/Items/{query.query}"
                item_params = { "api_key": server_conf.api_key, "Fields": "ProviderIds,ProductionYear,Genres" }
                item_resp = requests.get(item_url, params=item_params, timeout=10, proxies=proxies)
                if item_resp.ok: items = [item_resp.json()]
            except Exception: pass
        logging.info(f"搜索到 {len(items)} 个结果。")
        return items
    except Exception as e:
        logging.error(f"搜索媒体时出错: {e}")
        raise HTTPException(status_code=500, detail=f"搜索媒体时出错: {e}")
@app.get("/api/media/debug-item/{item_id}")
def debug_get_item_details(item_id: str):
    config = app_config.load_app_config()
    server_conf = config.server_config
    if not all([server_conf.server, server_conf.api_key, server_conf.user_id]):
        raise HTTPException(status_code=400, detail="Emby服务器未配置")
    logging.info(f"【调试】开始获取 Item ID: {item_id} 的完整数据...")
    url = f"{server_conf.server}/Users/{server_conf.user_id}/Items/{item_id}"
    params = {"api_key": server_conf.api_key}
    try:
        proxies = {}
        if config.proxy_config.enabled and config.proxy_config.url:
            proxy_url = config.proxy_config.url
            proxies = {'http': proxy_url, 'https': proxy_url}
        response = requests.get(url, params=params, timeout=20, proxies=proxies)
        response.raise_for_status()
        data = response.json()
        logging.info(f"【调试】成功获取 Item ID: {item_id} 的数据。")
        return data
    except requests.RequestException as e:
        logging.error(f"【调试】获取 Item ID: {item_id} 数据时发生网络错误: {e}")
        raise HTTPException(status_code=500, detail=f"请求Emby服务器失败: {e}")
    except Exception as e:
        logging.error(f"【调试】获取 Item ID: {item_id} 数据时发生未知错误: {e}")
        raise HTTPException(status_code=500, detail=f"发生未知错误: {e}")
@app.post("/api/media/download-item")
def download_single_item_api(req: DownloadRequest):
    config = app_config.load_app_config()
    if not config.download_config.download_directory: raise HTTPException(status_code=400, detail="下载目录未配置")
    logging.info(f"收到单项下载请求: Item ID={req.item_id}, 内容={req.content_types}")
    try:
        downloader = EmbyDownloader(config)
        result = downloader.download_for_item(req.item_id, req.content_types)
        return {"status": "success", "message": "下载任务完成", "details": result}
    except Exception as e:
        logging.error(f"单项下载失败: {e}")
        raise HTTPException(status_code=500, detail=f"下载时发生错误: {e}")
@app.post("/api/media/batch-download")
async def batch_download_api(req: BatchDownloadRequest):
    config = app_config.load_app_config()
    if not config.download_config.download_directory: raise HTTPException(status_code=400, detail="下载目录未配置")
    task_name = f"批量下载 ({req.mode})"
    task_id = task_manager.register_task(batch_download_task, task_name, config, req)
    return {"status": "success", "message": "批量下载任务已成功启动", "task_id": task_id}
@app.get("/api/tasks")
def get_tasks_api(): return task_manager.get_all_tasks()
@app.post("/api/tasks/{task_id}/cancel")
def cancel_task_api(task_id: str):
    if task_manager.cancel_task(task_id): return {"status": "success", "message": f"任务 {task_id} 正在取消中。"}
    else: raise HTTPException(status_code=404, detail=f"任务 {task_id} 未找到或已结束。")
class GenreMapping(BaseModel):
    mapping: Dict[str, str]
class GenrePreviewRequest(BaseModel):
    mapping: Dict[str, str]
    mode: Literal["byType", "byLibrary", "all"]
    media_type: Optional[Literal["Movie", "Series"]] = None
    library_ids: Optional[List[str]] = None
    blacklist: Optional[str] = None
class GenreApplyRequest(BaseModel):
    items_to_apply: List[Dict]

@app.post("/api/media/extract-local")
async def extract_local_media_api(req: LocalExtractRequest):
    config = app_config.load_app_config()
    if not config.download_config.download_directory:
        raise HTTPException(status_code=400, detail="全局下载目录未配置，请先在“Emby配置”页面设置。")
    if not os.path.isdir(req.source_path):
        raise HTTPException(status_code=400, detail=f"指定的源目录 '{req.source_path}' 无效或不存在。")
    
    task_name = f"本地提取 ({os.path.basename(req.source_path)})"
    task_id = task_manager.register_task(
        extract_local_media_task,
        task_name,
        config,
        req
    )
    return {"status": "success", "message": "本地提取任务已启动", "task_id": task_id}

@app.get("/api/genres")
def get_all_genres():
    config = app_config.load_app_config()
    logic = GenreLogic(config)
    return logic.get_all_genres()
@app.get("/api/genres/standard-mapping")
def get_standard_genre_mapping():
    config = app_config.load_app_config()
    return getattr(config, 'genre_mapping', {})
@app.post("/api/genres/standard-mapping")
def save_standard_genre_mapping(mapping: GenreMapping):
    try:
        config = app_config.load_app_config()
        config.genre_mapping = mapping.mapping
        app_config.save_app_config(config)
        logging.info("标准类型映射规则已保存。")
        return {"status": "success", "message": "映射规则已保存"}
    except Exception as e:
        logging.error(f"保存标准映射时出错: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@app.post("/api/genres/preview")
def preview_genre_changes(req: GenrePreviewRequest):
    config = app_config.load_app_config()
    logic = GenreLogic(config)
    task_name = f"预览类型替换 ({req.mode})"
    task_id = task_manager.register_task(
        logic.preview_changes_task,
        task_name,
        req.mapping, req.mode, req.media_type, req.library_ids, req.blacklist
    )
    return {"status": "success", "message": "预览任务已启动", "task_id": task_id}
@app.post("/api/genres/apply")
def apply_genre_changes(req: GenreApplyRequest):
    config = app_config.load_app_config()
    logic = GenreLogic(config)
    task_name = f"应用类型替换 (共 {len(req.items_to_apply)} 项)"
    task_id = task_manager.register_task(
        logic.apply_changes_task,
        task_name,
        req.items_to_apply
    )
    return {"status": "success", "message": "应用类型替换任务已启动", "task_id": task_id}
@app.post("/api/config/actor-localizer")
def save_actor_localizer_config_api(config: ActorLocalizerConfig):
    try:
        logging.info("正在保存演员中文化设置...")
        current_app_config = app_config.load_app_config()
        current_app_config.actor_localizer_config = config
        app_config.save_app_config(current_app_config)
        
        if scheduler.running:
            job_id = "actor_localizer_apply_job"
            existing_job = scheduler.get_job(job_id)
            if existing_job:
                scheduler.remove_job(job_id)
                logging.info(f"【调度任务】已移除旧的演员中文化自动应用任务。")
            if config.apply_cron:
                try:
                    scheduler.add_job(trigger_actor_localizer_apply, CronTrigger.from_crontab(config.apply_cron), id=job_id, replace_existing=True)
                    logging.info(f"【调度任务】已更新演员中文化自动应用任务，新CRON表达式: '{config.apply_cron}'")
                except Exception as e:
                    logging.error(f"【调度任务】更新演员中文化任务失败: {e}")
                    raise HTTPException(status_code=400, detail=f"CRON表达式无效: {e}")

        logging.info("演员中文化设置保存成功！")
        return {"success": True, "message": "演员中文化设置已保存！"}
    except Exception as e:
        logging.error(f"保存演员中文化设置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存演员中文化设置时发生错误: {e}")
@app.post("/api/actor-localizer/preview")
def preview_actor_changes_api(req: ActorLocalizerPreviewRequest):
    config = app_config.load_app_config()
    logic = ActorLocalizerLogic(config)
    task_name = f"预览演员中文化 ({req.target.scope})"
    task_id = task_manager.register_task(
        logic.preview_actor_changes_task,
        task_name,
        req.target,
        req.config
    )
    return {"status": "success", "message": "演员中文化预览任务已启动", "task_id": task_id}
@app.post("/api/actor-localizer/apply")
def apply_actor_changes_api(req: ActorLocalizerApplyRequest):
    config = app_config.load_app_config()
    logic = ActorLocalizerLogic(config)
    task_name = f"应用演员中文化 (共 {len(req.items)} 项)"
    task_id = task_manager.register_task(
        logic.apply_actor_changes_task,
        task_name,
        req.items
    )
    return {"status": "success", "message": "应用演员中文化任务已启动", "task_id": task_id}

@app.post("/api/actor-localizer/apply-directly")
def apply_actor_changes_directly_api():
    config = app_config.load_app_config()
    for task in task_manager.get_all_tasks():
        if task['name'].startswith("演员中文化"):
            raise HTTPException(status_code=409, detail=f"已有演员中文化任务(ID: {task['id']})正在运行，请勿重复启动。")
    
    logic = ActorLocalizerLogic(config)
    task_name = "演员中文化-手动触发自动应用"
    task_id = task_manager.register_task(
        logic.apply_actor_changes_directly_task,
        task_name,
        config.actor_localizer_config
    )
    return {"status": "success", "message": "自动应用任务已启动", "task_id": task_id}

class TestTranslationRequest(BaseModel):
    mode: Literal["tencent", "siliconflow"]
    config: Dict
@app.post("/api/actor-localizer/test-translation")
def test_translation_api(req: TestTranslationRequest):
    try:
        logic = ActorLocalizerLogic(app_config.load_app_config())
        text_to_test = "John Doe"
        translated_text = ""
        if req.mode == "tencent":
            logging.info("正在测试腾讯云翻译API...")
            api_config = TencentApiConfig(**req.config)
            translated_text = logic.translate_with_tencent_api(text_to_test, api_config)
        elif req.mode == "siliconflow":
            logging.info("正在测试SiliconFlow API...")
            api_config = SiliconflowApiConfig(**req.config)
            translated_text = logic.translate_with_siliconflow_api(text_to_test, api_config)
        if translated_text and translated_text != text_to_test:
            return {"success": True, "message": f"测试成功！翻译结果: '{translated_text}'"}
        else:
            raise Exception("翻译结果为空或与原文相同，请检查配置或API权限。")
    except Exception as e:
        logging.error(f"翻译API测试失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/api/config/scheduled-tasks")
def save_scheduled_tasks_config_api(config: ScheduledTasksConfig):
    try:
        logging.info("正在保存通用定时任务设置...")
        current_app_config = app_config.load_app_config()
        current_app_config.scheduled_tasks_config = config
        app_config.save_app_config(current_app_config)

        if scheduler.running:
            logging.info("【调度任务】检测到配置变更，正在更新调度器...")
            for task in config.tasks:
                job_id = f"scheduled_{task.id}"
                existing_job = scheduler.get_job(job_id)
                if task.enabled and task.cron:
                    try:
                        scheduler.add_job(
                            trigger_scheduled_task,
                            CronTrigger.from_crontab(task.cron),
                            id=job_id,
                            replace_existing=True,
                            args=[task.id]
                        )
                        logging.info(f"  - 已更新/添加任务 '{task.name}' (CRON: {task.cron})")
                    except Exception as e:
                        logging.error(f"  - 更新任务 '{task.name}' 失败: {e}")
                elif existing_job:
                    scheduler.remove_job(job_id)
                    logging.info(f"  - 已移除禁用的任务 '{task.name}'")

        logging.info("通用定时任务设置保存成功！")
        return {"success": True, "message": "定时任务设置已保存！"}
    except Exception as e:
        logging.error(f"保存通用定时任务设置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存设置时发生错误: {e}")
    
@app.post("/api/scheduled-tasks/{task_id}/trigger")
def trigger_scheduled_task_once_api(task_id: str):
    logging.info(f"【API接口】收到立即执行任务的请求: {task_id}")
    config = app_config.load_app_config()
    defined_tasks = {task.id for task in config.scheduled_tasks_config.tasks}
    if task_id not in defined_tasks:
        raise HTTPException(status_code=404, detail=f"未找到ID为 '{task_id}' 的定时任务定义。")

    task_name_map = {
        "actor_localizer": "演员中文化",
        "douban_fixer": "豆瓣ID修复器"
    }
    task_display_name = task_name_map.get(task_id)
    if task_display_name:
        for task in task_manager.get_all_tasks():
            if task['name'].startswith(f"定时任务-{task_display_name}"):
                 raise HTTPException(status_code=409, detail=f"已有同类定时任务(ID: {task['id']})正在运行，请勿重复启动。")

    try:
        trigger_scheduled_task(task_id)
        return {"status": "success", "message": f"任务 '{task_id}' 已成功触发，请在“运行任务”页面查看进度。"}
    except Exception as e:
        logging.error(f"手动触发定时任务 '{task_id}' 时失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"触发任务时发生内部错误: {e}")

@app.post("/api/config/douban-poster-updater")
def save_douban_poster_updater_config_api(config: DoubanPosterUpdaterConfig):
    try:
        logging.info("正在保存豆瓣海报更新器设置...")
        current_app_config = app_config.load_app_config()
        current_app_config.douban_poster_updater_config = config
        app_config.save_app_config(current_app_config)
        logging.info("豆瓣海报更新器设置保存成功！")
        return {"success": True, "message": "设置已保存！"}
    except Exception as e:
        logging.error(f"保存豆瓣海报更新器设置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存设置时发生错误: {e}")
    

@app.post("/api/config/webhook")
def save_webhook_config_api(config: WebhookConfig):
    try:
        logging.info("正在保存 Webhook 设置...")
        current_app_config = app_config.load_app_config()
        current_app_config.webhook_config = config
        app_config.save_app_config(current_app_config)
        logging.info("Webhook 设置保存成功！")
        return {"success": True, "message": "设置已保存！"}
    except Exception as e:
        logging.error(f"保存 Webhook 设置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存设置时发生错误: {e}")

# --- 核心修改 5: 重构 Webhook 接收器，使其将任务放入队列 ---
@app.post("/api/webhook/emby")
async def emby_webhook_receiver(payload: EmbyWebhookPayload):
    try:
        payload_json_str = payload.model_dump_json(indent=4, exclude_unset=True)
        logging.info(f"【Webhook调试】收到来自 Emby 的完整 Payload 内容:\n{payload_json_str}")
    except Exception as e:
        logging.error(f"【Webhook调试】打印 Payload 时发生错误: {e}")

    logging.info(f"【Webhook】收到来自 Emby 的通知，事件: {payload.Event}")
    
    config = app_config.load_app_config()
    if not config.webhook_config.enabled:
        logging.info("【Webhook】Webhook 功能未启用，跳过处理。")
        return {"status": "skipped", "message": "Webhook processing is disabled."}

    if not payload.Item:
        logging.info("【Webhook】收到的通知中不包含有效的 Item 信息，可能是测试通知或无关事件，已成功接收并跳过。")
        return {"status": "success_test_skipped", "message": "Test notification received successfully."}

    target_item_id = None
    target_item_name = payload.Item.Name
    target_item_type = payload.Item.Type

    if payload.Event in ["item.add", "library.new"]:
        if target_item_type in ["Movie", "Series"]:
            target_item_id = payload.Item.Id
            logging.info(f"【Webhook】检测到新 [电影/剧集] 入库: 【{target_item_name}】 (ID: {target_item_id})")
        
        elif target_item_type == "Episode":
            episode_id = payload.Item.Id
            logging.info(f"【Webhook】检测到新 [剧集分集] 入库: 【{target_item_name}】 (ID: {episode_id})，正在查找其所属剧集...")
            
            try:
                server_conf = config.server_config
                url = f"{server_conf.server}/Users/{server_conf.user_id}/Items/{episode_id}"
                params = {"api_key": server_conf.api_key, "Fields": "SeriesId,SeriesName"}
                response = requests.get(url, params=params, timeout=15)
                response.raise_for_status()
                episode_details = response.json()
                
                target_item_id = episode_details.get("SeriesId")
                if target_item_id:
                    target_item_name = episode_details.get("SeriesName", f"Series {target_item_id}")
                    logging.info(f"【Webhook】成功找到所属剧集: 【{target_item_name}】 (ID: {target_item_id})")
                else:
                    logging.warning(f"【Webhook】无法从剧集【{target_item_name}】中找到所属剧集的ID，跳过处理。")

            except requests.RequestException as e:
                logging.error(f"【Webhook】查询剧集详情失败: {e}，跳过处理。")
        
    if target_item_id:
        # 检查是否已在处理队列中
        if target_item_id in webhook_processing_set:
            logging.info(f"【Webhook】任务【{target_item_name}】(ID: {target_item_id}) 已存在于处理队列中，本次通知跳过。")
            return {"status": "skipped_in_queue", "message": "Task is already in the processing queue."}
        
        # 放入队列并更新集合
        await webhook_queue.put((target_item_id, target_item_name))
        webhook_processing_set.add(target_item_id)
        logging.info(f"【Webhook】已将任务【{target_item_name}】(ID: {target_item_id}) 添加到处理队列。当前队列长度: {webhook_queue.qsize()}")
        
        return {"status": "success_queued", "message": f"Task for item {target_item_id} has been queued."}
    
    logging.info(f"【Webhook】事件 '{payload.Event}' 或类型 '{target_item_type}' 无需处理，已跳过。")
    return {"status": "skipped", "message": "Event not applicable"}
# --- 结束修改 ---