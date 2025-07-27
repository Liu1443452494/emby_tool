# backend/upcoming_logic.py (新文件)

import logging
import os
import json
import time
from typing import Dict, Any, Optional, List, Literal
from datetime import datetime, timedelta, timezone
from filelock import FileLock, Timeout

from models import AppConfig, UpcomingSubscriptionItem
from log_manager import ui_logger
from trakt_manager import TraktManager
from tmdb_logic import TmdbLogic
from notification_manager import notification_manager, escape_markdown

UPCOMING_SUBSCRIPTIONS_FILE = os.path.join('/app/data', 'upcoming_subscriptions.json')
UPCOMING_CACHE_FILE = os.path.join('/app/data', 'upcoming_cache.json')
CACHE_DURATION_HOURS = 2

class UpcomingLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.config = app_config.upcoming_config
        self.trakt_manager = TraktManager(app_config)
        self.tmdb_logic = TmdbLogic(app_config)

    # backend/upcoming_logic.py (函数替换)
    def _get_cached_list(self) -> Optional[List[Dict]]:
        task_cat = "即将上映-缓存"
        if not os.path.exists(UPCOMING_CACHE_FILE):
            return None
        try:
            with open(UPCOMING_CACHE_FILE, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            timestamp_str = cache_data.get("timestamp")
            if not timestamp_str:
                return None
            
            timestamp = datetime.fromisoformat(timestamp_str)
            age = datetime.now(timezone.utc) - timestamp
            
            # --- 修改 ---
            if age < timedelta(hours=CACHE_DURATION_HOURS):
                remaining_time = timedelta(hours=CACHE_DURATION_HOURS) - age
                remaining_minutes = int(remaining_time.total_seconds() / 60)
                ui_logger.info(f"✅ 命中缓存！数据将在约 {remaining_minutes} 分钟后过期。", task_category=task_cat)
                return cache_data.get("data")
            else:
                ui_logger.info(f"⚠️ 缓存已过期 (存在时长: {age})，将重新获取。", task_category=task_cat)
                return None
            # --- 修改结束 ---
        except (IOError, json.JSONDecodeError) as e:
            ui_logger.error(f"❌ 读取缓存文件失败: {e}", task_category=task_cat)
            return None

    
    def _save_to_cache(self, data: List[Dict]):
        task_cat = "即将上映-缓存"
        try:
            cache_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": data
            }
            with open(UPCOMING_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=4)
            # --- 修改 ---
            ui_logger.info(f"✅ 成功将 {len(data)} 条数据写入缓存，有效期 {CACHE_DURATION_HOURS} 小时。", task_category=task_cat)
            # --- 修改结束 ---
        except IOError as e:
            ui_logger.error(f"❌ 写入缓存文件失败: {e}", task_category=task_cat)

    def _apply_3d_filtering(self, raw_items: List[Dict], filters: Dict) -> List[Dict]:
        task_cat = "即将上映-筛选"
        ui_logger.info("➡️ [步骤 2/3] 开始应用三维分层预筛选策略...", task_category=task_cat)
        
        verified_items = []
        processed_ids = set()

        for item in raw_items:
            media_type = item.get('media_type')
            media_info = item.get('movie') if media_type == 'movie' else item.get('show')
            if not media_info: continue

            tmdb_id = media_info.get('ids', {}).get('tmdb')
            if not tmdb_id or tmdb_id in processed_ids: continue
            
            title = media_info.get('original_title') or media_info.get('title', 'N/A')
            
            # 1. 类型过滤
            genres = media_info.get('genres', [])
            if any(genre in filters['genre_blacklist'] for genre in genres):
                logging.debug(f"  - [丢弃] {title}: 类型在黑名单中 ({genres})")
                continue

            # 2. 市场优先级过滤
            country = media_info.get('country', '')
            language = media_info.get('language', '')
            translations = media_info.get('available_translations', [])

            is_p0 = (country in filters['p0_countries']) or (language in filters['p0_languages'])
            is_p1 = (country in filters['p1_countries']) and ('zh' in translations)

            if is_p0 or is_p1:
                reason = "核心市场" if is_p0 else "潜力市场"
                logging.debug(f"  - [保留] {title}: {reason}")
                
                release_date = item.get('released') or item.get('first_aired')
                if release_date:
                    release_date_str = datetime.fromisoformat(release_date.replace('Z', '+00:00')).strftime('%Y-%m-%d')
                    verified_items.append({'tmdb_id': tmdb_id, 'media_type': media_type, 'release_date': release_date_str})
                    processed_ids.add(tmdb_id)
            else:
                logging.debug(f"  - [丢弃] {title}: 低优先级 (国家: {country}, 语言: {language})")

        ui_logger.info(f"✅ [步骤 2/3] 预筛选完成。候选条目从 {len(raw_items)} 个减少到 {len(verified_items)} 个。", task_category=task_cat)
        return verified_items

    def get_upcoming_list(self, dynamic_filters: Optional[Dict] = None) -> List[Dict]:
        task_cat = "即将上映-获取"
        
        # 1. 参数合并
        filters = self.config.filters.model_dump()
        if dynamic_filters and not dynamic_filters.get('use_defaults', True):
            ui_logger.info("🔍 检测到动态筛选条件，将覆盖默认配置。", task_category=task_cat)
            for key, value in dynamic_filters.items():
                if key in filters:
                    filters[key] = value
        
        # 尝试从缓存获取
        cached_list = self._get_cached_list()
        if cached_list:
            return cached_list

        # 2. 从 Trakt 获取原始数据
        ui_logger.info(f"➡️ [步骤 1/3] 开始从 Trakt 获取未来 {filters['fetch_days']} 天的日历数据...", task_category=task_cat)
        start_date = datetime.now().strftime('%Y-%m-%d')
        raw_items = []
        
        movies = self.trakt_manager.get_upcoming_calendar_raw('movies', start_date, filters['fetch_days'])
        if movies:
            for item in movies: item['media_type'] = 'movie'
            raw_items.extend(movies)
        
        shows = self.trakt_manager.get_upcoming_calendar_raw('shows', start_date, filters['fetch_days'])
        if shows:
            # 仅保留新剧首播
            new_shows = [item for item in shows if item.get('episode', {}).get('episode_type') == 'series_premiere']
            for item in new_shows: item['media_type'] = 'tv'
            raw_items.extend(new_shows)
        
        ui_logger.info(f"✅ [步骤 1/3] 完成。共获取到 {len(raw_items)} 条原始记录。", task_category=task_cat)

        # 3. 应用筛选
        filtered_items = self._apply_3d_filtering(raw_items, filters)

        # 4. 从 TMDB 获取最终详情
        ui_logger.info(f"➡️ [步骤 3/3] 开始从 TMDB 获取 {len(filtered_items)} 个项目的详细中文信息...", task_category=task_cat)
        final_list = []
        for item in filtered_items:
            try:
                endpoint = f"{item['media_type']}/{item['tmdb_id']}"
                params = {'language': 'zh-CN', 'append_to_response': 'images'}
                details = self.tmdb_logic._tmdb_request(endpoint, params)
                
                final_list.append({
                    "tmdb_id": details['id'],
                    "media_type": item['media_type'],
                    "title": details.get('title') or details.get('name'),
                    "overview": details.get('overview'),
                    "poster_path": details.get('poster_path'),
                    "release_date": item['release_date']
                })
                time.sleep(0.1) # API 礼貌性延迟
            except Exception as e:
                logging.error(f"获取 TMDB 详情失败 (ID: {item['tmdb_id']}): {e}")
        
        ui_logger.info(f"✅ [步骤 3/3] 完成。最终生成 {len(final_list)} 条高质量结果列表。", task_category=task_cat)
        
        # 5. 写入缓存并返回
        self._save_to_cache(final_list)
        return final_list

    def get_subscriptions(self) -> Dict[str, Any]:
        if not os.path.exists(UPCOMING_SUBSCRIPTIONS_FILE):
            return {}
        try:
            with open(UPCOMING_SUBSCRIPTIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError):
            return {}

    def add_subscription(self, item_data: Dict) -> bool:
        task_cat = "即将上映-订阅"
        try:
            with FileLock(UPCOMING_SUBSCRIPTIONS_FILE + ".lock", timeout=5):
                subs = self.get_subscriptions()
                tmdb_id_str = str(item_data['tmdb_id'])
                if tmdb_id_str in subs:
                    ui_logger.warning(f"⚠️ 《{item_data['title']}》已在订阅列表中。", task_category=task_cat)
                    return True
                
                subs[tmdb_id_str] = UpcomingSubscriptionItem(**item_data).model_dump()
                
                with open(UPCOMING_SUBSCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(subs, f, ensure_ascii=False, indent=4)
                
                ui_logger.info(f"✅ 成功订阅《{item_data['title']}》！", task_category=task_cat)
                return True
        except Timeout:
            ui_logger.error("❌ 添加订阅失败：获取文件锁超时。", task_category=task_cat)
            return False
        except Exception as e:
            ui_logger.error(f"❌ 添加订阅失败: {e}", task_category=task_cat)
            return False

    def remove_subscription(self, tmdb_id: int) -> bool:
        task_cat = "即将上映-订阅"
        try:
            with FileLock(UPCOMING_SUBSCRIPTIONS_FILE + ".lock", timeout=5):
                subs = self.get_subscriptions()
                tmdb_id_str = str(tmdb_id)
                if tmdb_id_str not in subs:
                    return True
                
                title = subs[tmdb_id_str].get('title', f"ID {tmdb_id}")
                del subs[tmdb_id_str]
                
                with open(UPCOMING_SUBSCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(subs, f, ensure_ascii=False, indent=4)
                
                ui_logger.info(f"✅ 已取消对《{title}》的订阅。", task_category=task_cat)
                return True
        except Timeout:
            ui_logger.error("❌ 取消订阅失败：获取文件锁超时。", task_category=task_cat)
            return False
        except Exception as e:
            ui_logger.error(f"❌ 取消订阅失败: {e}", task_category=task_cat)
            return False

    def check_and_notify(self):
        task_cat = "定时任务-订阅通知"
        ui_logger.info("➡️ 开始检查订阅列表并发送通知...", task_category=task_cat)
        
        if not self.app_config.telegram_config.enabled:
            ui_logger.warning("⚠️ Telegram 通知未启用，任务跳过。", task_category=task_cat)
            return

        subs = self.get_subscriptions()
        if not subs:
            ui_logger.info("✅ 订阅列表为空，无需发送通知。", task_category=task_cat)
            return

        today = datetime.now().date()
        notifications = {0: [], 1: [], 2: [], 3: []} # 0:今天, 1:明天, ...

        for tmdb_id, item_info in subs.items():
            try:
                release_date = datetime.strptime(item_info['release_date'], '%Y-%m-%d').date()
                delta_days = (release_date - today).days
                
                if 0 <= delta_days <= 3:
                    notifications[delta_days].append(item_info['title'])
            except (ValueError, KeyError):
                continue
        
        message_parts = []
        if notifications[0]:
            titles = "、".join([f"《{escape_markdown(t)}》" for t in notifications[0]])
            message_parts.append(f"🎉 *今日首映*\n{titles}")
        
        upcoming_parts = []
        if notifications[1]:
            titles = "、".join([f"《{escape_markdown(t)}》" for t in notifications[1]])
            upcoming_parts.append(f"明天: {titles}")
        if notifications[2]:
            titles = "、".join([f"《{escape_markdown(t)}》" for t in notifications[2]])
            upcoming_parts.append(f"后天: {titles}")
        if notifications[3]:
            titles = "、".join([f"《{escape_markdown(t)}》" for t in notifications[3]])
            upcoming_parts.append(f"3天后: {titles}")
        
        if upcoming_parts:
            message_parts.append(f"📅 *即将上映*\n- " + "\n- ".join(upcoming_parts))

        if not message_parts:
            ui_logger.info("✅ 检查完毕，未来3天内没有即将上映的订阅项目。", task_category=task_cat)
            return
            
        final_message = "🔔 *订阅日历提醒*\n\n" + "\n\n".join(message_parts)
        notification_manager.send_telegram_message(final_message, self.app_config)
        ui_logger.info("✅ 成功发送订阅通知！", task_category=task_cat)