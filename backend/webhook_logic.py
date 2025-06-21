# backend/webhook_logic.py (新文件)

import logging
import threading
import time
import os
import json

from models import AppConfig
from task_manager import TaskManager
import config as app_config

# 导入需要用到的逻辑类
from douban_fixer_logic import DoubanFixerLogic
from actor_localizer_logic import ActorLocalizerLogic
from douban_poster_updater_logic import DoubanPosterUpdaterLogic
from douban_manager import DOUBAN_CACHE_FILE, _parse_folder_name

class WebhookLogic:
    def __init__(self, config: AppConfig):
        self.config = config
        self.server_config = config.server_config
        self.webhook_config = config.webhook_config # 假设我们在模型中会添加这个

    def _get_emby_item_details(self, item_id: str):
        """一个辅助方法，用于获取 Emby 媒体项的 ProviderIds"""
        # 这个逻辑可以从其他 logic 类中借鉴，这里为了独立性重新实现
        import requests
        url = f"{self.server_config.server}/Users/{self.server_config.user_id}/Items/{item_id}"
        params = {"api_key": self.server_config.api_key, "Fields": "ProviderIds,Name,Type"}
        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"【Webhook】获取 Emby 媒体详情 (ID: {item_id}) 失败: {e}")
            return None

    def _update_douban_cache_incrementally(self, douban_id: str, media_type: str) -> bool:
        """
        增量更新豆瓣缓存文件。
        :return: 如果数据被成功找到并更新到缓存中，返回 True。
        """
        logging.info(f"【Webhook-数据同步】开始为豆瓣ID {douban_id} 执行增量缓存更新...")
        
        # 1. 加载当前缓存
        try:
            with open(DOUBAN_CACHE_FILE, 'r', encoding='utf-8') as f:
                douban_map = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            douban_map = {}

        # 2. 内存中检查
        if douban_id in douban_map:
            logging.info(f"【Webhook-数据同步】豆瓣ID {douban_id} 的数据已存在于缓存中，跳过文件更新。")
            return True

        # 3. 定位新数据文件夹
        douban_data_root = self.config.douban_config.directory
        if not douban_data_root or not os.path.isdir(douban_data_root):
            logging.error("【Webhook-数据同步】豆瓣数据根目录未配置或无效，无法进行增量更新。")
            return False

        sub_dir = 'douban-movies' if media_type == 'Movie' else 'douban-tv'
        target_dir = os.path.join(douban_data_root, sub_dir)

        if not os.path.isdir(target_dir):
            logging.error(f"【Webhook-数据同步】找不到豆瓣数据子目录: {target_dir}")
            return False

        found_folder = None
        for folder_name in os.listdir(target_dir):
            parsed_db_id, _ = _parse_folder_name(folder_name)
            if parsed_db_id == douban_id:
                found_folder = os.path.join(target_dir, folder_name)
                break
        
        if not found_folder:
            logging.error(f"【Webhook-数据同步】在 {target_dir} 中未找到与豆瓣ID {douban_id} 匹配的文件夹。")
            return False

        # 4. 读取并解析新数据
        json_filename = 'all.json' if media_type == 'Movie' else 'series.json'
        json_path = os.path.join(found_folder, json_filename)

        if not os.path.isfile(json_path):
            logging.error(f"【Webhook-数据同步】在目录 {found_folder} 中未找到元数据文件 {json_filename}。")
            return False

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                new_data = json.load(f)
            
            # 提取所需字段，与全量扫描保持一致
            item_data = {
                'type': media_type,
                'title': new_data.get('title', 'N/A'),
                'year': new_data.get('year', ''),
                'genres': new_data.get('genres', []),
                'intro': new_data.get('intro', ''),
                'pic': new_data.get('pic', {}),
                'actors': [
                    {
                        'id': actor.get('id'),
                        'name': actor.get('name'),
                        'character': actor.get('character'),
                        'avatar': actor.get('avatar', {})
                    } for actor in new_data.get('actors', [])
                ],
                'imdb_id': _parse_folder_name(os.path.basename(found_folder))[1]
            }
            # 添加额外字段
            extra_fields = self.config.douban_config.extra_fields
            if 'rating' in extra_fields: item_data['rating'] = new_data.get('rating', {}).get('value')
            if 'pubdate' in extra_fields: item_data['pubdate'] = new_data.get('pubdate', [])
            # ... (可以根据需要添加所有额外字段的逻辑)

            # 5. 更新内存并写回文件
            douban_map[douban_id] = item_data
            with open(DOUBAN_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(douban_map, f, ensure_ascii=False, indent=4)
            
            logging.info(f"【Webhook-数据同步】成功将豆瓣ID {douban_id} 的数据增量更新到缓存文件。")
            return True

        except Exception as e:
            logging.error(f"【Webhook-数据同步】处理或写入新豆瓣数据时失败: {e}", exc_info=True)
            return False


    def process_new_media_task(self, item_id: str, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """
        由 Webhook 触发的，对单个新媒体项进行自动化处理的任务链。
        """
        logging.info(f"【Webhook任务】已启动，开始处理新入库媒体 (ID: {item_id})")
        
        # --- 步骤 0: 初始等待 ---
        wait_time = self.webhook_config.initial_wait_time
        logging.info(f"【Webhook任务】【步骤 0/5 | 初始等待】等待 {wait_time} 秒，以便 Emby 自动刮削... (可配置)")
        time.sleep(wait_time)
        if cancellation_event.is_set(): return

        # --- 步骤 1: 获取豆瓣ID ---
        logging.info(f"【Webhook任务】【步骤 1/5 | 获取豆瓣ID】开始...")
        item_details = self._get_emby_item_details(item_id)
        if not item_details:
            logging.error(f"【Webhook任务】无法获取媒体 {item_id} 的详细信息，任务中止。")
            return

        item_name = item_details.get("Name", f"Item {item_id}")
        item_type = item_details.get("Type", "Movie") # 默认为 Movie
        task_manager.tasks[task_id]['name'] = f"Webhook-自动处理-{item_name}" # 更新任务名
        
        douban_id = None
        provider_ids = item_details.get("ProviderIds", {})
        douban_id = next((v for k, v in provider_ids.items() if k.lower() == 'douban'), None)

        if douban_id:
            logging.info(f"【Webhook任务】【豆瓣ID修复】媒体 [{item_name}] 已有关联的豆瓣ID: {douban_id}，跳过ID修复步骤。")
        else:
            logging.info(f"【Webhook任务】【豆瓣ID修复】媒体 [{item_name}] 缺少豆瓣ID，开始执行ID修复...")
            fixer_logic = DoubanFixerLogic(self.config)
            if fixer_logic._process_single_item_for_fixing(item_id):
                # 修复成功后，重新获取详情以拿到新的豆瓣ID
                refreshed_details = self._get_emby_item_details(item_id)
                douban_id = next((v for k, v in refreshed_details.get("ProviderIds", {}).items() if k.lower() == 'douban'), None)
                logging.info(f"【Webhook任务】【豆瓣ID修复】成功修复并获取到新的豆瓣ID: {douban_id}")
            else:
                logging.error(f"【Webhook任务】【豆瓣ID修复】ID修复失败。")
        
        if not douban_id:
            logging.error(f"【Webhook任务】最终未能获取到豆瓣ID，自动化流程中止。")
            return
        if cancellation_event.is_set(): return

        # --- 步骤 2: 同步豆瓣数据 ---
        logging.info(f"【Webhook任务】【步骤 2/5 | 同步豆瓣数据】开始...")
        wait_time_for_plugin = self.webhook_config.plugin_wait_time
        logging.info(f"【Webhook任务】【数据同步】等待 {wait_time_for_plugin} 秒，以便 Emby 豆瓣插件下载元数据... (可配置)")
        time.sleep(wait_time_for_plugin)
        
        if not self._update_douban_cache_incrementally(douban_id, item_type):
            logging.error(f"【Webhook任务】【数据同步】未能从本地获取到豆瓣ID {douban_id} 的元数据，后续流程可能失败或使用旧数据。")
            # 根据严格程度，可以选择在这里中止。目前我们选择继续，让后续任务自己处理数据缺失。
        if cancellation_event.is_set(): return

        # --- 步骤 3: 演员中文化 ---
        logging.info(f"【Webhook任务】【步骤 3/5 | 演员中文化】开始...")
        try:
            localizer_logic = ActorLocalizerLogic(self.config)
            localizer_logic._process_single_item_for_localization(item_id, self.config.actor_localizer_config)
        except Exception as e:
            logging.error(f"【Webhook任务】【演员中文化】步骤执行失败，但将继续后续任务。错误: {e}", exc_info=True)
        if cancellation_event.is_set(): return

        # --- 步骤 4: 豆瓣海报更新 ---
        logging.info(f"【Webhook任务】【步骤 4/5 | 豆瓣海报更新】开始...")
        try:
            poster_logic = DoubanPosterUpdaterLogic(self.config)
            poster_logic.run_poster_update_for_items([item_id], self.config.douban_poster_updater_config, cancellation_event, task_id, task_manager)
        except Exception as e:
            logging.error(f"【Webhook任务】【豆瓣海报更新】步骤执行失败。错误: {e}", exc_info=True)
        if cancellation_event.is_set(): return
        
        # --- 步骤 5: 结束 ---
        logging.info(f"【Webhook任务】【步骤 5/5 | 完成】媒体 [{item_name}] 的自动化处理流程已全部执行完毕。")