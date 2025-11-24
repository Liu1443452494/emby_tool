

import os
import json
import logging
import threading
from typing import List
from datetime import datetime
from task_manager import TaskManager
import config as app_config
from models import DoubanCacheStatus
from log_manager import ui_logger

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

# backend/douban_manager.py (函数替换)

def scan_douban_directory_task(directory: str, extra_fields: List[str], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
    task_cat = "豆瓣扫描"
    ui_logger.info("➡️ 【步骤 1/5】任务启动，开始扫描豆瓣数据目录...", task_category=task_cat)
    
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
    
    ui_logger.info(f"✅ 【步骤 2/5】目录扫描完成，共找到 {total_folders} 个媒体文件夹。", task_category=task_cat)
    ui_logger.info("➡️ 【步骤 3/5】开始解析元数据文件，过程中的详细日志将写入后端日志文件...", task_category=task_cat)
    
    final_data = {}
    found_count = 0
    skipped_no_json_count = 0
    skipped_no_id_count = 0
    error_json_count = 0
    error_unknown_count = 0

    for i, folder_info in enumerate(media_folders):
        if cancellation_event.is_set():
            ui_logger.warning("⚠️ 任务被用户取消。", task_category=task_cat)
            return

        folder_path = folder_info['path']
        folder_name = os.path.basename(folder_path)
        media_type = folder_info['type']
        
        # 仅在进度条更新时使用 logging.debug 记录详细信息到后端日志
        if (i + 1) % 100 == 0 or (i + 1) == total_folders:
            logging.debug(f"【豆瓣扫描】进度 {i+1}/{total_folders}: 正在处理【{folder_name}】")
        
        task_manager.update_task_progress(task_id, i + 1, total_folders)

        json_filename = 'all.json' if media_type == 'Movie' else 'series.json'
        json_path = os.path.join(folder_path, json_filename)

        if not os.path.isfile(json_path):
            logging.warning(f"【豆瓣扫描-跳过】在目录【{folder_path}】中未找到元数据文件 {json_filename}。")
            skipped_no_json_count += 1
            continue

        try:
            douban_id, imdb_id = _parse_folder_name(folder_name)
            if douban_id == 'N/A':
                logging.warning(f"【豆瓣扫描-跳过】无法从文件夹名【{folder_name}】解析出豆瓣ID。")
                skipped_no_id_count += 1
                continue

            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)


            #下方genres后移除简介  'intro': data.get('intro', ''),
            item_data = {
                'type': media_type,
                'title': data.get('title', 'N/A'),
                'year': data.get('year', ''),
                'genres': data.get('genres', []),
                'pic': data.get('pic', {}),
                'actors': [
                    {
                        'id': actor.get('id'),
                        'name': actor.get('name'),
                        'latin_name': actor.get('latin_name'),
                        'character': actor.get('character'),
                        'avatar': actor.get('avatar', {})
                    } for actor in data.get('actors', [])
                ],
                'imdb_id': imdb_id,
                'countries': data.get('countries', [])
            }

            if 'rating' in extra_fields:
                item_data['rating'] = data.get('rating', {}).get('value')
            if 'pubdate' in extra_fields:
                item_data['pubdate'] = data.get('pubdate', [])
            if 'card_subtitle' in extra_fields:
                item_data['card_subtitle'] = data.get('card_subtitle', '')
            if 'languages' in extra_fields:
                item_data['languages'] = data.get('languages', [])
            if 'durations' in extra_fields and media_type == 'Movie':
                item_data['durations'] = data.get('durations', [])
            
            final_data[douban_id] = item_data
            found_count += 1
        except json.JSONDecodeError:
            logging.error(f"【豆瓣扫描-错误】解析JSON文件失败: {json_path}")
            error_json_count += 1
        except Exception as e:
            logging.error(f"【豆瓣扫描-错误】处理文件夹【{folder_path}】时发生未知错误: {e}", exc_info=True)
            error_unknown_count += 1

    ui_logger.info(f"✅ 【步骤 4/5】元数据解析完成！", task_category=task_cat)
    # --- 汇总报告 ---
    ui_logger.info(f"""
    - - - - - - - - 扫描结果汇总 - - - - - - - -
    ✅ 成功解析: {found_count} 条
    ⚠️ 跳过 (缺少元数据文件): {skipped_no_json_count} 条
    ⚠️ 跳过 (无法解析ID): {skipped_no_id_count} 条
    ❌ 失败 (JSON格式错误): {error_json_count} 条
    ❌ 失败 (其他未知错误): {error_unknown_count} 条
    - - - - - - - - - - - - - - - - - - - - - - -
    """, task_category=task_cat)
    
    try:
        cache_dir = os.path.dirname(DOUBAN_CACHE_FILE)
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)

        old_data_keys = set()
        if os.path.exists(DOUBAN_CACHE_FILE):
            try:
                with open(DOUBAN_CACHE_FILE, 'r', encoding='utf-8') as f:
                    old_data = json.load(f)
                old_data_keys = set(old_data.keys())
            except (IOError, json.JSONDecodeError):
                ui_logger.warning("⚠️ 读取旧缓存文件失败，无法进行数据对比。", task_category=task_cat)

        new_data_keys = set(final_data.keys())
        added_count = len(new_data_keys - old_data_keys)
        removed_count = len(old_data_keys - new_data_keys)
        
        if old_data_keys:
            ui_logger.info(f"🔄 数据对比：新增 {added_count} 条，移除 {removed_count} 条。", task_category=task_cat)

        ui_logger.info(f"➡️ 【步骤 5/5】正在将 {found_count} 条数据写入缓存文件...", task_category=task_cat)
        with open(DOUBAN_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(final_data, f, ensure_ascii=False, indent=4)
        ui_logger.info("✅ 【步骤 5/5】缓存文件写入成功！", task_category=task_cat)

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
        ui_logger.error(f"❌ 写入缓存或更新配置失败: {e}", task_category=task_cat, exc_info=True)

    return {"found_count": found_count}