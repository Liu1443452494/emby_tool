# backend/douban_manager.py (修改后)

import os
import json
import logging
import threading
from typing import List
from datetime import datetime
from task_manager import TaskManager
import config as app_config
from models import DoubanCacheStatus

# --- 核心修改：将缓存文件路径指向容器内的 /app/data 目录 ---
DOUBAN_CACHE_FILE = os.path.join('/app/data', 'douban_data.json')

def _parse_folder_name(folder_name):
    douban_id = 'N/A'
    imdb_id = 'N/A'
    if '_' in folder_name:
        parts = folder_name.split('_')
        db_part = parts[0]
        imdb_part = parts[1] if len(parts) > 1 else ''
        if db_part.isdigit() and db_part != '0':
            douban_id = db_part
        if imdb_part.startswith('tt'):
            imdb_id = imdb_part
    elif folder_name.isdigit():
        douban_id = folder_name
    return douban_id, imdb_id

def scan_douban_directory_task(directory: str, extra_fields: List[str], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
    logging.info(f"【豆瓣扫描】任务启动，开始扫描目录: {directory}")
    movie_dir = os.path.join(directory, 'douban-movies')
    series_dir = os.path.join(directory, 'douban-tv')
    
    media_folders = []
    if os.path.isdir(movie_dir):
        for folder in os.listdir(movie_dir):
            full_path = os.path.join(movie_dir, folder)
            if os.path.isdir(full_path):
                media_folders.append({'path': full_path, 'type': 'Movie'})
    
    if os.path.isdir(series_dir):
        for folder in os.listdir(series_dir):
            full_path = os.path.join(series_dir, folder)
            if os.path.isdir(full_path):
                media_folders.append({'path': full_path, 'type': 'TVShow'})

    total_folders = len(media_folders)
    task_manager.update_task_progress(task_id, 0, total_folders)
    logging.info(f"【豆瓣扫描】共找到 {total_folders} 个媒体文件夹待处理。")
    
    final_data = {}
    found_count = 0

    for i, folder_info in enumerate(media_folders):
        if cancellation_event.is_set():
            logging.warning("【豆瓣扫描】任务被用户取消。")
            return

        folder_path = folder_info['path']
        folder_name = os.path.basename(folder_path)
        media_type = folder_info['type']
        
        logging.info(f"【豆瓣扫描】进度 {i+1}/{total_folders}: 正在处理 [{folder_name}]")
        task_manager.update_task_progress(task_id, i + 1, total_folders)

        json_filename = 'all.json' if media_type == 'Movie' else 'series.json'
        json_path = os.path.join(folder_path, json_filename)

        if not os.path.isfile(json_path):
            logging.warning(f"【豆瓣扫描】警告：在目录 {folder_path} 中未找到元数据文件 {json_filename}，已跳过。")
            continue

        try:
            douban_id, imdb_id = _parse_folder_name(folder_name)
            if douban_id == 'N/A':
                logging.warning(f"【豆瓣扫描】警告：无法从文件夹名 {folder_name} 解析出豆瓣ID，已跳过。")
                continue

            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            item_data = {
                'type': media_type,
                'title': data.get('title', 'N/A'),
                'year': data.get('year', ''),
                'genres': data.get('genres', []),
                'intro': data.get('intro', ''),
                'pic': data.get('pic', {}),
                'actors': [
                    {
                        'id': actor.get('id'),
                        'name': actor.get('name'),
                        'character': actor.get('character'),
                        'avatar': actor.get('avatar', {})
                    } for actor in data.get('actors', [])
                ],
                'imdb_id': imdb_id
            }

            if 'rating' in extra_fields:
                item_data['rating'] = data.get('rating', {}).get('value')
            if 'pubdate' in extra_fields:
                item_data['pubdate'] = data.get('pubdate', [])
            if 'card_subtitle' in extra_fields:
                item_data['card_subtitle'] = data.get('card_subtitle', '')
            if 'languages' in extra_fields:
                item_data['languages'] = data.get('languages', [])
            if 'countries' in extra_fields:
                item_data['countries'] = data.get('countries', [])
            if 'durations' in extra_fields and media_type == 'Movie':
                item_data['durations'] = data.get('durations', [])
            
            final_data[douban_id] = item_data
            found_count += 1
        except json.JSONDecodeError:
            logging.error(f"【豆瓣扫描】错误：解析JSON文件失败: {json_path}")
        except Exception as e:
            logging.error(f"【豆瓣扫描】错误：处理文件夹 {folder_path} 时发生未知错误: {e}")

    logging.info(f"【豆瓣扫描】扫描完成，共解析 {found_count} 个有效的元数据文件。")
    
    try:
        # --- 核心修改：确保在写入前，/app/data 目录存在 ---
        cache_dir = os.path.dirname(DOUBAN_CACHE_FILE)
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)

        logging.info(f"【豆瓣扫描】正在将 {found_count} 条数据写入缓存文件: {DOUBAN_CACHE_FILE}")
        with open(DOUBAN_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(final_data, f, ensure_ascii=False, indent=4)
        logging.info("【豆瓣扫描】缓存文件写入成功！")

        config = app_config.load_app_config()
        mtime = os.path.getmtime(DOUBAN_CACHE_FILE)
        last_modified = datetime.fromtimestamp(mtime).isoformat()
        
        config.douban_cache_status = DoubanCacheStatus(
            exists=True,
            item_count=found_count,
            last_modified=last_modified,
            is_scanning=False
        )
        app_config.save_app_config(config)
        logging.info("【豆瓣扫描】已更新配置文件中的缓存状态。")

    except Exception as e:
        logging.error(f"【豆瓣扫描】错误：写入缓存或更新配置失败: {e}")

    return {"found_count": found_count}