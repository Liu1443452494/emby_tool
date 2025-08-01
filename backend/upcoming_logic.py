# backend/upcoming_logic.py (完整文件覆盖)

import logging
import os
import json
import time
from typing import Dict, Any, Optional, List, Literal, Tuple
from datetime import datetime, timedelta, timezone
from filelock import FileLock, Timeout

from models import AppConfig
from log_manager import ui_logger
from trakt_manager import TraktManager
from tmdb_logic import TmdbLogic
from notification_manager import notification_manager, escape_markdown

# --- 修改：移除订阅文件常量，修改缓存文件常量 ---
UPCOMING_DB_FILE = os.path.join('/app/data', 'upcoming_database.json')
# --- 修改结束 ---
CACHE_DURATION_HOURS = 12

class UpcomingLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.config = app_config.upcoming_config
        self.trakt_manager = TraktManager(app_config)
        self.tmdb_logic = TmdbLogic(app_config)

    def _read_db(self) -> Dict:
        """安全地读取数据库文件"""
        if not os.path.exists(UPCOMING_DB_FILE):
            return {"timestamp": None, "data": {}}
        try:
            with open(UPCOMING_DB_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content:
                    return {"timestamp": None, "data": {}}
                return json.loads(content)
        except (IOError, json.JSONDecodeError):
            return {"timestamp": None, "data": {}}

    

    def _write_db(self, db_content: Dict):
        """安全地写入数据库文件"""
        task_cat = "即将上映-数据库"
        try:
            # --- 核心修改：移除这里的 with FileLock ---
            with open(UPCOMING_DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(db_content, f, ensure_ascii=False, indent=4)
        except Exception as e:
            # --- 核心修改：调整日志，因为锁的错误会在调用方被捕获 ---
            ui_logger.error(f"❌ 写入数据库时发生IO错误: {e}", task_category=task_cat)
            raise # 抛出异常让上层处理

    def _is_cache_valid(self, db_content: Dict) -> Tuple[bool, str]:
        """检查 Trakt 缓存是否有效"""
        timestamp_str = db_content.get("timestamp")
        if not timestamp_str:
            return False, "无有效时间戳"
        
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
            age = datetime.now(timezone.utc) - timestamp
            
            if age < timedelta(hours=CACHE_DURATION_HOURS):
                remaining_time = timedelta(hours=CACHE_DURATION_HOURS) - age
                remaining_hours = int(remaining_time.total_seconds() // 3600)
                remaining_minutes = int((remaining_time.total_seconds() % 3600) // 60)
                if remaining_hours > 0:
                    return True, f"有效期剩余约 {remaining_hours} 小时 {remaining_minutes} 分钟"
                else:
                    return True, f"有效期剩余约 {remaining_minutes} 分钟"
            else:
                return False, f"缓存已于约 {int(age.total_seconds() // 3600 - CACHE_DURATION_HOURS)} 小时前过期"
        except ValueError:
            return False, "时间戳格式无效"

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
            
            genres = media_info.get('genres', [])
            if any(genre in filters['genre_blacklist'] for genre in genres):
                logging.debug(f"  - [丢弃] {title}: 类型在黑名单中 ({genres})")
                continue

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
                    verified_items.append({'tmdb_id': tmdb_id, 'media_type': media_type, 'release_date': release_date_str, 'is_ignored': False})
                    processed_ids.add(tmdb_id)
            else:
                logging.debug(f"  - [丢弃] {title}: 低优先级 (国家: {country}, 语言: {language})")

        ui_logger.info(f"✅ [步骤 2/3] 预筛选完成。候选条目从 {len(raw_items)} 个减少到 {len(verified_items)} 个。", task_category=task_cat)
        return verified_items

    def get_upcoming_list(self, dynamic_filters: Optional[Dict] = None) -> List[Dict]:
        task_cat = "即将上映-获取"
        ui_logger.info(f"➡️ [核心入口] get_upcoming_list 被调用。强制刷新: {bool(dynamic_filters and not dynamic_filters.get('use_defaults', True))}", task_category=task_cat)
        filters = self.config.filters.model_dump()
        force_refresh = False
        if dynamic_filters and not dynamic_filters.get('use_defaults', True):
            ui_logger.info("🔍 检测到动态筛选条件，将强制刷新。", task_category=task_cat)
            force_refresh = True
            for key, value in dynamic_filters.items():
                if key in filters:
                    filters[key] = value
        
        db_content = self._read_db()
        is_valid, reason = self._is_cache_valid(db_content)

        if is_valid and not force_refresh:
            ui_logger.info(f"✅ 命中 Trakt 日历缓存！{reason}。", task_category=task_cat)
        else:
            if force_refresh:
                ui_logger.info("🔄 用户请求应用新筛选条件，强制从 Trakt 刷新...", task_category=task_cat)
            else:
                ui_logger.warning(f"⚠️ Trakt 日历缓存已失效 ({reason})，开始从 Trakt 刷新...", task_category=task_cat)

            ui_logger.info(f"➡️ [步骤 1/3] 开始从 Trakt 获取未来 {filters['fetch_days']} 天的日历数据...", task_category=task_cat)
            start_date = datetime.now().strftime('%Y-%m-%d')
            raw_items = []
            
            movies = self.trakt_manager.get_upcoming_calendar_raw('movies', start_date, filters['fetch_days'])
            if movies:
                for item in movies: item['media_type'] = 'movie'
                raw_items.extend(movies)
            
            shows = self.trakt_manager.get_upcoming_calendar_raw('shows', start_date, filters['fetch_days'])
            if shows:
                new_shows = [item for item in shows if item.get('episode', {}).get('episode_type') == 'series_premiere']
                for item in new_shows: item['media_type'] = 'tv'
                raw_items.extend(new_shows)
            
            ui_logger.info(f"✅ [步骤 1/3] 完成。共获取到 {len(raw_items)} 条原始记录。", task_category=task_cat)

            filtered_items = self._apply_3d_filtering(raw_items, filters)

            ui_logger.info(f"➡️ [步骤 3/3] 开始从 TMDB 获取 {len(filtered_items)} 个项目的详细中文信息 (将跳过已有缓存)...", task_category=task_cat)
            new_items_count = 0
            skipped_items_count = 0
            

            for item in filtered_items:
                tmdb_id_str = str(item['tmdb_id'])
                if tmdb_id_str in db_content['data']:
                    logging.debug(f"  - [跳过] TMDB ID: {tmdb_id_str} 已存在于本地数据库。")
                    db_content['data'][tmdb_id_str]['release_date'] = item['release_date']
                    continue
                
                try:
                    endpoint = f"{item['media_type']}/{item['tmdb_id']}"
                    params = {'language': 'zh-CN', 'append_to_response': 'images,credits'}
                    details = self.tmdb_logic._tmdb_request(endpoint, params)
                    
                    if not details.get('poster_path'):
                        skipped_items_count += 1
                        item_title = details.get('title') or details.get('name', f"ID: {tmdb_id_str}")
                        logging.debug(f"  - [丢弃-调试] TMDB ID: {tmdb_id_str} (《{item_title}》) 因缺少 poster_path 而被忽略。")
                        continue
                    
                    raw_genres = [genre['name'] for genre in details.get('genres', [])]
                    genres = [
                        "科幻奇幻" if g == "Sci-Fi & Fantasy" else g
                        for g in raw_genres
                    ]
                    origin_country = details.get('origin_country', [])
                    popularity = details.get('popularity', 0)
                    cast = details.get('credits', {}).get('cast', [])
                    actors = [actor['name'] for actor in cast[:6]]

                    db_content['data'][tmdb_id_str] = {
                        "tmdb_id": details['id'],
                        "media_type": item['media_type'],
                        "title": details.get('title') or details.get('name'),
                        "overview": details.get('overview'),
                        "poster_path": details.get('poster_path'),
                        "release_date": item['release_date'],
                        "is_subscribed": False,
                        "subscribed_at": None,
                        "genres": genres,
                        "origin_country": origin_country,
                        "popularity": popularity,
                        "actors": actors,
                        "is_permanent": False,
                        "is_ignored": False
                    }
                    new_items_count += 1
                    logging.debug(f"  - [新增] 成功获取 TMDB ID: {tmdb_id_str} 的数据。")
                    time.sleep(0.1)
                except Exception as e:
                    logging.error(f"获取 TMDB 详情失败 (ID: {item['tmdb_id']}): {e}")
            
            summary_log = f"✅ [步骤 3/3] 完成。新增了 {new_items_count} 条高质量结果到数据库。"
            if skipped_items_count > 0:
                summary_log += f" 跳过了 {skipped_items_count} 条 (因TMDB数据不完整)。"
            ui_logger.info(summary_log, task_category=task_cat)

            rules = self.config.auto_subscribe_rules
            if rules.enabled:
                ui_logger.info("➡️ [步骤 4/4] 开始执行自动化订阅...", task_category=task_cat)
                auto_subscribed_count = 0
                
                rule_actors = {actor.strip().lower() for actor in rules.actors if actor.strip()}
                rule_countries = {country.strip().lower() for country in rules.countries if country.strip()}

                if not rule_actors and (not rule_countries or rules.min_popularity <= 0):
                     ui_logger.warning("   - [跳过] 自动化订阅已启用，但未配置任何有效规则。", task_category=task_cat)
                else:
                    today = datetime.now(timezone.utc).date()
                    for item in db_content['data'].values():
                        if item.get('is_subscribed'):
                            continue

                        try:
                            release_date_str = item.get('release_date')
                            if not release_date_str:
                                logging.debug(f"   - [跳过-自动订阅]《{item.get('title', '未知')}》因缺少上映日期而被忽略。")
                                continue
                            
                            item_release_date = datetime.fromisoformat(release_date_str).date()
                            
                            if item_release_date < today:
                                logging.debug(f"   - [跳过-自动订阅]《{item.get('title', '未知')}》因已上映 (日期: {release_date_str}) 而被忽略。")
                                continue
                        except (ValueError, TypeError):
                            logging.debug(f"   - [跳过-自动订阅]《{item.get('title', '未知')}》因日期格式无效 ({item.get('release_date')}) 而被忽略。")
                            continue

                        if rule_actors:
                            item_actors_lower = {actor.lower() for actor in item.get('actors', [])}
                            matched_actors = rule_actors.intersection(item_actors_lower)
                            if matched_actors:
                                item['is_subscribed'] = True
                                item['subscribed_at'] = datetime.now(timezone.utc).isoformat()
                                auto_subscribed_count += 1
                                ui_logger.info(f"   - ✅ 自动订阅《{item['title']}》，原因：匹配到演员关键词 '{next(iter(matched_actors))}'。", task_category=task_cat)
                                continue

                        if rule_countries and rules.min_popularity > 0:
                            item_countries_lower = {country.lower() for country in item.get('origin_country', [])}
                            if item_countries_lower.intersection(rule_countries):
                                if item.get('popularity', 0) >= rules.min_popularity:
                                    item['is_subscribed'] = True
                                    item['subscribed_at'] = datetime.now(timezone.utc).isoformat()
                                    auto_subscribed_count += 1
                                    ui_logger.info(f"   - ✅ 自动订阅《{item['title']}》，原因：满足国家匹配且热门度 ({item.get('popularity', 0):.2f}) >= {rules.min_popularity}。", task_category=task_cat)
                    
                    if auto_subscribed_count > 0:
                        ui_logger.info(f"🎉 [步骤 4/4] 自动化订阅完成，共新增 {auto_subscribed_count} 个订阅。", task_category=task_cat)
                    else:
                        ui_logger.info("   - [步骤 4/4] 自动化订阅检查完成，没有发现符合条件的新项目。", task_category=task_cat)
            
            db_content['timestamp'] = datetime.now(timezone.utc).isoformat()
            self._write_db(db_content)
            ui_logger.info(f"🎉 数据库更新完毕！Trakt 日历缓存时间戳已刷新。", task_category=task_cat)

        # --- 核心修改：应用两步过滤 ---
        # 步骤 1: 预过滤，移除不感兴趣的项目
        pre_filtered_data = [
            item for item in db_content['data'].values()
            if not item.get('is_ignored', False)
        ]
        
        # 步骤 2: 在预过滤结果上应用现有的保留逻辑
        today_str = datetime.now().strftime('%Y-%m-%d')
        final_list = [
            item for item in pre_filtered_data
            if item.get('is_permanent', False) or (item.get('release_date') and item['release_date'] >= today_str)
        ]
        # --- 修改结束 ---
        
        return sorted(final_list, key=lambda x: (x['release_date'], -x.get('popularity', 0)))


    def get_all_data(self) -> List[Dict]:
        """获取数据库中所有对前端可见的项目"""
        task_cat = "即将上映-获取"
        ui_logger.info("➡️ [核心入口] get_all_data 被调用 (仅读取本地数据库)。", task_category=task_cat)
        db_content = self._read_db()
        
        # --- 核心修改：应用两步过滤 ---
        # 步骤 1: 预过滤，移除不感兴趣的项目
        pre_filtered_data = [
            item for item in db_content['data'].values()
            if not item.get('is_ignored', False)
        ]
        
        # 步骤 2: 在预过滤结果上应用现有的保留逻辑
        today_str = datetime.now().strftime('%Y-%m-%d')
        final_list = [
            item for item in pre_filtered_data
            if item.get('is_permanent', False) or (item.get('release_date') and item['release_date'] >= today_str)
        ]
        # --- 修改结束 ---
        
        return sorted(final_list, key=lambda x: (x['release_date'], -x.get('popularity', 0)))


    def update_subscription(self, tmdb_id: int, subscribe: bool) -> bool:
        task_cat = "即将上映-订阅"
        try:
            # --- 核心修改：将 FileLock 移到这里，并管理完整的读-改-写事务 ---
            with FileLock(UPCOMING_DB_FILE + ".lock", timeout=10):
                db_content = self._read_db()
                tmdb_id_str = str(tmdb_id)
                
                if tmdb_id_str not in db_content['data']:
                    ui_logger.error(f"❌ 操作失败：数据库中未找到 TMDB ID 为 {tmdb_id} 的项目。", task_category=task_cat)
                    return False
                
                item = db_content['data'][tmdb_id_str]
                item['is_subscribed'] = subscribe
                item['subscribed_at'] = datetime.now(timezone.utc).isoformat() if subscribe else None
                
                # 直接在这里写入，而不是调用 _write_db
                with open(UPCOMING_DB_FILE, 'w', encoding='utf-8') as f:
                    json.dump(db_content, f, ensure_ascii=False, indent=4)
            # --- 修改结束 ---
                
            action_text = "订阅" if subscribe else "取消订阅"
            ui_logger.info(f"✅ 成功{action_text}《{item['title']}》！", task_category=task_cat)
            return True
        except Timeout:
            ui_logger.error("❌ 操作失败：获取文件锁超时，另一进程可能正在操作数据库。", task_category=task_cat)
            return False
        except Exception as e:
            ui_logger.error(f"❌ 操作失败: {e}", task_category=task_cat)
            return False

    def update_permanence(self, tmdb_id: int, is_permanent: bool) -> bool:
        task_cat = "即将上映-收藏"
        try:
            with FileLock(UPCOMING_DB_FILE + ".lock", timeout=10):
                db_content = self._read_db()
                tmdb_id_str = str(tmdb_id)
                
                if tmdb_id_str not in db_content['data']:
                    ui_logger.error(f"❌ 操作失败：数据库中未找到 TMDB ID 为 {tmdb_id} 的项目。", task_category=task_cat)
                    return False
                
                item = db_content['data'][tmdb_id_str]
                item['is_permanent'] = is_permanent
                
                with open(UPCOMING_DB_FILE, 'w', encoding='utf-8') as f:
                    json.dump(db_content, f, ensure_ascii=False, indent=4)
            
            action_text = "永久收藏" if is_permanent else "取消收藏"
            ui_logger.info(f"✅ 成功{action_text}《{item['title']}》！", task_category=task_cat)
            return True
        except Timeout:
            ui_logger.error("❌ 操作失败：获取文件锁超时。", task_category=task_cat)
            return False
        except Exception as e:
            ui_logger.error(f"❌ 操作失败: {e}", task_category=task_cat)
            return False
        

    def update_ignore_status(self, tmdb_id: int) -> bool:
        """将指定项目标记为不感兴趣"""
        task_cat = "即将上映-忽略"
        try:
            with FileLock(UPCOMING_DB_FILE + ".lock", timeout=10):
                db_content = self._read_db()
                tmdb_id_str = str(tmdb_id)
                
                if tmdb_id_str not in db_content['data']:
                    ui_logger.error(f"❌ 操作失败：数据库中未找到 TMDB ID 为 {tmdb_id} 的项目。", task_category=task_cat)
                    return False
                
                item = db_content['data'][tmdb_id_str]
                item['is_ignored'] = True
                
                with open(UPCOMING_DB_FILE, 'w', encoding='utf-8') as f:
                    json.dump(db_content, f, ensure_ascii=False, indent=4)
            
            ui_logger.info(f"✅ 已将《{item['title']}》标记为不感兴趣，它将不再显示。", task_category=task_cat)
            return True
        except Timeout:
            ui_logger.error("❌ 操作失败：获取文件锁超时，另一进程可能正在操作数据库。", task_category=task_cat)
            return False
        except Exception as e:
            ui_logger.error(f"❌ 操作失败: {e}", task_category=task_cat)
            return False

    def check_and_notify(self):
        task_cat = "定时任务-订阅通知"
        ui_logger.info("➡️ 开始检查订阅列表并发送通知...", task_category=task_cat)

        ui_logger.info("   - [步骤 1/3] 自动检查并按需更新“即将上映”数据...", task_category=task_cat)
        # 传入 use_defaults: True 来触发标准的缓存检查逻辑
        self.get_upcoming_list(dynamic_filters={'use_defaults': True})
        ui_logger.info("   - [步骤 1/3] 数据更新检查完成。", task_category=task_cat)
        
        if not self.app_config.telegram_config.enabled:
            ui_logger.warning("⚠️ Telegram 通知未启用，任务跳过。", task_category=task_cat)
            return

        db_content = self._read_db()
        subs = [item for item in db_content['data'].values() if item.get('is_subscribed')]
        
        if not subs:
            ui_logger.info("✅ 订阅列表为空，无需发送通知。", task_category=task_cat)
            return

        today = datetime.now().date()
        notifications = {0: [], 1: [], 2: [], 3: []}
        all_notified_items = []

        for item_info in subs:
            try:
                release_date = datetime.strptime(item_info['release_date'], '%Y-%m-%d').date()
                delta_days = (release_date - today).days
                
                if 0 <= delta_days <= 3:
                    notifications[delta_days].append(item_info)
                    all_notified_items.append(item_info)
            except (ValueError, KeyError):
                continue
        
        if not all_notified_items:
            ui_logger.info("✅ 检查完毕，未来3天内没有即将上映的订阅项目。", task_category=task_cat)
            return

        hottest_item = max(all_notified_items, key=lambda x: x.get('popularity', 0))
        poster_url = f"https://image.tmdb.org/t/p/w780{hottest_item['poster_path']}" if hottest_item.get('poster_path') else None
        ui_logger.info(f"🖼️ 已选择《{hottest_item['title']}》作为封面海报 (热度: {hottest_item.get('popularity', 0):.2f})。", task_category=task_cat)

        message_parts = []
        day_map = {0: "今日首映", 1: "明日上映", 2: "后天上映", 3: "3天后上映"}
        
        for day, items in notifications.items():
            if not items:
                continue
            
            date_obj = today + timedelta(days=day)
            date_str = date_obj.strftime('%Y-%m-%d')
            
            header = f"🎉 *{day_map[day]}* `({date_str})`"
            
            item_details_parts = []
            for item in sorted(items, key=lambda x: -x.get('popularity', 0)):
                title = escape_markdown(item['title'])
                year = escape_markdown(f"({item['release_date'][:4]})") if item.get('release_date') else ""
                actors = " / ".join(item.get('actors', []))
                actors_line = f" \- {escape_markdown(actors)}" if actors else ""
                
                item_details_parts.append(f"《{title}》{year}{actors_line}")

            message_parts.append(header + "\n" + "\n".join(item_details_parts))

        final_caption = "🔔 *订阅日历提醒*\n\n" + "\n\n".join(message_parts)
        
        result = None
        if poster_url:
            try:
                # --- 核心修改：在此处下载图片 ---
                import requests
                from proxy_manager import ProxyManager
                proxy_manager = ProxyManager(self.app_config)
                image_proxies = proxy_manager.get_proxies(poster_url)
                ui_logger.debug(f"   - [调试] 正在下载封面图片: {poster_url}", task_category=task_cat)
                response_img = requests.get(poster_url, timeout=30, proxies=image_proxies)
                response_img.raise_for_status()
                image_bytes = response_img.content
                # --- 下载结束 ---

                # --- 核心修改：将下载好的二进制数据传递给通知函数 ---
                result = notification_manager.send_telegram_photo_notification(
                    image_source=image_bytes,
                    caption=final_caption,
                    app_config=self.app_config
                )
            except Exception as e:
                ui_logger.error(f"❌ 下载封面图片或发送通知时失败: {e}。将降级为纯文本通知。", task_category=task_cat, exc_info=True)
                # 发生异常时，result 保持为 None，会触发下面的降级逻辑
        
        # 如果没有海报URL，或者图片下载/发送失败，则降级为纯文本
        if result is None:
            if poster_url: # 仅在下载失败时打印降级日志
                 ui_logger.warning("⚠️ 封面项目图片处理失败，已自动降级为纯文本通知。", task_category=task_cat)
            else: # 仅在项目本身无海报时打印
                 ui_logger.warning("⚠️ 封面项目缺少海报，将发送纯文本通知。", task_category=task_cat)
            result = notification_manager.send_telegram_message(final_caption, self.app_config)

        if result.get("success"):
            ui_logger.info("✅ 成功发送订阅通知！", task_category=task_cat)
        else:
            ui_logger.error(f"❌ 发送订阅通知失败，原因: {result.get('message', '未知错误')}", task_category=task_cat)


    def prune_expired_items(self):
        """定时清理任务的执行逻辑"""
        task_cat = "定时任务-订阅清理"
        ui_logger.info("➡️ 开始执行订阅列表过期项目清理任务...", task_category=task_cat)
        
        try:
            with FileLock(UPCOMING_DB_FILE + ".lock", timeout=30):
                db_content = self._read_db()
                if not db_content['data']:
                    ui_logger.info("✅ 数据库为空，无需清理。", task_category=task_cat)
                    return

                original_count = len(db_content['data'])
                today_str = datetime.now().strftime('%Y-%m-%d')
                
                # --- 核心修改：引入详细的分类和计数 ---
                items_to_keep = {}
                items_to_prune = []
                exempted_count = 0

                for tmdb_id, item in db_content['data'].items():
                    is_expired = item.get('release_date') and item['release_date'] < today_str
                    is_permanent = item.get('is_permanent', False)

                    if is_expired and not is_permanent:
                        items_to_prune.append(item)
                    else:
                        if is_expired and is_permanent:
                            exempted_count += 1
                            logging.debug(f"  - [豁免]《{item.get('title', tmdb_id)}》已过期但因永久收藏被保留。")
                        items_to_keep[tmdb_id] = item
                
                pruned_count = len(items_to_prune)
                
                if pruned_count > 0:
                    db_content['data'] = items_to_keep
                    with open(UPCOMING_DB_FILE, 'w', encoding='utf-8') as f:
                        json.dump(db_content, f, ensure_ascii=False, indent=4)
                    
                    summary_log = f"✅ 清理完成！共移除了 {pruned_count} 个已上映的过期项目。"
                    if exempted_count > 0:
                        summary_log += f" (另有 {exempted_count} 个项目因永久收藏被豁免)"
                    ui_logger.info(summary_log, task_category=task_cat)
                    
                    # 打印被删除的项目的详细日志
                    pruned_titles = "、".join([f"《{item.get('title', '未知')}》" for item in items_to_prune])
                    logging.info(f"  - [详情] 被移除的项目: {pruned_titles}")

                else:
                    summary_log = "✅ 检查完成，没有发现需要清理的过期项目。"
                    if exempted_count > 0:
                        summary_log += f" (有 {exempted_count} 个日期过期项目因永久收藏被保留)"
                    ui_logger.info(summary_log, task_category=task_cat)
                # --- 修改结束 ---

        except Timeout:
            ui_logger.error("❌ 清理任务失败：获取文件锁超时。", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"❌ 清理任务时发生未知错误: {e}", task_category=task_cat, exc_info=True)

    # backend/upcoming_logic.py (函数替换)

    def search_tmdb(self, media_type: str, query: str) -> List[Dict]:
        """根据关键词或ID在TMDB中搜索媒体"""
        task_cat = "即将上映-手动搜索"
        ui_logger.info(f"🔍 正在为 [{media_type}] 搜索 '{query}'...", task_category=task_cat)
        
        results = []
        # 优先尝试按 ID 搜索
        if query.isdigit():
            try:
                endpoint = f"{media_type}/{query}"
                params = {'language': 'zh-CN'}
                details = self.tmdb_logic._tmdb_request(endpoint, params)
                results.append(details)
                ui_logger.info(f"✅ 按 TMDB ID '{query}' 精确匹配成功。", task_category=task_cat)
            except Exception:
                ui_logger.warning(f"⚠️ 按 TMDB ID '{query}' 查找失败，将尝试作为标题进行模糊搜索。", task_category=task_cat)
                results = [] # 清空，以便进行后续搜索

        # 如果 ID 搜索无果或 query 不是数字，则按标题搜索
        if not results:
            try:
                endpoint = f"search/{media_type}"
                params = {'language': 'zh-CN', 'query': query}
                search_data = self.tmdb_logic._tmdb_request(endpoint, params)
                results = search_data.get('results', [])
                ui_logger.info(f"✅ 按标题 '{query}' 搜索到 {len(results)} 个结果。", task_category=task_cat)
            except Exception as e:
                ui_logger.error(f"❌ 按标题 '{query}' 搜索时发生错误: {e}", task_category=task_cat)
                return []
        
        # --- 核心修改：返回完整日期，而不是只返回年份 ---
        candidates = []
        for item in results:
            title = item.get('title') or item.get('name')
            release_date = item.get('release_date') or item.get('first_air_date')
            
            candidates.append({
                "tmdb_id": item.get('id'),
                "title": title,
                "release_date": release_date, # 直接传递完整日期
                "poster_path": item.get('poster_path'),
                "overview": item.get('overview')
            })
        return candidates

    def add_permanent_item(self, tmdb_id: int, media_type: str) -> Tuple[bool, str]:
        """获取单个TMDB项目的完整信息并将其作为永久收藏添加到数据库"""
        task_cat = "即将上映-手动添加"
        try:
            # 1. 获取完整信息
            ui_logger.info(f"➡️ 正在获取 TMDB ID: {tmdb_id} 的完整信息...", task_category=task_cat)
            endpoint = f"{media_type}/{tmdb_id}"
            params = {'language': 'zh-CN', 'append_to_response': 'images,credits'}
            details = self.tmdb_logic._tmdb_request(endpoint, params)

            # 2. 检查海报
            if not details.get('poster_path'):
                msg = f"媒体《{details.get('title') or details.get('name')}》因缺少海报图而无法添加。"
                ui_logger.warning(f"⚠️ {msg}", task_category=task_cat)
                return False, msg

            # 3. 构建数据对象
            raw_genres = [genre['name'] for genre in details.get('genres', [])]
            genres = ["科幻奇幻" if g == "Sci-Fi & Fantasy" else g for g in raw_genres]
            origin_country = details.get('origin_country', [])
            popularity = details.get('popularity', 0)
            cast = details.get('credits', {}).get('cast', [])
            actors = [actor['name'] for actor in cast[:5]]
            release_date = details.get('release_date') or details.get('first_air_date')

            item_data = {
                "tmdb_id": details['id'],
                "media_type": media_type,
                "title": details.get('title') or details.get('name'),
                "overview": details.get('overview'),
                "poster_path": details.get('poster_path'),
                "release_date": release_date,
                "is_subscribed": False,
                "subscribed_at": None,
                "genres": genres,
                "origin_country": origin_country,
                "popularity": popularity,
                "actors": actors,
                "is_permanent": True,
                "is_ignored": False 
            }

            # 4. 写入数据库
            with FileLock(UPCOMING_DB_FILE + ".lock", timeout=10):
                db_content = self._read_db()
                tmdb_id_str = str(tmdb_id)
                
                if tmdb_id_str in db_content['data']:
                    ui_logger.info(f"数据库中已存在《{item_data['title']}》，将直接将其设置为永久收藏。", task_category=task_cat)
                    db_content['data'][tmdb_id_str]['is_permanent'] = True
                else:
                    db_content['data'][tmdb_id_str] = item_data
                
                with open(UPCOMING_DB_FILE, 'w', encoding='utf-8') as f:
                    json.dump(db_content, f, ensure_ascii=False, indent=4)
            
            msg = f"🎉 成功将《{item_data['title']}》添加到永久收藏！"
            ui_logger.info(msg, task_category=task_cat)
            return True, msg

        except Timeout:
            msg = "操作失败：获取文件锁超时。"
            ui_logger.error(f"❌ {msg}", task_category=task_cat)
            return False, msg
        except Exception as e:
            msg = f"操作失败: {e}"
            ui_logger.error(f"❌ {msg}", task_category=task_cat, exc_info=True)
            return False, msg