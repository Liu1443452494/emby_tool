import sys
import os
import requests
import httpx
import logging
import asyncio
import threading
import json
import time
import re
import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Dict, Optional, Literal, Tuple, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, Query, Path
from fastapi.responses import Response
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from task_manager import TaskManager, task_manager
from models import EpisodeRenamerConfig
from episode_renamer_router import router as episode_renamer_router
from poster_manager_router import router as poster_manager_router
from actor_role_mapper_router import router as actor_role_mapper_router
from episode_role_sync_router import router as episode_role_sync_router
from actor_avatar_mapper_router import router as actor_avatar_mapper_router
from chasing_center_router import router as chasing_center_router
from upcoming_router import router as upcoming_router
from file_scraper_router import router as file_scraper_router
from media_tagger_router import router as media_tagger_router

from media_selector import MediaSelector
from models import ScheduledTasksConfig, ScheduledTasksTargetScope
from douban_poster_updater_logic import DoubanPosterUpdaterLogic
from models import DoubanPosterUpdaterConfig, EpisodeRefresherConfig
from episode_refresher_logic import EpisodeRefresherLogic
from local_extractor import extract_local_media_task
from models import LocalExtractRequest
from models import (
    ServerConfig, DownloadConfig, AppConfig, MediaSearchQuery, 
    DownloadRequest, BatchDownloadRequest, DoubanConfig, DoubanCacheStatus,
    ActorLocalizerConfig, ActorLocalizerPreviewRequest, ActorLocalizerApplyRequest,
    SuggestRolesRequest, UpdateRolesRequest,
    TencentApiConfig, SiliconflowApiConfig,
    TmdbConfig, ProxyConfig,
    DoubanFixerConfig,
    EmbyWebhookPayload,
    PreciseScreenshotUpdateRequest,
    WebhookConfig
)
import config as app_config
from emby_downloader import EmbyDownloader, batch_download_task
from log_manager import setup_logging, broadcaster as log_broadcaster, ui_logger
from genre_logic import GenreLogic
from douban_manager import scan_douban_directory_task, DOUBAN_CACHE_FILE
from actor_localizer_logic import ActorLocalizerLogic
from actor_gallery_router import router as actor_gallery_router
from douban_fixer_logic import DoubanFixerLogic
from douban_fixer_router import router as douban_fixer_router
from webhook_logic import WebhookLogic
from proxy_manager import ProxyManager
from episode_renamer_logic import EpisodeRenamerLogic
from episode_role_sync_logic import EpisodeRoleSyncLogic

setup_logging()
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

episode_sync_queue: Dict[str, Dict[str, Any]] = {}
episode_sync_queue_lock = threading.Lock()
episode_sync_scheduler_task = None

id_map_update_request_time: Optional[float] = None
id_map_update_lock = threading.Lock()
id_map_update_scheduler_task = None

scan_and_rename_queue: Dict[str, Dict[str, Any]] = {}
scan_and_rename_queue_lock = threading.Lock()
library_scan_scheduler_task = None

main_task_completed_series: set[str] = set()

def generate_id_map_task(cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
    """
    扫描全库，生成 TMDB ID 到 Emby Item ID 的映射文件。
    """
    task_cat = "ID映射表生成"
    ui_logger.info(f"➡️ 开始扫描全库，生成 TMDB-Emby ID 映射表...", task_category=task_cat)
    
    config = app_config.load_app_config()
    selector = MediaSelector(config)
    
    all_media_scope = ScheduledTasksTargetScope(mode='all')
    all_item_ids = selector.get_item_ids(all_media_scope)

    if not all_item_ids:
        ui_logger.warning("⚠️ 未在 Emby 中找到任何媒体项，任务中止。", task_category=task_cat)
        return

    total_items = len(all_item_ids)
    task_manager.update_task_progress(task_id, 0, total_items)
    ui_logger.info(f"🔍 已获取到 {total_items} 个媒体项实例，正在批量处理...", task_category=task_cat)

    # --- 核心修改 1: 初始化 id_map ---
    id_map = {}
    processed_count = 0
    skipped_count = 0
    failed_count = 0

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_id = {executor.submit(selector._get_emby_item_details, item_id, "ProviderIds,Name,Type"): item_id for item_id in all_item_ids}
        
        for future in as_completed(future_to_id):
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务在处理中被取消。", task_category=task_cat)
                for f in future_to_id:
                    f.cancel()
                return
            
            item_id = future_to_id[future]
            try:
                details = future.result()
                provider_ids = details.get("ProviderIds", {})
                provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
                tmdb_id = provider_ids_lower.get("tmdb")
                
                # --- 核心修改 2: 获取媒体类型并构建新的带前缀的键 ---
                item_type = details.get("Type") # "Movie" or "Series"
                
                if tmdb_id and item_type:
                    prefix = 'tv' if item_type == 'Series' else 'movie'
                    map_key = f"{prefix}-{tmdb_id}"
                    
                    # 初始化键
                    if map_key not in id_map:
                        id_map[map_key] = []
                    
                    # 追加 Emby ID
                    id_map[map_key].append(item_id)
                # --- 修改结束 ---
                else:
                    item_name = details.get("Name", f"ID {item_id}")
                    reason = "缺少 TMDB ID" if not tmdb_id else "缺少媒体类型信息"
                    ui_logger.info(f"   - [跳过] 媒体【{item_name}】(ID: {item_id}) 因 {reason} 而被忽略。", task_category=task_cat)
                    skipped_count += 1
            except Exception as e:
                ui_logger.error(f"   - ❌ 处理媒体 {item_id} 时出错: {e}", task_category=task_cat)
                failed_count += 1
            
            processed_count += 1
            if processed_count % 100 == 0 or processed_count == total_items:
                task_manager.update_task_progress(task_id, processed_count, total_items)

    ID_MAP_FILE = os.path.join('/app/data', 'id_map.json')
    try:
        with open(ID_MAP_FILE, 'w', encoding='utf-8') as f:
            json.dump(id_map, f, indent=4)
        
        # --- 核心修改 3: 更新最终的日志输出 ---
        total_emby_ids_mapped = sum(len(v) for v in id_map.values())
        ui_logger.info(f"✅ 映射表生成完毕。共处理 {total_items} 个媒体项，映射 {len(id_map)} 个唯一的 TMDB-ID-类型 组合，关联 {total_emby_ids_mapped} 个Emby媒体项。跳过: {skipped_count} 项, 失败: {failed_count} 项。", task_category=task_cat)
        # --- 修改结束 ---
    except IOError as e:
        ui_logger.error(f"❌ 写入映射表文件失败: {e}", task_category=task_cat)
        raise e
    
async def id_map_update_scheduler():
    """
    独立的后台调度器，用于处理 ID 映射表更新的延迟触发任务。
    """
    task_cat = "ID映射调度器"
    logging.info(f"【{task_cat}】已启动，将每 60 秒检查一次更新请求...")
    
    while True:
        try:
            await asyncio.sleep(60) # 调度器检查周期
            
            global id_map_update_request_time
            if id_map_update_request_time is None:
                continue

            now = time.time()
            silence_duration = now - id_map_update_request_time
            
            # 检查是否有ID映射任务正在运行
            is_task_running = any("ID 映射表" in task['name'] for task in task_manager.get_all_tasks())
            if is_task_running:
                logging.info(f"【{task_cat}】⏱️ 检测到已有ID映射表生成任务正在运行，本次调度跳过，等待其完成后再重新计时。")
                continue

            if silence_duration >= 300: # 300秒 (5分钟) 静默期
                ui_logger.info(f"➡️【{task_cat}】检测到 Webhook 请求已静默 {silence_duration:.1f} 秒 (>=300s)，开始执行 ID 映射表全量更新...", task_category=task_cat)
                
                # 触发任务
                task_manager.register_task(generate_id_map_task, "Webhook触发-ID映射表更新")
                
                # 重置计时器
                with id_map_update_lock:
                    id_map_update_request_time = None
                logging.info(f"【{task_cat}】✅ 任务已派发，更新请求计时器已重置。")
            else:
                remaining_time = 300 - silence_duration
                logging.info(f"【{task_cat}】⏱️ 收到更新请求，当前已静默 {silence_duration:.1f} 秒，等待剩余 {remaining_time:.1f} 秒...")

        except asyncio.CancelledError:
            logging.info(f"【{task_cat}】收到关闭信号，正在退出...")
            break
        except Exception as e:
            logging.error(f"【{task_cat}】运行时发生未知错误: {e}", exc_info=True)
            await asyncio.sleep(120) # 发生错误时等待更长时间

# backend/main.py (函数替换)

async def library_scan_scheduler():
    """
    独立的后台调度器，用于处理媒体库文件扫描的防抖触发任务。
    在扫描前，会先处理该媒体库下待重命名的电影，并根据处理结果决定是否需要扫描。
    """
    task_cat = "媒体库扫描调度器"
    logging.info(f"【{task_cat}】已启动，将每 60 秒检查一次待处理队列...")
    
    while True:
        try:
            await asyncio.sleep(60) # 调度器检查周期
            
            now = time.time()
            ready_to_process_tasks = {}
            
            with scan_and_rename_queue_lock:
                if not scan_and_rename_queue:
                    continue

                logging.info(f"【{task_cat}】🔍 开始检查队列，当前有 {len(scan_and_rename_queue)} 个媒体库待处理...")
                
                libs_to_pop = []
                for lib_id, entry in scan_and_rename_queue.items():
                    last_update_time = entry.get('last_update', 0)
                    silence_duration = now - last_update_time
                    
                    if silence_duration >= 90: # 90秒静默期
                        logging.info(f"   - ✅ 媒体库 (ID: {lib_id}) 条件满足：静默 {silence_duration:.1f} 秒 (>=90s)。准备处理。")
                        ready_to_process_tasks[lib_id] = entry
                        libs_to_pop.append(lib_id)
                    else:
                        remaining_time = 90 - silence_duration
                        logging.info(f"   - ⏱️ 媒体库 (ID: {lib_id}) 静默时长 {silence_duration:.1f} 秒，等待剩余 {remaining_time:.1f} 秒...")

                # 从主队列中安全地弹出这些媒体库
                for lib_id in libs_to_pop:
                    scan_and_rename_queue.pop(lib_id, None)

            # 在锁外执行耗时任务
            if ready_to_process_tasks:
                config = app_config.load_app_config()
                from movie_renamer_logic import MovieRenamerLogic
                renamer_logic = MovieRenamerLogic(config)
                
                for lib_id, entry in ready_to_process_tasks.items():
                    try:
                        lib_info = renamer_logic._get_library_for_item_by_id(lib_id)
                        lib_name = lib_info.get("Name") if lib_info else f"ID {lib_id}"
                    except Exception:
                        lib_name = f"ID {lib_id}"

                    items_to_rename = entry.get('items_to_rename')
                    
                    # --- 核心修改：引入按需扫描逻辑 ---
                    should_scan = False
                    if items_to_rename:
                        # 场景1: 这是由 Webhook 触发的、带重命名任务的流程
                        ui_logger.info(f"➡️ [扫描前置任务] 检测到媒体库【{lib_name}】有 {len(items_to_rename)} 个电影待重命名，开始处理...", task_category=task_cat)
                        
                        renamed_any_file = False
                        movie_details_list = renamer_logic._get_movie_details_batch(list(items_to_rename), task_cat)
                        
                        for movie_details in movie_details_list:
                            result = renamer_logic.process_single_movie(movie_details, task_cat)
                            if result is not None:
                                renamed_any_file = True
                        
                        if renamed_any_file:
                            ui_logger.info(f"✅ [扫描决策] 检测到文件变更，将为媒体库【{lib_name}】执行扫描。", task_category=task_cat)
                            should_scan = True
                        else:
                            ui_logger.info(f"✅ [扫描决策] 所有待处理电影的文件名均合格，无需为媒体库【{lib_name}】执行扫描。", task_category=task_cat)
                    else:
                        # 场景2: 这是“纯扫描”请求
                        logging.info(f"【{task_cat}】媒体库【{lib_name}】收到一个纯扫描请求，将直接执行扫描。")
                        should_scan = True
                    
                    if should_scan:
                        renamer_logic._trigger_library_scan(lib_id, lib_name, task_cat)
                    # --- 修改结束 ---

        except asyncio.CancelledError:
            logging.info(f"【{task_cat}】收到关闭信号，正在退出...")
            break
        except Exception as e:
            logging.error(f"【{task_cat}】运行时发生未知错误: {e}", exc_info=True)
            await asyncio.sleep(120)

async def episode_sync_scheduler():
    """
    独立的后台调度器，用于处理分集角色同步的延迟触发任务。
    """
    task_cat = "分集同步调度器"
    logging.info(f"【{task_cat}】已启动，将每 60 秒检查一次待处理队列...")
    
    while True:
        try:
            await asyncio.sleep(60) # 调度器检查周期
            
            now = time.time()
            series_to_process = {}
            
            with episode_sync_queue_lock:
                if not episode_sync_queue:
                    continue

                logging.info(f"【{task_cat}】🔍 开始检查队列，当前有 {len(episode_sync_queue)} 个剧集待处理...")
                
                ready_series_ids = []
                for series_id, data in episode_sync_queue.items():
                    last_update_time = data['last_update']
                    series_name = data['series_name']
                    silence_duration = now - last_update_time
                    
                    is_silent_enough = silence_duration >= 90
                    is_main_task_done = series_id in main_task_completed_series

                    if is_silent_enough and is_main_task_done:
                        logging.info(f"   - ✅ 剧集《{series_name}》 (ID: {series_id}) 条件满足：静默 {silence_duration:.1f} 秒 (>=90s) 且主流程已完成。准备处理。")
                        ready_series_ids.append(series_id)
                    elif is_silent_enough and not is_main_task_done:
                        logging.info(f"   - ⏱️ 剧集《{series_name}》 (ID: {series_id}) 已满足静默条件，但其主流程任务（如演员中文化）尚未完成，继续等待...")
                    else: # not silent enough
                        remaining_time = 90 - silence_duration
                        logging.info(f"   - ⏱️ 剧集《{series_name}》 (ID: {series_id}) 静默时长 {silence_duration:.1f} 秒，等待剩余 {remaining_time:.1f} 秒...")

                # 从主队列和完成标记中安全地弹出这些剧集的数据
                for series_id in ready_series_ids:
                    series_to_process[series_id] = episode_sync_queue.pop(series_id)
                    if series_id in main_task_completed_series:
                        main_task_completed_series.remove(series_id)

            # 在锁外执行耗时任务
            if series_to_process:
                ui_logger.info(f"➡️ {len(series_to_process)} 个剧集已满足所有条件，开始派发精准同步任务...", task_category=task_cat)
                config = app_config.load_app_config()
                logic = EpisodeRoleSyncLogic(config)

                for series_id, data in series_to_process.items():
                    series_name = data['series_name']
                    episode_ids = list(data['episode_ids'])
                    task_name = f"精准分集角色同步 -《{series_name}》({len(episode_ids)}集)"
                    
                    task_manager.register_task(
                        logic.run_sync_for_specific_episodes,
                        task_name,
                        series_id=series_id,
                        episode_ids=episode_ids,
                        config=config.episode_role_sync_config,
                        task_category=task_name
                    )
        except asyncio.CancelledError:
            logging.info(f"【{task_cat}】收到关闭信号，正在退出...")
            break
        except Exception as e:
            logging.error(f"【{task_cat}】运行时发生未知错误: {e}", exc_info=True)
            await asyncio.sleep(120)


webhook_queue = asyncio.Queue()
webhook_processing_set = set()

async def webhook_worker():
    # Webhook 日志已在 webhook_logic.py 中处理，此处保留底层日志
    logging.info("【Webhook工作者】已启动，等待处理任务...")
    while True:
        try:
            item_id, item_name = await webhook_queue.get()
            
            task_id = task_manager.register_task(
                _webhook_task_runner, 
                f"Webhook-自动处理-【{item_name}】",
                item_id=item_id
            )
            
            while task_id in task_manager.tasks:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            logging.info("【Webhook工作者】收到关闭信号，正在退出...")
            break
        except Exception as e:
            logging.error(f"【Webhook工作者】处理任务时发生未知错误: {e}", exc_info=True)
            await asyncio.sleep(5)
        finally:
            if item_id in webhook_processing_set:
                webhook_processing_set.remove(item_id)
            webhook_queue.task_done()

def _webhook_task_runner(item_id: str, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
    current_config = app_config.load_app_config()
    logic = WebhookLogic(current_config)
    logic.process_new_media_task(item_id, cancellation_event, series_id=item_id)


def trigger_douban_refresh():
    task_cat = "定时任务-豆瓣数据"
    ui_logger.info("开始执行豆瓣数据强制刷新...", task_category=task_cat)
    config = app_config.load_app_config()
    douban_conf = config.douban_config
    if douban_conf.directory and os.path.isdir(douban_conf.directory):
        task_manager.register_task(scan_douban_directory_task, "定时刷新豆瓣数据", douban_conf.directory, douban_conf.extra_fields)
    else:
        ui_logger.warning("未配置有效的豆瓣目录，跳过定时刷新。", task_category=task_cat)

def trigger_douban_fixer_scan():
    task_cat = "定时任务-豆瓣修复"
    ui_logger.info("开始执行豆瓣ID修复器全量扫描...", task_category=task_cat)
    config = app_config.load_app_config()
    for task in task_manager.get_all_tasks():
        if task['name'].startswith("豆瓣ID修复"):
            ui_logger.warning("检测到已有豆瓣ID修复任务正在运行，本次调度跳过。", task_category=task_cat)
            return
    logic = DoubanFixerLogic(config)
    task_manager.register_task(logic.scan_and_match_task, "豆瓣ID修复-all", "all", None, None)

def trigger_actor_localizer_apply():
    task_cat = "定时任务-演员中文化"
    ui_logger.info("开始执行演员中文化自动应用任务...", task_category=task_cat)
    config = app_config.load_app_config()
    for task in task_manager.get_all_tasks():
        if task['name'].startswith("演员中文化"):
            ui_logger.warning("检测到已有演员中文化任务正在运行，本次调度跳过。", task_category=task_cat)
            return
    logic = ActorLocalizerLogic(config)
    task_manager.register_task(logic.apply_actor_changes_directly_task, "演员中文化-定时自动应用", config.actor_localizer_config)

def _episode_refresher_task_runner(
    series_ids: List[str], 
    config: AppConfig, 
    cancellation_event: threading.Event, 
    task_id: str, 
    task_manager: TaskManager,
    task_name: str 
):
    task_cat = task_name
    ui_logger.info(f"开始从 {len(series_ids)} 个剧集(Series)中获取所有分集(Episode)...", task_category=task_cat)
    task_manager.update_task_progress(task_id, 0, len(series_ids))

    all_episode_ids = []
    session = requests.Session()
    for i, series_id in enumerate(series_ids):
        if cancellation_event.is_set():
            ui_logger.warning("在获取分集阶段被取消。", task_category=task_cat)
            return

        try:
            episodes_url = f"{config.server_config.server}/Items"
            episodes_params = {
                "api_key": config.server_config.api_key,
                "ParentId": series_id,
                "IncludeItemTypes": "Episode",
                "Recursive": "true",
                "Fields": "Id"
            }
            episodes_resp = session.get(episodes_url, params=episodes_params, timeout=30)
            if episodes_resp.ok:
                episodes = episodes_resp.json().get("Items", [])
                all_episode_ids.extend([ep['Id'] for ep in episodes])
        except Exception as e:
            ui_logger.error(f"获取剧集 {series_id} 的分集时失败: {e}", task_category=task_cat)
        
        task_manager.update_task_progress(task_id, i + 1, len(series_ids))

    ui_logger.info(f"分集获取完毕，共找到 {len(all_episode_ids)} 个分集需要刷新。", task_category=task_cat)
    
    logic = EpisodeRefresherLogic(config)
    logic.run_refresh_for_episodes(
        all_episode_ids,
        config.episode_refresher_config,
        cancellation_event,
        task_id,
        task_manager,
        task_cat
    )

def _episode_screenshot_backup_task_runner(
    series_ids: List[str], 
    config: AppConfig, 
    cancellation_event: threading.Event, 
    task_id: str, 
    task_manager: TaskManager,
    task_name: str 
):
    task_cat = task_name
    logic = EpisodeRefresherLogic(config)
    logic.backup_screenshots_from_emby_task(
        series_ids,
        config.episode_refresher_config,
        cancellation_event,
        task_id,
        task_manager
    )

def _episode_renamer_task_runner(
    series_ids: List[str], 
    config: AppConfig, 
    cancellation_event: threading.Event, 
    task_id: str, 
    task_manager: TaskManager,
    task_name: str 
):
    task_cat = task_name
    ui_logger.info(f"开始从 {len(series_ids)} 个剧集(Series)中获取所有分集(Episode)...", task_category=task_cat)
    task_manager.update_task_progress(task_id, 0, len(series_ids))

    all_episode_ids = []
    session = requests.Session()
    for i, series_id in enumerate(series_ids):
        if cancellation_event.is_set():
            ui_logger.warning("在获取分集阶段被取消。", task_category=task_cat)
            return

        try:
            episodes_url = f"{config.server_config.server}/Items"
            episodes_params = {
                "api_key": config.server_config.api_key,
                "ParentId": series_id,
                "IncludeItemTypes": "Episode",
                "Recursive": "true",
                "Fields": "Id"
            }
            episodes_resp = session.get(episodes_url, params=episodes_params, timeout=30)
            if episodes_resp.ok:
                episodes = episodes_resp.json().get("Items", [])
                all_episode_ids.extend([ep['Id'] for ep in episodes])
        except Exception as e:
            ui_logger.error(f"获取剧集 {series_id} 的分集时失败: {e}", task_category=task_cat)
        
        task_manager.update_task_progress(task_id, i + 1, len(series_ids))

    ui_logger.info(f"分集获取完毕，共找到 {len(all_episode_ids)} 个分集需要处理。", task_category=task_cat)
    
    logic = EpisodeRenamerLogic(config)
    logic.run_rename_for_episodes(
        all_episode_ids,
        cancellation_event,
        task_id,
        task_manager,
        task_cat
    )


def trigger_scheduled_task(task_id: str):
    task_name_map = {
        "actor_localizer": "演员中文化",
        "douban_fixer": "豆瓣ID修复",
        "douban_poster_updater": "豆瓣海报更新",
        "episode_refresher": "剧集元数据刷新",
        "episode_renamer": "剧集文件重命名",
        "movie_renamer": "电影文件重命名",
        "episode_role_sync": "剧集角色同步到分集",
        # --- 新增行 ---
        "id_mapper": "TMDB-Emby ID 映射表"
    }
    task_display_name = task_name_map.get(task_id, task_id)
    task_cat = f"定时任务-{task_display_name}"
    ui_logger.info(f"开始执行定时任务...", task_category=task_cat)
    
    # --- 核心修改：ID映射任务不依赖通用范围 ---
    if task_id == "id_mapper":
        task_manager.register_task(generate_id_map_task, f"定时任务-{task_display_name}")
        return

    config = app_config.load_app_config()
    scope = config.scheduled_tasks_config.target_scope
    selector = MediaSelector(config)
    
    target_collection_type = None
    if task_id == "episode_refresher" or task_id == "episode_renamer":
        target_collection_type = "tvshows"

    elif task_id == "movie_renamer":
        target_collection_type = "movies"
        
    item_ids = selector.get_item_ids(scope, target_collection_type=target_collection_type)

    if not item_ids:
        ui_logger.info(f"未根据范围找到任何媒体项，任务结束。", task_category=task_cat)
        return

    if task_id == "actor_localizer":
        logic = ActorLocalizerLogic(config)
        task_name = f"定时任务-演员中文化({scope.mode})"
        task_manager.register_task(
            logic.run_localization_for_items, 
            task_name, 
            item_ids, 
            config.actor_localizer_config,
            task_category=task_name
        )
    elif task_id == "douban_fixer":
        logic = DoubanFixerLogic(config)
        task_name = f"定时任务-豆瓣ID修复({scope.mode})"
        task_manager.register_task(
            logic.run_fixer_for_items,
            task_name,
            item_ids,
            task_category=task_name
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
    elif task_id == "episode_refresher":
        task_name = f"定时任务-剧集元数据刷新({scope.mode})"
        task_manager.register_task(
            _episode_refresher_task_runner,
            task_name,
            series_ids=item_ids,
            config=config,
            task_name=task_name
        )
    elif task_id == "episode_renamer":
        task_name = f"定时任务-剧集文件重命名({scope.mode})"
        task_manager.register_task(
            _episode_renamer_task_runner,
            task_name,
            series_ids=item_ids,
            config=config,
            task_name=task_name
        )
    elif task_id == "episode_role_sync":
        logic = EpisodeRoleSyncLogic(config)
        task_name = f"定时任务-剧集角色同步({scope.mode})"
        task_manager.register_task(
            logic.run_sync_for_items,
            task_name,
            item_ids,
            config.episode_role_sync_config,
            task_category=task_name
        )
    elif task_id == "movie_renamer":
        from movie_renamer_logic import MovieRenamerLogic
        logic = MovieRenamerLogic(config)
        task_name = f"定时任务-电影文件重命名({scope.mode})"
        task_manager.register_task(
            logic.run_rename_task_for_items,
            task_name,
            item_ids=item_ids,
            task_category=task_name
        )
    else:
        ui_logger.warning(f"未知的任务ID: {task_id}", task_category=task_cat)

def trigger_chasing_workflow():
    """内置的每日追更工作流触发器"""
    task_cat = "定时任务-追更维护"
    config = app_config.load_app_config()
    if not config.chasing_center_config.enabled:
        logging.info(f"【调度任务】追更工作流未启用，跳过每日维护。")
        return
    
    ui_logger.info("开始执行内置的每日追更维护任务...", task_category=task_cat)
    from chasing_center_logic import ChasingCenterLogic
    logic = ChasingCenterLogic(config)
    task_manager.register_task(logic.run_chasing_workflow_task, "定时任务-追更每日维护")

def trigger_upcoming_notification():
    """即将上映订阅通知触发器"""
    task_cat = "定时任务-订阅通知"
    config = app_config.load_app_config()
    if not config.upcoming_config.enabled:
        logging.info(f"【调度任务】即将上映功能未启用，跳过订阅通知。")
        return
    
    ui_logger.info("开始执行订阅列表通知任务...", task_category=task_cat)
    from upcoming_logic import UpcomingLogic
    logic = UpcomingLogic(config)
    # 这是一个快速任务，直接在主线程执行，不注册到 task_manager
    logic.check_and_notify()

def trigger_calendar_notification():
    """追剧日历通知触发器"""
    task_cat = "定时任务-追剧日历"
    config = app_config.load_app_config()
    if not config.chasing_center_config.enabled or not config.telegram_config.enabled:
        logging.info(f"【调度任务】追更工作流或Telegram通知未启用，跳过日历发送。")
        return
    
    ui_logger.info("开始执行追剧日历通知任务...", task_category=task_cat)
    from chasing_center_logic import ChasingCenterLogic
    logic = ChasingCenterLogic(config)
    task_manager.register_task(logic.send_calendar_notification_task, "定时任务-追剧日历通知")

def trigger_media_tagger_task():
    """媒体标签器定时任务触发器"""
    task_cat = "定时任务-媒体标签器"
    config = app_config.load_app_config()
    if not config.media_tagger_config.enabled:
        logging.info(f"【调度任务】媒体标签器定时任务未启用，跳过执行。")
        return
    
    ui_logger.info("开始执行媒体标签器定时任务...", task_category=task_cat)
    from media_tagger_logic import MediaTaggerLogic
    logic = MediaTaggerLogic(config)
    task_manager.register_task(logic.run_tagging_task, "媒体标签器-定时任务")

def update_chasing_scheduler():
    """更新追更中心的定时任务"""
    task_cat = "系统配置"
    ui_logger.info("【调度任务】检测到追更中心配置变更，正在更新调度器...", task_category=task_cat)
    config = app_config.load_app_config()
    
    # 每日维护任务 (内置，不可配置)
    job_id_workflow = "chasing_workflow_daily"
    # --- 修改 ---
    if config.chasing_center_config.enabled and config.chasing_center_config.maintenance_cron:
        try:
            scheduler.add_job(
                trigger_chasing_workflow, 
                CronTrigger.from_crontab(config.chasing_center_config.maintenance_cron), 
                id=job_id_workflow, 
                replace_existing=True
            )
            ui_logger.info(f"  - 已更新每日追更维护任务 (CRON: {config.chasing_center_config.maintenance_cron})", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"  - ❌ 更新每日追更维护任务失败: {e}", task_category=task_cat)
    # --- 修改结束 ---
    elif scheduler.get_job(job_id_workflow):
        scheduler.remove_job(job_id_workflow)
        ui_logger.info(f"  - 已禁用并移除每日追更维护任务。", task_category=task_cat)

    # 日历通知任务 (可配置)
    job_id_calendar = "chasing_calendar_notification"
    if config.chasing_center_config.enabled and config.chasing_center_config.notification_cron:
        try:
            scheduler.add_job(
                trigger_calendar_notification, 
                CronTrigger.from_crontab(config.chasing_center_config.notification_cron), 
                id=job_id_calendar, 
                replace_existing=True
            )
            ui_logger.info(f"  - 已更新追剧日历通知任务 (CRON: {config.chasing_center_config.notification_cron})", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"  - ❌ 更新追剧日历任务失败: {e}", task_category=task_cat)
    elif scheduler.get_job(job_id_calendar):
        scheduler.remove_job(job_id_calendar)
        ui_logger.info(f"  - 已移除追剧日历通知任务。", task_category=task_cat)


def update_upcoming_scheduler():
    """更新即将上映功能的定时任务"""
    task_cat = "系统配置"
    ui_logger.info("【调度任务】检测到即将上映功能配置变更，正在更新调度器...", task_category=task_cat)
    config = app_config.load_app_config()
    
    # --- 新增：清理任务的逻辑 ---
    from upcoming_logic import UpcomingLogic
    logic = UpcomingLogic(config)

    def trigger_pruning_task():
        """即将上映过期项目清理触发器"""
        task_cat_prune = "定时任务-订阅清理"
        if not config.upcoming_config.enabled:
            logging.info(f"【调度任务】即将上映功能未启用，跳过过期项目清理。")
            return
        ui_logger.info("开始执行订阅列表过期项目清理任务...", task_category=task_cat_prune)
        logic.prune_expired_items()
    # --- 新增结束 ---

    # 订阅通知任务
    job_id_notify = "upcoming_notification"
    if config.upcoming_config.enabled and config.upcoming_config.notification_cron:
        try:
            scheduler.add_job(
                trigger_upcoming_notification, 
                CronTrigger.from_crontab(config.upcoming_config.notification_cron), 
                id=job_id_notify, 
                replace_existing=True
            )
            ui_logger.info(f"  - 已更新订阅通知任务 (CRON: {config.upcoming_config.notification_cron})", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"  - ❌ 更新订阅通知任务失败: {e}", task_category=task_cat)
    elif scheduler.get_job(job_id_notify):
        scheduler.remove_job(job_id_notify)
        ui_logger.info(f"  - 已禁用并移除订阅通知任务。", task_category=task_cat)

    # --- 新增：清理任务的调度 ---
    job_id_prune = "upcoming_pruning"
    if config.upcoming_config.enabled and config.upcoming_config.pruning_cron:
        try:
            scheduler.add_job(
                trigger_pruning_task, 
                CronTrigger.from_crontab(config.upcoming_config.pruning_cron), 
                id=job_id_prune, 
                replace_existing=True
            )
            ui_logger.info(f"  - 已更新过期项目清理任务 (CRON: {config.upcoming_config.pruning_cron})", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"  - ❌ 更新过期项目清理任务失败: {e}", task_category=task_cat)
    elif scheduler.get_job(job_id_prune):
        scheduler.remove_job(job_id_prune)
        ui_logger.info(f"  - 已禁用并移除过期项目清理任务。", task_category=task_cat)
    # --- 新增结束 ---



@asynccontextmanager
async def lifespan(app: FastAPI):
    global episode_sync_scheduler_task, id_map_update_scheduler_task # 声明我们要修改全局变量
    task_cat = "系统启动"
    # --- 核心修改 1: 初始化日志系统，但不包括 WebSocket 处理器 ---
    # 这是为了让日志系统在应用启动的最早期就能工作
    from log_manager import setup_logging, WebSocketLogHandler
    setup_logging(add_websocket_handler=False)
    
    # --- 核心修改 2: 在主线程（lifespan内）创建并添加 WebSocket 处理器 ---
    # 此时 get_running_loop() 一定能成功
    websocket_handler = WebSocketLogHandler()
    logging.getLogger().addHandler(websocket_handler)
    ui_logger.info("应用启动...", task_category=task_cat)
    required_tools = ['ffmpeg', 'ffprobe']
    for tool in required_tools:
        if not shutil.which(tool):
            ui_logger.warning(f"【启动检查】未找到 '{tool}' 命令，视频截图功能将不可用。请确保已在 Docker 环境或主机上安装 ffmpeg。", task_category=task_cat)
    task_manager_consumer = asyncio.create_task(task_manager.broadcast_consumer())
    webhook_worker_task = asyncio.create_task(webhook_worker())
    # --- 新增 ---
    episode_sync_scheduler_task = asyncio.create_task(episode_sync_scheduler())
    # --- 新增：启动ID映射表更新调度器 ---
    id_map_update_scheduler_task = asyncio.create_task(id_map_update_scheduler())

    library_scan_scheduler_task = asyncio.create_task(library_scan_scheduler())
    # --- 新增结束 ---

    config = app_config.load_app_config()
    
    douban_conf = config.douban_config
    if douban_conf.directory and os.path.isdir(douban_conf.directory):
        if not os.path.exists(DOUBAN_CACHE_FILE):
            ui_logger.info("【启动检查】未发现豆瓣缓存文件，将自动执行首次扫描。", task_category=task_cat)
            task_manager.register_task(scan_douban_directory_task, "首次启动豆瓣扫描", douban_conf.directory, douban_conf.extra_fields)
        else:
            logging.info(f"【启动检查】已找到豆瓣缓存文件: {DOUBAN_CACHE_FILE}，跳过自动扫描。")
    else:
        logging.warning("【启动检查】未配置有效的豆瓣目录，无法执行扫描。")

    if douban_conf.refresh_cron:
        try:
            scheduler.add_job(trigger_douban_refresh, CronTrigger.from_crontab(douban_conf.refresh_cron), id="douban_refresh_job", replace_existing=True)
            ui_logger.info(f"【调度任务】已成功设置豆瓣数据定时刷新任务，CRON表达式: '{douban_conf.refresh_cron}'", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"【调度任务】设置定时刷新任务失败，CRON表达式可能无效: {e}", task_category=task_cat)

    fixer_conf = config.douban_fixer_config
    if fixer_conf.scan_cron:
        try:
            scheduler.add_job(trigger_douban_fixer_scan, CronTrigger.from_crontab(fixer_conf.scan_cron), id="douban_fixer_scan_job", replace_existing=True)
            ui_logger.info(f"【调度任务】已成功设置豆瓣ID修复器定时扫描任务，CRON表达式: '{fixer_conf.scan_cron}'", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"【调度任务】设置豆瓣ID修复器定时扫描任务失败，CRON表达式可能无效: {e}", task_category=task_cat)

    actor_conf = config.actor_localizer_config
    if actor_conf.apply_cron:
        try:
            scheduler.add_job(trigger_actor_localizer_apply, CronTrigger.from_crontab(actor_conf.apply_cron), id="actor_localizer_apply_job", replace_existing=True)
            ui_logger.info(f"【调度任务】已成功设置演员中文化自动应用任务，CRON表达式: '{actor_conf.apply_cron}'", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"【调度任务】设置演员中文化自动应用任务失败，CRON表达式可能无效: {e}", task_category=task_cat)

    
    ui_logger.info("【调度任务】开始设置通用定时任务...", task_category=task_cat)
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
                ui_logger.info(f"  - 已成功设置定时任务 '{task.name}'，CRON表达式: '{task.cron}'", task_category=task_cat)
            except Exception as e:
                ui_logger.error(f"  - 设置定时任务 '{task.name}' 失败，CRON表达式可能无效: {e}", task_category=task_cat)

    ui_logger.info("【调度任务】开始设置追更中心任务...", task_category=task_cat)
    update_chasing_scheduler()

    ui_logger.info("【调度任务】开始设置即将上映任务...", task_category=task_cat)
    update_upcoming_scheduler()

    media_tagger_conf = config.media_tagger_config
    if media_tagger_conf.enabled and media_tagger_conf.cron:
        try:
            scheduler.add_job(
                trigger_media_tagger_task,
                CronTrigger.from_crontab(media_tagger_conf.cron),
                id="media_tagger_job",
                replace_existing=True
            )
            ui_logger.info(f"【调度任务】已成功设置媒体标签器任务，CRON表达式: '{media_tagger_conf.cron}'", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"【调度任务】设置媒体标签器任务失败，CRON表达式可能无效: {e}", task_category=task_cat)

    if not scheduler.running:
        scheduler.start()

    yield
    
    logging.info("应用关闭，正在停止后台服务...")
    
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logging.info("APScheduler 已被指令关闭。")

    webhook_worker_task.cancel()
    task_manager_consumer.cancel()
    # --- 新增 ---
    if episode_sync_scheduler_task:
        episode_sync_scheduler_task.cancel()
    if id_map_update_scheduler_task:
        id_map_update_scheduler_task.cancel()
    # --- 新增：取消媒体库扫描调度器 ---
    if library_scan_scheduler_task:
        library_scan_scheduler_task.cancel()
    await asyncio.gather(
        webhook_worker_task, 
        task_manager_consumer, 
        episode_sync_scheduler_task, 
        id_map_update_scheduler_task, 
        library_scan_scheduler_task, # 添加到 gather
        return_exceptions=True
    )
    # --- 修改结束 ---
    logging.info("所有后台任务已成功取消。")

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
app.include_router(episode_renamer_router, prefix="/api/episode-renamer")
app.include_router(poster_manager_router, prefix="/api/poster-manager")
app.include_router(actor_role_mapper_router, prefix="/api/actor-role-mapper")
app.include_router(episode_role_sync_router, prefix="/api/episode-role-sync")
app.include_router(actor_avatar_mapper_router, prefix="/api/actor-avatar-mapper")
app.include_router(chasing_center_router, prefix="/api/chasing-center")
app.include_router(upcoming_router, prefix="/api/upcoming")
app.include_router(file_scraper_router, prefix="/api/file-scraper")
app.include_router(media_tagger_router, prefix="/api/media-tagger")

from models import TraktConfig
from trakt_manager import TraktManager

@app.post("/api/config/trakt")
def save_trakt_config_api(config: TraktConfig):
    """保存 Trakt.tv 配置"""
    try:
        ui_logger.info("正在保存 Trakt.tv 设置...", task_category="系统配置")
        current_app_config = app_config.load_app_config()
        current_app_config.trakt_config = config
        app_config.save_app_config(current_app_config)
        ui_logger.info("✅ Trakt.tv 设置保存成功！", task_category="系统配置")
        return {"success": True, "message": "设置已保存！"}
    except Exception as e:
        logging.error(f"保存 Trakt.tv 设置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存设置时发生错误: {e}")

@app.post("/api/trakt/test")
def test_trakt_api(config: TraktConfig):
    """测试 Trakt.tv API 连接"""
    task_cat = "Trakt-测试"
    if not config.enabled:
        return {"success": True, "message": "Trakt 未启用，无需测试。"}
    if not config.client_id:
        raise HTTPException(status_code=400, detail="Client ID 不能为空。")
    
    ui_logger.info(f"➡️ [Trakt] 开始测试 Client ID...", task_category=task_cat)
    
    temp_app_config = app_config.load_app_config()
    temp_app_config.trakt_config = config
    trakt_manager = TraktManager(temp_app_config)
    
    # 使用一个常见的 TMDB ID 进行测试
    test_tmdb_id = "1399" # Game of Thrones
    result = trakt_manager.get_show_seasons_with_episodes(test_tmdb_id)
    
    if result is not None:
        ui_logger.info(f"✅ [Trakt] 测试成功！成功获取到《权力的游戏》的 {len(result)} 条分集数据。", task_category=task_cat)
        return {"success": True, "message": "Trakt API 连接成功！"}
    else:
        ui_logger.error(f"❌ [Trakt] 测试失败，请检查 Client ID 是否正确以及网络连接。", task_category=task_cat)
        raise HTTPException(status_code=500, detail="无法从 Trakt.tv 获取数据，请检查 Client ID 或代理设置。")


@app.get("/api/image-proxy")
async def image_proxy(url: str):
    """
    通用的外部图片代理，用于解决前端混合内容问题。
    此实现遵循用户定义的代理规则。
    """
    task_cat = "图片代理-通用"
    try:
        config = app_config.load_app_config()
        proxy_manager = ProxyManager(config)
        # --- 核心修正：使用 mounts 参数 ---
        mounts = proxy_manager.get_proxies_for_httpx(url)

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
        }
        if 'doubanio.com' in url:
            headers['Referer'] = 'https://movie.douban.com/'

        async with httpx.AsyncClient(mounts=mounts or {}, follow_redirects=True) as client:
            req = await client.get(url, headers=headers, timeout=20)
        # --- 修正结束 ---
            req.raise_for_status()

        content_type = req.headers.get('Content-Type', 'image/jpeg')
        if not content_type.startswith('image/'):
            ui_logger.warning(f"⚠️ 代理请求返回的 Content-Type 不是图片: {content_type}。URL: {url}", task_category=task_cat)
            raise HTTPException(status_code=400, detail="代理目标返回的不是有效的图片内容。")

        return Response(content=req.content, media_type=content_type)
        
    except httpx.RequestError as e:
        ui_logger.error(f"❌ 请求外部图片失败: {e}", task_category=task_cat, exc_info=True)
        raise HTTPException(status_code=502, detail=f"请求外部图片URL失败: {e}")
    except Exception as e:
        ui_logger.error(f"❌ 代理图片时发生未知错误: {e}", task_category=task_cat, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

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
    task_cat = "图片代理-Emby"
    try:
        config = app_config.load_app_config()
        server_conf = config.server_config
        if not server_conf.server:
            raise HTTPException(status_code=400, detail="Emby服务器未配置。")

        if 'api_key=' not in path.lower():
            separator = '&' if '?' in path else '?'
            path_with_auth = f"{path}{separator}api_key={server_conf.api_key}"
        else:
            path_with_auth = path

        full_url = f"{server_conf.server}/{path_with_auth}"
        
        proxy_manager = ProxyManager(config)
        # --- 核心修正：使用 mounts 参数 ---
        mounts = proxy_manager.get_proxies_for_httpx(full_url)

        async with httpx.AsyncClient(mounts=mounts or {}, follow_redirects=True) as client:
            req = await client.get(full_url, timeout=20)
        # --- 修正结束 ---
        
        req.raise_for_status()
        
        content_type = req.headers.get('Content-Type', 'image/jpeg')
        if not content_type.startswith('image/'):
            ui_logger.warning(f"⚠️ 代理请求返回的 Content-Type 不是图片: {content_type}。URL: {full_url}", task_category=task_cat)
            raise HTTPException(status_code=400, detail="代理目标返回的不是有效的图片内容。")

        return Response(content=req.content, media_type=content_type)
        
    except httpx.RequestError as e:
        ui_logger.error(f"❌ 请求 Emby 图片时发生网络异常: {e}", task_category=task_cat, exc_info=True)
        raise HTTPException(status_code=502, detail=f"请求 Emby 服务器失败: {e}")
    except Exception as e:
        ui_logger.error(f"❌ 代理 Emby 图片时发生未知错误: {e}", task_category=task_cat, exc_info=True)
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
        
        # --- 核心修改：使用新的 ProxyManager ---
        test_url = f"{server_config.server}/Users/{server_config.user_id}"
        proxy_manager = ProxyManager(current_app_config)
        proxies = proxy_manager.get_proxies(test_url)
        
        if proxies:
            logging.info(f"【连接测试】将通过代理 {proxies.get('http')} 连接 Emby 服务器。")
        else:
            logging.info("【连接测试】将直接连接 Emby 服务器。")
        # --- 结束修改 ---

        params = {"api_key": server_config.api_key}
        response = requests.get(test_url, params=params, timeout=15, proxies=proxies)
        response.raise_for_status()
        user_data = response.json()
        if not user_data.get("Name"): raise ValueError("服务器响应异常，未找到有效的用户信息。")
        
        system_info_url = f"{server_config.server}/System/Info"
        # --- 核心修改：为第二个请求也应用代理逻辑 ---
        proxies_system = proxy_manager.get_proxies(system_info_url)
        response_system = requests.get(system_info_url, params=params, timeout=15, proxies=proxies_system)
        # --- 结束修改 ---
        
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
        # --- 核心修改：使用 ui_logger 发送中文日志给前端 ---
        ui_logger.info("正在保存网络代理设置...", task_category="系统配置")
        # --- 使用 logging.debug 记录详细的技术日志到后端 ---
        logging.debug(f"接收到的代理配置原始数据: {proxy_config.model_dump_json()}")
        
        if proxy_config.url and not (proxy_config.url.startswith("http://") or proxy_config.url.startswith("https://")):
             raise ValueError("代理地址格式不正确，必须以 http:// 或 https:// 开头。")
        
        current_app_config = app_config.load_app_config()
        current_app_config.proxy_config = proxy_config
        app_config.save_app_config(current_app_config)
        
        # --- 核心修改：使用 ui_logger 发送中文成功日志给前端 ---
        ui_logger.info("代理设置保存成功！", task_category="系统配置")
        
        return {"success": True, "message": "代理设置已保存！"}
    except Exception as e:
        logging.error(f"保存代理设置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存代理设置时发生错误: {e}")

@app.post("/api/config/proxy/test")
def test_proxy_config_api(proxy_config: ProxyConfig):
    task_cat = "代理测试" # --- 定义任务类别 ---
    if not proxy_config.enabled:
        ui_logger.info("代理未启用，跳过测试。", task_category=task_cat)
        return {"success": True, "message": "代理未启用，无需测试。"}
    proxy_url = proxy_config.url
    if not proxy_url:
        raise HTTPException(status_code=400, detail="代理已启用，但代理地址不能为空。")
    if not (proxy_url.startswith("http://") or proxy_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="代理地址格式不正确，必须以 http:// 或 https:// 开头。")
    ui_logger.info(f"开始测试，将通过代理 '{proxy_url}' 连接外部网络...", task_category=task_cat)
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
        ui_logger.info(f"成功！服务器返回状态码: {response.status_code}。延迟: {latency_ms:.2f} ms。", task_category=task_cat)
        return {"success": True, "message": success_msg, "latency": f"{latency_ms:.2f} ms"}
    except requests.exceptions.ProxyError as e:
        ui_logger.error(f"失败！代理错误: {e}", task_category=task_cat, exc_info=True)
        raise HTTPException(status_code=500, detail=f"代理服务器错误，请检查地址和端口是否正确，以及代理服务是否正常运行。")
    except requests.exceptions.ConnectTimeout:
        ui_logger.error(f"失败！连接代理服务器超时。", task_category=task_cat)
        raise HTTPException(status_code=500, detail="连接代理服务器超时，请检查网络或代理设置。")
    except requests.exceptions.RequestException as e:
        ui_logger.error(f"失败！发生网络请求异常: {e}", task_category=task_cat, exc_info=True)
        raise HTTPException(status_code=500, detail=f"通过代理访问外部网络失败，请检查代理是否能访问公网。错误: {e}")
    except Exception as e:
        ui_logger.error(f"失败！发生未知错误: {e}", task_category=task_cat, exc_info=True)
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
def get_logs_api(
    page: int = Query(1, ge=1), 
    page_size: int = Query(1000, ge=1), 
    level: str = Query("INFO"), 
    category: Optional[str] = Query(None),
    date: Optional[str] = Query(None, description="查询指定日期的日志，格式 YYYY-MM-DD")
):
   
    LOGS_DIR = "/app/data/logs"
    
    log_file_path = ""
    if date:
        log_file_path = os.path.join(LOGS_DIR, f"app.log.{date}")
    else:
        log_file_path = os.path.join(LOGS_DIR, "app.log")

    

    if not os.path.exists(log_file_path):
        # 如果文件不存在，直接返回空结果，避免后续错误
        return {"total": 0, "logs": [], "totalPages": 0, "currentPage": page}

    try:
        with open(log_file_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        
        log_pattern = re.compile(
            r"^(?P<level>\w+):\s+"
            r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+-\s+"
            r"(?P<category>.+?)\s+→\s+"
            r"(?P<message>.*)$"
        )

        parsed_logs = []
        current_log_entry = None

        for line in all_lines:
            match = log_pattern.match(line.strip())
            if match:
                if current_log_entry:
                    parsed_logs.append(current_log_entry)
                current_log_entry = match.groupdict()
            elif current_log_entry:
                current_log_entry['message'] += '\n' + line.rstrip()
        
        if current_log_entry:
            parsed_logs.append(current_log_entry)

        # --- 核心修改 2: 过滤逻辑保持不变，但作用于单个日志文件 ---
        filtered_logs = []
        if level != "ALL":
            level_to_match = level.upper()
            for log in parsed_logs:
                if log.get('level', '').upper() == level_to_match:
                    filtered_logs.append(log)
        else:
            filtered_logs = parsed_logs
        
        if category:
            final_filtered_logs = [log for log in filtered_logs if log.get('category', '').strip() == category]
        else:
            final_filtered_logs = filtered_logs
        
        total_logs = len(final_filtered_logs)
        total_pages = (total_logs + page_size - 1) // page_size
        
        # --- 核心修改 3: 分页逻辑保持不变，但现在是倒序分页 ---
        # 最新的日志在最前面
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        
        # 从反转后的列表（最新的在前）中切片
        paginated_logs = final_filtered_logs[::-1][start_index:end_index]
            
        return {"total": total_logs, "logs": paginated_logs, "totalPages": total_pages, "currentPage": page}
    except Exception as e:
        logging.error(f"❌ 读取日志文件 '{log_file_path}' 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取日志文件失败: {e}")
    


@app.get("/api/logs/dates")
def get_log_dates_api():
    """扫描日志目录并返回所有可用的日志日期列表"""
    LOGS_DIR = "/app/data/logs"
    dates = []
    try:
        if not os.path.exists(LOGS_DIR):
            logging.warning(f"⚠️ 日志目录 '{LOGS_DIR}' 不存在，无法获取历史日期。")
            return []

        # 检查当天的日志是否存在
        if os.path.exists(os.path.join(LOGS_DIR, "app.log")):
            today_str = datetime.now().strftime('%Y-%m-%d')
            dates.append(today_str)

        # 扫描历史日志文件
        for filename in os.listdir(LOGS_DIR):
            if filename.startswith("app.log."):
                # 文件名格式为 app.log.YYYY-MM-DD
                date_part = filename.split('.')[-1]
                try:
                    # 验证日期格式是否正确
                    datetime.strptime(date_part, '%Y-%m-%d')
                    dates.append(date_part)
                except ValueError:
                    # 忽略格式不正确的文件
                    continue
        
        # 按日期降序排序，最新的日期在最前面
        dates.sort(reverse=True)
        return dates
    except Exception as e:
        logging.error(f"❌ 扫描日志日期失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"扫描日志日期失败: {e}")


@app.get("/api/logs/categories")
def get_log_categories_api():
    """扫描日志目录并返回所有唯一的任务类别"""
    LOGS_DIR = "/app/data/logs"
    categories = set()
    
    try:
        if not os.path.exists(LOGS_DIR):
            logging.warning(f"⚠️ 日志目录 '{LOGS_DIR}' 不存在，无法获取任务类别。")
            return []

        log_pattern = re.compile(r"-\s+(.+?)\s+→")

        # --- 核心修改：遍历日志目录下的所有 app.log* 文件 ---
        for filename in os.listdir(LOGS_DIR):
            if filename.startswith("app.log"):
                file_path = os.path.join(LOGS_DIR, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        for line in f:
                            match = log_pattern.search(line)
                            if match:
                                # strip() 用于去除可能存在的前后空格
                                categories.add(match.group(1).strip())
                except Exception as file_error:
                    logging.error(f"❌ 读取日志文件 '{file_path}' 时出错: {file_error}")
                    # 单个文件读取失败不应中断整个流程
                    continue
        
        # 返回排序后的列表以保证前端显示顺序稳定
        return sorted(list(categories))
    except Exception as e:
        logging.error(f"❌ 扫描日志类别失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"扫描日志类别失败: {e}")
    

# backend/main.py (函数替换)

@app.delete("/api/logs")
def clear_logs_api():
    LOGS_DIR = "/app/data/logs"
    
    try:
        root_logger = logging.getLogger()
        
        # --- 核心修改 1: 只关闭和移除文件处理器 ---
        # 遍历处理器列表的一个副本，因为我们会在循环中修改原列表
        handlers_to_remove = []
        for handler in root_logger.handlers:
            # 通过检查 handler 的类型来精确识别文件处理器
            if isinstance(handler, logging.handlers.TimedRotatingFileHandler):
                handlers_to_remove.append(handler)

        for handler in handlers_to_remove:
            handler.close()
            root_logger.removeHandler(handler)
        
        # --- 文件删除逻辑保持不变 ---
        if not os.path.exists(LOGS_DIR):
            # 即使目录不存在，也应该重新添加文件处理器
            pass
        else:
            cleared_count = 0
            for filename in os.listdir(LOGS_DIR):
                if filename.startswith("app.log"):
                    file_path = os.path.join(LOGS_DIR, filename)
                    try:
                        os.remove(file_path)
                        cleared_count += 1
                    except OSError as e:
                        logging.error(f"❌ 删除日志文件 '{file_path}' 失败: {e}", exc_info=True)
            logging.info(f"✅ 日志已清空，共删除 {cleared_count} 个日志文件。")

        # --- 核心修改 2: 只重新添加文件处理器 ---
        # 创建一个新的文件处理器并添加到根 logger
        log_file_path = os.path.join(LOGS_DIR, "app.log")
        file_handler = logging.handlers.TimedRotatingFileHandler(
            log_file_path, 
            when='D', 
            interval=1, 
            backupCount=14, 
            encoding='utf-8'
        )
        # 需要从 log_manager 导入 CustomLogFormatter
        from log_manager import CustomLogFormatter
        file_handler.setFormatter(CustomLogFormatter())
        root_logger.addHandler(file_handler)

        ui_logger.info("日志文件已清空并重建。", task_category="日志管理")
        return {"success": True, "message": "所有日志文件已清空"}
    
    except Exception as e:
        ui_logger.error(f"❌ 清空日志文件时发生未知错误: {e}", task_category="日志管理", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清空日志失败: {e}")
    
# backend/main.py (函数替换)

@app.get("/api/media/libraries")
def get_libraries_api():
    config = app_config.load_app_config()
    server_conf = config.server_config
    if not all([server_conf.server, server_conf.api_key, server_conf.user_id]): raise HTTPException(status_code=400, detail="Emby服务器未配置")
    try:
        logging.info(f"正在从 {server_conf.server} 获取媒体库列表...")
        url = f"{server_conf.server}/Users/{server_conf.user_id}/Views"
        
        proxy_manager = ProxyManager(config)
        proxies = proxy_manager.get_proxies(url)

        response = requests.get(url, params={"api_key": server_conf.api_key}, timeout=15, proxies=proxies)
        response.raise_for_status()
        views = response.json().get("Items", [])

        # --- 核心修改：增加健壮性，并添加调试日志 ---
        # 临时调试日志，用于观察所有返回的视图及其类型
        for v in views:
            logging.debug(f"【媒体库API调试】找到视图: \"{v.get('Name')}\", CollectionType: \"{v.get('CollectionType')}\", Type: \"{v.get('Type')}\"")

        # 更健壮的媒体库识别逻辑：
        # 1. CollectionType 在我们的白名单中
        # 2. 或者，它的 Type 是 'CollectionFolder' (这是媒体库的根本类型)
        valid_collection_types = ["movies", "tvshows", "homevideos", "music", "mixed"]
        libraries = [
            {"id": v["Id"], "name": v["Name"]} 
            for v in views 
            if v.get("CollectionType") in valid_collection_types or v.get("Type") == "CollectionFolder"
        ]
        # --- 修改结束 ---
        
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
        # --- 核心修改：使用新的 ProxyManager ---
        proxy_manager = ProxyManager(config)
        proxies = proxy_manager.get_proxies(url)
        # --- 结束修改 ---

        response = requests.get(url, params=params, timeout=20, proxies=proxies)
        response.raise_for_status()
        items = response.json().get("Items", [])
        if not items and query.query.isdigit():
            try:
                item_url = f"{server_conf.server}/Users/{server_conf.user_id}/Items/{query.query}"
                item_params = { "api_key": server_conf.api_key, "Fields": "ProviderIds,ProductionYear,Genres" }
                
                # --- 核心修改：为第二个请求也应用代理逻辑 ---
                proxies_item = proxy_manager.get_proxies(item_url)
                item_resp = requests.get(item_url, params=item_params, timeout=10, proxies=proxies_item)
                # --- 结束修改 ---

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
        # --- 核心修改：使用新的 ProxyManager ---
        proxy_manager = ProxyManager(config)
        proxies = proxy_manager.get_proxies(url)
        # --- 结束修改 ---

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

# backend/main.py (修改 apply_actor_changes_directly_api 函数)

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
        config.actor_localizer_config,
        task_category=task_name # 传递 task_category
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
    

@app.get("/api/actor-localizer/media/{item_id}/people", response_model=List[Dict])
def get_media_people(item_id: str):
    try:
        config = app_config.load_app_config()
        logic = ActorLocalizerLogic(config)
        return logic.get_people_for_item(item_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/actor-localizer/suggest-roles", response_model=Dict[str, str])
def suggest_roles(req: SuggestRolesRequest):
    try:
        config = app_config.load_app_config()
        if not config.actor_localizer_config.siliconflow_config.api_key:
            raise HTTPException(status_code=400, detail="尚未配置AI大模型API Key，无法使用此功能。")
        logic = ActorLocalizerLogic(config)
        return logic.suggest_roles_with_ai(req.item_id, req.actor_names, config.actor_localizer_config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/actor-localizer/update-roles")
def update_roles(req: UpdateRolesRequest):
    task_cat = "手动校正-应用"
    try:
        config = app_config.load_app_config()
        logic = ActorLocalizerLogic(config)
        
        # --- 核心修改：先获取旧数据进行对比 ---
        ui_logger.info(f"➡️ 收到对媒体 (ID: {req.item_id}) 的角色更新请求，正在获取当前数据...", task_category=task_cat)
        full_item_json = logic._get_item_details(req.item_id, full_json=True)
        if not full_item_json:
            raise HTTPException(status_code=404, detail=f"未能找到媒体项 {req.item_id}")
        
        original_people = full_item_json.get('People', [])
        
        # 简单对比：直接比较两个列表是否相等。
        # 注意：这要求前端发送的 people 对象结构与Emby返回的完全一致。
        if original_people == req.people:
            ui_logger.info(f"✅ 检测到角色列表无任何变更，无需更新。", task_category=task_cat)
            return {"success": True, "message": "角色列表无任何变更，无需更新。"}
        # --- 修改结束 ---

        ui_logger.info(f"🔍 检测到角色列表存在变更，正在应用到 Emby...", task_category=task_cat)
        full_item_json['People'] = req.people
        
        if logic._update_item_on_server(req.item_id, full_item_json):
            ui_logger.info(f"✅ 角色名已成功更新到Emby！", task_category=task_cat)
            return {"success": True, "message": "角色名已成功更新到Emby！"}
        else:
            raise HTTPException(status_code=500, detail="更新到Emby时发生错误。")
    except Exception as e:
        ui_logger.error(f"❌ 更新角色时发生未知错误: {e}", task_category=task_cat, exc_info=True)
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
    task_cat = "API-定时任务"
    ui_logger.info(f"收到立即执行任务的请求: {task_id}", task_category=task_cat)
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
        return {"success": True, "message": f"任务 '{task_display_name or task_id}' 已成功触发，请在“运行任务”页面查看进度。"}
    except Exception as e:
        ui_logger.error(f"手动触发定时任务 '{task_id}' 时失败: {e}", task_category=task_cat, exc_info=True)
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

@app.post("/api/config/episode-refresher")
def save_episode_refresher_config_api(config: EpisodeRefresherConfig):
    try:
        logging.info("正在保存剧集元数据刷新器设置...")
        current_app_config = app_config.load_app_config()
        current_app_config.episode_refresher_config = config
        app_config.save_app_config(current_app_config)
        logging.info("剧集元数据刷新器设置保存成功！")
        return {"success": True, "message": "设置已保存！"}
    except Exception as e:
        logging.error(f"保存剧集元数据刷新器设置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存设置时发生错误: {e}")
    
class ScreenshotBackupRequest(BaseModel):
    scope: ScheduledTasksTargetScope
    config: EpisodeRefresherConfig

@app.post("/api/episode-refresher/backup-screenshots")
def backup_screenshots_api(req: ScreenshotBackupRequest):
    task_cat = "API-截图备份"
    ui_logger.info(f"收到截图备份请求，范围: {req.scope.mode}", task_category=task_cat)
    
    config = app_config.load_app_config()
    # 使用请求中临时的配置
    config.episode_refresher_config = req.config
    
    selector = MediaSelector(config)
    series_ids = selector.get_item_ids(req.scope, target_collection_type="tvshows")

    if not series_ids:
        raise HTTPException(status_code=404, detail="在指定范围内未找到任何剧集。")

    task_name = f"手动备份截图 ({req.scope.mode})"
    task_id = task_manager.register_task(
        _episode_screenshot_backup_task_runner,
        task_name,
        series_ids=series_ids,
        config=config,
        task_name=task_name
    )
    return {"status": "success", "message": "截图备份任务已启动。", "task_id": task_id}

class GitHubBackupRequest(BaseModel):
    config: EpisodeRefresherConfig

@app.post("/api/episode-refresher/backup-to-github")
def backup_screenshots_to_github_api(req: GitHubBackupRequest):
    task_cat = "API-备份到GitHub"
    ui_logger.info(f"收到备份截图到 GitHub 的请求...", task_category=task_cat)
    
    config = app_config.load_app_config()
    # 使用请求中临时的配置
    config.episode_refresher_config = req.config
    
    logic = EpisodeRefresherLogic(config)
    task_name = "备份截图到 GitHub"
    task_id = task_manager.register_task(
        logic.backup_screenshots_to_github_task,
        task_name,
        config=config.episode_refresher_config
    )
    return {"status": "success", "message": "备份到 GitHub 的任务已启动。", "task_id": task_id}
    
@app.post("/api/config/episode-renamer")
def save_episode_renamer_config_api(config: EpisodeRenamerConfig):
    try:
        logging.info("正在保存剧集文件重命名器设置...")
        current_app_config = app_config.load_app_config()
        current_app_config.episode_renamer_config = config
        app_config.save_app_config(current_app_config)
        logging.info("剧集文件重命名器设置保存成功！")
        return {"success": True, "message": "设置已保存！"}
    except Exception as e:
        logging.error(f"保存剧集文件重命名器设置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存设置时发生错误: {e}")


from models import TelegramConfig
from notification_manager import notification_manager, escape_markdown

@app.post("/api/config/telegram")
def save_telegram_config_api(config: TelegramConfig):
    """保存 Telegram 通知配置"""
    try:
        ui_logger.info("正在保存 Telegram 通知设置...", task_category="系统配置")
        current_app_config = app_config.load_app_config()
        current_app_config.telegram_config = config
        app_config.save_app_config(current_app_config)
        ui_logger.info("✅ Telegram 通知设置保存成功！", task_category="系统配置")
        return {"success": True, "message": "设置已保存！"}
    except Exception as e:
        logging.error(f"保存 Telegram 设置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存设置时发生错误: {e}")

@app.post("/api/notification/test-telegram")
def test_telegram_api(config: TelegramConfig):
    """测试发送一条 Telegram 消息"""
    # --- 核心修改：加载完整配置，并将临时测试配置覆盖上去 ---
    current_app_config = app_config.load_app_config()
    current_app_config.telegram_config = config # 使用用户正在测试的配置
    
    raw_message = "🎉 这是一条来自 Emby-Toolkit 的测试消息！\n如果能看到我，说明您的通知配置正确无误。"
    test_message = escape_markdown(raw_message)
    
    result = notification_manager.send_telegram_message(test_message, current_app_config)
    # --- 修改结束 ---
    if result["success"]:
        return result
    else:
        raise HTTPException(status_code=500, detail=result["message"])

@app.get("/api/episodes/{series_id}")
def get_series_episodes(series_id: str):
    """获取指定剧集的所有分集信息"""
    task_cat = "API-剧集刷新"
    try:
        config = app_config.load_app_config()
        session = requests.Session()
        episodes_url = f"{config.server_config.server}/Items"
        episodes_params = {
            "api_key": config.server_config.api_key,
            "ParentId": series_id,
            "IncludeItemTypes": "Episode",
            "Recursive": "true",
            "Fields": "Id,Name,IndexNumber,ParentIndexNumber,SeriesName,ProviderIds"
        }
        response = session.get(episodes_url, params=episodes_params, timeout=30)
        response.raise_for_status()
        return response.json().get("Items", [])
    except Exception as e:
        ui_logger.error(f"获取剧集 {series_id} 的分集列表时失败: {e}", task_category=task_cat, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/episode-refresher/series/{series_id}/local-screenshots")
def get_local_screenshots_for_series_api(series_id: str):
    """获取指定剧集在本地存在截图的分集列表"""
    task_cat = "API-剧集刷新"
    try:
        config = app_config.load_app_config()
        logic = EpisodeRefresherLogic(config)
        return logic.get_local_screenshots_for_series(series_id)
    except Exception as e:
        ui_logger.error(f"获取剧集 {series_id} 的本地截图列表时失败: {e}", task_category=task_cat, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/episode-refresher/precise-upload-from-local")
def precise_upload_from_local_api(req: PreciseScreenshotUpdateRequest):
    """启动一个任务，用于精准上传本地已有的截图"""
    task_cat = "API-精准覆盖"
    ui_logger.info(f"收到对剧集《{req.series_name}》的精准上传请求...", task_category=task_cat)
    
    config = app_config.load_app_config()
    # 使用请求中临时的配置
    config.episode_refresher_config = req.config
    
    logic = EpisodeRefresherLogic(config)
    task_name = f"精准覆盖截图 - {req.series_name}"
    task_id = task_manager.register_task(
        logic.precise_upload_from_local_task,
        task_name,
        series_tmdb_id=req.series_tmdb_id,
        series_name=req.series_name,
        episodes=req.episodes,
        config=req.config
    )
    return {"status": "success", "message": "精准覆盖任务已启动。", "task_id": task_id}

@app.get("/api/episode-refresher/github-delete-log")
def get_github_delete_log_api():
    """获取待删除截图的日志，并聚合Emby信息"""
    try:
        config = app_config.load_app_config()
        logic = EpisodeRefresherLogic(config)
        return logic.get_github_delete_log()
    except Exception as e:
        ui_logger.error(f"获取待删除日志失败: {e}", task_category="API-远程清理", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/episode-refresher/github-delete-log")
def save_github_delete_log_api(payload: Dict):
    """保存用户审核后的待删除日志"""
    try:
        config = app_config.load_app_config()
        logic = EpisodeRefresherLogic(config)
        if logic.save_github_delete_log(payload):
            return {"status": "success", "message": "审核状态已保存！"}
        else:
            raise HTTPException(status_code=500, detail="保存日志文件失败。")
    except Exception as e:
        ui_logger.error(f"保存待删除日志失败: {e}", task_category="API-远程清理", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/episode-refresher/cleanup-github")
def cleanup_github_screenshots_api():
    """启动一个任务，清理远程作废截图"""
    task_cat = "API-远程清理"
    ui_logger.info(f"收到清理远程作废截图的请求...", task_category=task_cat)
    
    config = app_config.load_app_config()
    if not config.episode_refresher_config.github_config.personal_access_token:
        raise HTTPException(status_code=400, detail="未配置 GitHub PAT，无法执行清理操作。")

    logic = EpisodeRefresherLogic(config)
    task_name = "清理远程作废截图"
    task_id = task_manager.register_task(
        logic.cleanup_github_screenshots_task,
        task_name,
        config=config.episode_refresher_config
    )
    return {"status": "success", "message": "清理任务已启动。", "task_id": task_id}

# backend/main.py (新增路由)

class ScreenshotRestoreRequest(BaseModel):
    scope: ScheduledTasksTargetScope
    overwrite: bool

@app.post("/api/episode-refresher/restore-from-github")
def restore_screenshots_from_github_api(req: ScreenshotRestoreRequest):
    """启动一个任务，从 GitHub 备份反向恢复截图到 Emby"""
    task_cat = "API-截图恢复(反向)"
    ui_logger.info(f"收到从 GitHub 恢复截图的请求...", task_category=task_cat)
    
    config = app_config.load_app_config()
    logic = EpisodeRefresherLogic(config)
    task_name = f"从GitHub恢复截图 ({req.scope.mode})"
    task_id = task_manager.register_task(
        logic.restore_screenshots_from_github_task,
        task_name,
        scope=req.scope,
        overwrite=req.overwrite
    )
    return {"status": "success", "message": "从GitHub恢复截图的任务已启动。", "task_id": task_id}

@app.post("/api/webhook/emby")
async def emby_webhook_receiver(payload: EmbyWebhookPayload):
    try:
        payload_json_str = payload.model_dump_json(indent=4, exclude_unset=True)
        logging.info(f"【Webhook调试】收到来自 Emby 的完整 Payload 内容:\n{payload_json_str}")
    except Exception as e:
        logging.error(f"【Webhook调试】打印 Payload 时发生错误: {e}")

    task_cat = "Webhook"
    ui_logger.info(f"➡️ 收到来自 Emby 的通知，事件: {payload.Event}", task_category=task_cat)
    
    config = app_config.load_app_config()
    if not config.webhook_config.enabled:
        ui_logger.info("【跳过】Webhook 功能未启用，忽略本次通知。", task_category=task_cat)
        return {"status": "skipped", "message": "Webhook processing is disabled."}

    if not payload.Item:
        ui_logger.info("【跳过】收到的通知中不包含有效的 Item 信息，可能是测试通知或无关事件。", task_category=task_cat)
        return {"status": "success_test_skipped", "message": "Test notification received successfully."}

    target_item_id = None
    target_item_name = payload.Item.Name
    target_item_type = payload.Item.Type

    if payload.Event in ["item.add", "library.new"]:
        if target_item_type in ["Movie", "Series"]:
            target_item_id = payload.Item.Id
            ui_logger.info(f"  - [主流程] 检测到新 [电影/剧集] 入库: 【{target_item_name}】 (ID: {target_item_id})", task_category=task_cat)
        
        elif target_item_type == "Episode":
            episode_id = payload.Item.Id
            ui_logger.info(f"  - [分集流程] 检测到新 [剧集分集] 入库: 【{target_item_name}】 (ID: {episode_id})", task_category=task_cat)
            
            try:
                server_conf = config.server_config
                url = f"{server_conf.server}/Users/{server_conf.user_id}/Items/{episode_id}"
                params = {"api_key": server_conf.api_key, "Fields": "SeriesId,SeriesName"}
                response = requests.get(url, params=params, timeout=15)
                response.raise_for_status()
                episode_details = response.json()
                
                series_id = episode_details.get("SeriesId")
                series_name = episode_details.get("SeriesName")

                if series_id and series_name:
                    ui_logger.info(f"  - [分集流程] 成功找到所属剧集: 【{series_name}】 (ID: {series_id})", task_category=task_cat)
                    
                    # --- 核心新增：事件收集逻辑 ---
                    with episode_sync_queue_lock:
                        if series_id not in episode_sync_queue:
                            episode_sync_queue[series_id] = {
                                "episode_ids": set(),
                                "series_name": series_name,
                                "last_update": 0
                            }
                            ui_logger.info(f"    - [收集器] 首次记录剧集《{series_name}》，已创建新的同步队列。", task_category=task_cat)
                        
                        episode_sync_queue[series_id]["episode_ids"].add(episode_id)
                        episode_sync_queue[series_id]["last_update"] = time.time()
                        
                        queue_size = len(episode_sync_queue[series_id]["episode_ids"])
                        ui_logger.info(f"    - [收集器] 已将分集 {episode_id} 添加到队列。剧集《{series_name}》当前待同步分集数: {queue_size}。静默倒计时已重置。", task_category=task_cat)
                    # --- 核心新增结束 ---

                    # 主流程依然只处理剧集ID
                    target_item_id = series_id
                    target_item_name = series_name
                else:
                    ui_logger.warning(f"  - ⚠️ [分集流程] 无法从分集【{target_item_name}】中找到所属剧集的ID，跳过处理。", task_category=task_cat)

            except requests.RequestException as e:
                ui_logger.error(f"  - ❌ [分集流程] 查询剧集详情失败: {e}，跳过处理。", task_category=task_cat)
        
    if target_item_id:
        if target_item_id in webhook_processing_set:
            ui_logger.info(f"  - [主流程-跳过] 任务【{target_item_name}】(ID: {target_item_id}) 已在主处理队列中，本次通知的主流程部分跳过。", task_category=task_cat)
            return {"status": "skipped_in_queue", "message": "Task is already in the processing queue."}
        
        await webhook_queue.put((target_item_id, target_item_name))
        webhook_processing_set.add(target_item_id)
        ui_logger.info(f"  - [主流程-入队] 已将任务【{target_item_name}】(ID: {target_item_id}) 添加到主处理队列。当前队列长度: {webhook_queue.qsize()}", task_category=task_cat)
        
        return {"status": "success_queued", "message": f"Task for item {target_item_id} has been queued."}
    
    ui_logger.info(f"【跳过】事件 '{payload.Event}' 或类型 '{target_item_type}' 无需处理。", task_category=task_cat)
    return {"status": "skipped", "message": "Event not applicable"}