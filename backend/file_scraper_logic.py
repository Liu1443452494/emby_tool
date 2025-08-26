# backend/file_scraper_logic.py (完整文件覆盖)

import os
import json
import time
import re
import shutil
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Callable
from filelock import FileLock, Timeout
import cloudscraper
from bs4 import BeautifulSoup
from PIL import Image
import io

from models import AppConfig, FileScraperConfig
from task_manager import TaskManager
from log_manager import ui_logger
from proxy_manager import ProxyManager

CACHE_FILE_PATH = os.path.join('/app/data', 'file_scraper_cache.json')
CACHE_EXPIRATION_DAYS = 7

class FileScraperLogic:
    def __init__(self, config: AppConfig):
        self.config = config
        self.scraper_config = config.file_scraper_config
        self.proxy_manager = ProxyManager(config)
        
        # --- 核心修改：移除 FlareSolverr 逻辑，统一创建一个 scraper 实例 ---
        self.scraper = cloudscraper.create_scraper()
        ui_logger.info(f"✅ 文件刮削器已初始化，当前使用内置 Cloudflare 解析器。", task_category="文件刮削器-初始化")

    def _make_request(self, url, **kwargs):
        # --- 核心修改：移除回退逻辑，直接使用唯一的 scraper 实例 ---
        return self.scraper.get(url, **kwargs)

    def _read_cache(self) -> Dict:
        """安全地读取缓存文件"""
        if not os.path.exists(CACHE_FILE_PATH):
            return {}
        try:
            with open(CACHE_FILE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            ui_logger.error(f"❌ 读取刮削器缓存文件失败: {e}", task_category="文件刮削器")
            return {}

    def _write_cache(self, cache_data: Dict):
        """安全地写入缓存文件，带文件锁"""
        task_cat = "文件刮削器-缓存"
        lock_path = CACHE_FILE_PATH + ".lock"
        try:
            with FileLock(lock_path, timeout=10):
                with open(CACHE_FILE_PATH, 'w', encoding='utf-8') as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=4)
        except Timeout:
            ui_logger.error("❌ 写入缓存文件失败：获取文件锁超时，另一进程可能正在操作。", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"❌ 写入缓存文件时发生未知错误: {e}", task_category=task_cat)


        # backend/file_scraper_logic.py (函数替换)
    def _check_metadata_exists(self, path: str, log_details: bool = False) -> bool:
        """
        检查指定路径的元数据是否存在，并根据 log_details 参数输出总结性诊断日志。
        """
        task_cat = "文件刮削器-扫描"
        
        def log(message):
            if log_details:
                ui_logger.info(message, task_category=task_cat)

        if os.path.isdir(path):
            poster_path = os.path.join(path, 'poster.jpg')
            nfo_path = os.path.join(path, 'movie.nfo')
            poster_exists = os.path.exists(poster_path)
            nfo_exists = os.path.exists(nfo_path)
            is_complete = poster_exists and nfo_exists
            
            if log_details:
                log(f"  - [检测] 路径 '{os.path.basename(path)}' (文件夹)")
                # --- 核心修改 ---
                log(f"    - 通用海报: 'poster.jpg' ({'存在' if poster_exists else '不存在'})")
                log(f"    - 通用NFO:   'movie.nfo' ({'存在' if nfo_exists else '不存在'})")
                # --- 修改结束 ---
                final_status_icon = "✅" if is_complete else ("⚠️" if (poster_exists or nfo_exists) else "❌")
                final_status_text = "完整" if is_complete else ("不完整" if final_status_icon == "⚠️" else "缺失")
                log(f"  - [结论] {final_status_icon} 元数据判定为 [{final_status_text}]。")
                
            return is_complete
        else: # 路径是文件
            # 1. 静默计算所有可能的元数据路径
            base, _ = os.path.splitext(path)
            parent_dir = os.path.dirname(path)
            
            poster_path_associated = f"{base}-poster.jpg"
            nfo_path_associated = f"{base}.nfo"
            
            poster_path_generic = os.path.join(parent_dir, 'poster.jpg')
            nfo_path_generic = os.path.join(parent_dir, 'movie.nfo')

            # 2. 静默检查这些路径是否存在
            poster_A_exists = os.path.exists(poster_path_associated)
            nfo_A_exists = os.path.exists(nfo_path_associated)
            
            poster_B_exists = os.path.exists(poster_path_generic)
            nfo_B_exists = os.path.exists(nfo_path_generic)
            
            is_independent = not self._is_bare_file(path)

            # 3. 根据优先级计算最终结果
            is_complete = False
            if poster_A_exists and nfo_A_exists:
                is_complete = True
            elif is_independent and poster_B_exists and nfo_B_exists:
                is_complete = True

            # 4. 如果需要，打印总结报告
            if log_details:
                log(f"  - [检测] 路径 '{os.path.basename(path)}' (文件)")
                # --- 核心修改 ---
                log(f"    - 关联海报: '{os.path.basename(poster_path_associated)}' ({'存在' if poster_A_exists else '不存在'})")
                log(f"    - 关联NFO:   '{os.path.basename(nfo_path_associated)}' ({'存在' if nfo_A_exists else '不存在'})")
                
                if is_independent:
                    log(f"    - (独立环境) 通用海报: 'poster.jpg' ({'存在' if poster_B_exists else '不存在'})")
                    log(f"    - (独立环境) 通用NFO:   'movie.nfo' ({'存在' if nfo_B_exists else '不存在'})")
                # --- 修改结束 ---
                
                found_any_file = poster_A_exists or nfo_A_exists or (is_independent and (poster_B_exists or nfo_B_exists))
                final_status_icon = "✅" if is_complete else ("⚠️" if found_any_file else "❌")
                final_status_text = "完整" if is_complete else ("不完整" if final_status_icon == "⚠️" else "缺失")
                
                log(f"  - [结论] {final_status_icon} 元数据判定为 [{final_status_text}]。")

            return is_complete

    def scan_directory_task(self, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager) -> List[Dict]:
        """
        扫描目录、清理缓存并返回文件列表的后台任务。
        """
        task_cat = "文件刮削器-扫描"
        scan_dir = self.scraper_config.scan_directory
        extensions = [ext.lower() for ext in self.scraper_config.file_extensions]
        ui_logger.info(f"➡️ 开始扫描任务，目标目录: {scan_dir}", task_category=task_cat)

        # 1. 读取并预处理缓存
        full_cache = self._read_cache()
        cleaned_cache = {}
        now = datetime.utcnow()
        expiration_delta = timedelta(days=CACHE_EXPIRATION_DAYS)

        ui_logger.info(f"🔍 正在进行全局缓存清理，将移除超过 {CACHE_EXPIRATION_DAYS} 天未访问的目录数据...", task_category=task_cat)
        for dir_path, dir_data in full_cache.items():
            last_accessed_str = dir_data.get("last_accessed")
            if last_accessed_str:
                try:
                    last_accessed_dt = datetime.fromisoformat(last_accessed_str.replace('Z', '+00:00'))
                    if now - last_accessed_dt.replace(tzinfo=None) <= expiration_delta:
                        cleaned_cache[dir_path] = dir_data
                    else:
                        ui_logger.info(f"  - 🗑️ 目录 '{dir_path}' 的缓存数据已过期 (上次访问于 {last_accessed_str})，已被清理。", task_category=task_cat)
                except ValueError:
                     ui_logger.warning(f"  - ⚠️ 无法解析目录 '{dir_path}' 的时间戳，将保留该数据。", task_category=task_cat)
            else:
                cleaned_cache[dir_path] = dir_data # 保留没有时间戳的旧数据

        # 2. 定位当前目录数据
        if scan_dir not in cleaned_cache:
            ui_logger.info(f"ℹ️ 为新目录 '{scan_dir}' 创建缓存记录。", task_category=task_cat)
            cleaned_cache[scan_dir] = {"last_accessed": now.isoformat() + 'Z', "files": {}}
        else:
            ui_logger.info(f"✅ 找到目录 '{scan_dir}' 的现有缓存，将更新其访问时间。", task_category=task_cat)
            cleaned_cache[scan_dir]["last_accessed"] = now.isoformat() + 'Z'
        
        current_dir_cache = cleaned_cache[scan_dir]["files"]

        # 3. 遍历本地文件系统
        ui_logger.info(f"🚀 开始深度遍历文件系统，请稍候...", task_category=task_cat)
        current_disk_files = set()
        try:
# --- 新增/修改 ---
            for root, dirs, files in os.walk(scan_dir):
                if cancellation_event.is_set():
                    ui_logger.warning("⚠️ 扫描任务被用户取消。", task_category=task_cat)
                    return []
                
                # 只处理文件，不再单独添加文件夹
                for file_name in files:
                    if os.path.splitext(file_name)[1].lower() in extensions:
                        file_path = os.path.join(root, file_name)
                        current_disk_files.add(file_path)
# --- 新增/修改结束 ---
        except Exception as e:
            ui_logger.error(f"❌ 遍历目录时发生错误: {e}", task_category=task_cat)
            return []

        ui_logger.info(f"✅ 文件系统遍历完成，共发现 {len(current_disk_files)} 个有效项目。", task_category=task_cat)

        # 4. 清理缓存中已不存在的文件条目
        cached_paths = set(current_dir_cache.keys())
        paths_to_remove = cached_paths - current_disk_files
        if paths_to_remove:
            ui_logger.info(f"🔄 正在清理缓存中 {len(paths_to_remove)} 个已失效的文件记录...", task_category=task_cat)
            for path in paths_to_remove:
                del current_dir_cache[path]

        # 5. 更新元数据状态并构建返回列表
        final_file_list = []
        total_files = len(current_disk_files)
        task_manager.update_task_progress(task_id, 0, total_files)
        
        ui_logger.info("🔍 正在检查每个项目的元数据状态...", task_category=task_cat)
        for i, path in enumerate(sorted(list(current_disk_files))):
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 扫描任务在元数据检查阶段被用户取消。", task_category=task_cat)
                return []

            # --- 新增/修改：解耦完整性判断和路径获取 ---
            # a. 判断完整性，用于UI显示 Tag
            has_metadata = self._check_metadata_exists(path, log_details=True)
            
            # b. 无论元数据是否完整，都尝试获取单个文件的路径
            nfo_path, _ = self.get_media_file(path, 'nfo')
            poster_path, _ = self.get_media_file(path, 'poster')
            # --- 新增/修改结束 ---
            
            if path not in current_dir_cache:
                current_dir_cache[path] = {}
            
            current_dir_cache[path]["has_metadata"] = has_metadata
            
            file_info = {
                "path": path,
                "type": 'dir' if os.path.isdir(path) else 'file',
                "urls": current_dir_cache[path].get("urls", {}),
                "has_metadata": has_metadata,
                "last_scraped": current_dir_cache[path].get("last_scraped_timestamp"),
                "nfo_path": nfo_path,
                "poster_path": poster_path
            }
            final_file_list.append(file_info)
            
            if (i + 1) % 100 == 0:
                task_manager.update_task_progress(task_id, i + 1, total_files)

        task_manager.update_task_progress(task_id, total_files, total_files)
        
        # 6. 写回缓存
        self._write_cache(cleaned_cache)
        ui_logger.info("🎉 扫描任务完成！缓存已更新。", task_category=task_cat)
        
        return final_file_list

    # --- 刮削逻辑 ---

    def _parse_xchina_html(self, html_content: str, task_cat: str) -> Optional[Dict]:
        """使用 BeautifulSoup 解析 xchina.co 的HTML页面，提取所需信息。"""
        try:
            soup = BeautifulSoup(html_content, 'lxml')
            data = {
                'title': None, 'actors': [], 'tags': [], 'plot': None,
                'poster_url': None, 'fanart_url': None
            }

            title_tag = soup.find('h1', class_='hero-title-item')
            if title_tag: data['title'] = title_tag.get_text(strip=True)

            actor_tag = soup.find('div', class_='model-item')
            if actor_tag:
                actor_name = actor_tag.find('div').get_text(strip=True) if actor_tag.find('div') else None
                actor_thumb_url = None
                style_attr = actor_tag.get('style', '')
                match = re.search(r"url\('(.+?)'\)", style_attr)
                if match: actor_thumb_url = match.group(1)
                if actor_name: data['actors'].append({'name': actor_name, 'thumb': actor_thumb_url})

            tags = []
            info_card = soup.find('div', class_='info-card video-detail')
            if info_card:
                camera_icon_item = info_card.find('i', class_='fa-video-camera')
                if camera_icon_item and (text_div := camera_icon_item.find_next('div', class_='text')):
                    for a_tag in text_div.find_all('a'): tags.append(a_tag.get_text(strip=True))
                
                file_icon_item = info_card.find('i', class_='fa-file')
                if file_icon_item and (text_div := file_icon_item.find_next('div', class_='text')):
                    tags.append(text_div.get_text(strip=True))
            data['tags'] = tags

            screenshot_container = soup.find('div', class_='screenshot-container')
            if screenshot_container and (img_tags := screenshot_container.find_all('img')):
                if len(img_tags) > 0:
                    data['poster_url'] = img_tags[0].get('src')
                    data['plot'] = img_tags[0].get('alt')
                if len(img_tags) > 1:
                    data['fanart_url'] = img_tags[1].get('src')

            ui_logger.info("  - ✅ [xchina.co] HTML内容解析成功。", task_category=task_cat)
            return data
        except Exception as e:
            ui_logger.error(f"  - ❌ [xchina.co] 解析HTML时发生内部错误: {e}", task_category=task_cat)
            return None
        
    def _parse_javday_html(self, html_content: str, task_cat: str) -> Optional[Dict]:
        """使用 BeautifulSoup 和正则表达式解析 javday.app 的HTML页面。"""
        try:
            soup = BeautifulSoup(html_content, 'lxml')
            data = {
                'title': None, 'actors': [], 'tags': [], 'plot': None,
                'poster_url': None, 'fanart_url': None
            }

            # 1. 提取标题
            title_tag = soup.find('h1', class_='video-title')
            if title_tag:
                data['title'] = title_tag.get_text(strip=True)

            # 2. 提取演员
            actor_tag = soup.find('span', class_='vod_actor')
            if actor_tag and actor_tag.find('a'):
                actor_name = actor_tag.find('a').get_text(strip=True)
                if actor_name:
                    data['actors'].append({'name': actor_name, 'thumb': None})

            # 3. 提取标签 (番号和厂商)
            tags = []
            jpnum_tag = soup.find('span', class_='jpnum')
            if jpnum_tag:
                tags.append(jpnum_tag.get_text(strip=True))
            
            producer_tag = soup.find('span', class_='producer')
            if producer_tag and producer_tag.find('a'):
                tags.append(producer_tag.find('a').get_text(strip=True))
            
            data['tags'] = tags

            # 4. 使用正则表达式提取海报URL
            match = re.search(r"pic:\s*'([^']*)'", html_content)
            if match:
                relative_path = match.group(1)
                if relative_path.startswith('/'):
                    data['poster_url'] = f"https://javday.app{relative_path}"
                else:
                    data['poster_url'] = f"https://javday.app/{relative_path}"
            
            ui_logger.info("  - ✅ [javday.app] HTML内容解析成功。", task_category=task_cat)
            return data
        except Exception as e:
            ui_logger.error(f"  - ❌ [javday.app] 解析HTML时发生内部错误: {e}", task_category=task_cat)
            return None

    def _parse_madou_club_html(self, html_content: str, task_cat: str) -> Optional[Dict]:
        """使用 BeautifulSoup 和正则表达式解析 madou.club 的HTML页面。"""
        try:
            soup = BeautifulSoup(html_content, 'lxml')
            data = {
                'title': None, 'actors': [], 'tags': [], 'plot': None,
                'poster_url': None, 'fanart_url': None
            }

            # 1. 提取标题
            title_tag = soup.find('h1', class_='article-title')
            if title_tag:
                data['title'] = title_tag.get_text(strip=True)

            # 2. 提取标签
            tags = set()
            # 从 meta keywords 中提取
            keywords_meta = soup.find('meta', attrs={'name': 'keywords'})
            if keywords_meta and keywords_meta.get('content'):
                keywords = [tag.strip() for tag in keywords_meta.get('content').split(',') if tag.strip()]
                tags.update(keywords)
            
            # 从 article-tags 中提取
            tags_div = soup.find('div', class_='article-tags')
            if tags_div:
                for a_tag in tags_div.find_all('a'):
                    tags.add(a_tag.get_text(strip=True))
            
            data['tags'] = list(tags)

            # 3. 使用正则表达式提取海报URL
            match = re.search(r"shareimage\s*:\s*'([^']*)'", html_content)
            if match:
                data['poster_url'] = match.group(1)
            
            ui_logger.info("  - ✅ [madou.club] HTML内容解析成功。", task_category=task_cat)
            return data
        except Exception as e:
            ui_logger.error(f"  - ❌ [madou.club] 解析HTML时发生内部错误: {e}", task_category=task_cat)
            return None
    # --- 新增结束 ---

    def _parse_madouqu_html(self, html_content: str, task_cat: str) -> Optional[Dict]:
        """使用 BeautifulSoup 解析 madouqu.com 的HTML页面。"""
        try:
            soup = BeautifulSoup(html_content, 'lxml')
            data = {
                'title': None, 'actors': [], 'tags': [], 'plot': None,
                'poster_url': None, 'fanart_url': None
            }

            # 1. 提取标题
            title_tag = soup.find('h1', class_='entry-title')
            if title_tag:
                data['title'] = title_tag.get_text(strip=True)

            # 2. 提取演员
            p_tags = soup.find_all('p')
            for p in p_tags:
                p_text = p.get_text(strip=True)
                if p_text.startswith('麻豆女郎：'):
                    actor_name = p_text.replace('麻豆女郎：', '').strip()
                    if actor_name:
                        data['actors'].append({'name': actor_name, 'thumb': None})
                    break
            
            # 3. 提取标签
            tags = set()
            # 从番号和片名中提取
            for p in p_tags:
                p_text = p.get_text(strip=True)
                if p_text.startswith('扣扣番號：'):
                    tags.add(p_text.replace('扣扣番號：', '').strip())
                elif p_text.startswith('扣扣片名：'):
                    tags.add(p_text.replace('扣扣片名：', '').strip())
            
            # 从面包屑导航中提取分类
            breadcrumbs = soup.find('div', class_='breadcrumbs')
            if breadcrumbs:
                links = breadcrumbs.find_all('a')
                # 跳过第一个("麻豆区")
                if len(links) > 1:
                    for link in links[1:]:
                        tags.add(link.get_text(strip=True))

            data['tags'] = list(tags)

            # 4. 提取海报URL
            poster_meta = soup.find('meta', property='og:image')
            if poster_meta and poster_meta.get('content'):
                data['poster_url'] = poster_meta.get('content')
            
            ui_logger.info("  - ✅ [madouqu.com] HTML内容解析成功。", task_category=task_cat)
            return data
        except Exception as e:
            ui_logger.error(f"  - ❌ [madouqu.com] 解析HTML时发生内部错误: {e}", task_category=task_cat)
            return None
    # --- 新增结束 ---

    def _get_scraper_for_domain(self, domain: str) -> Optional[Callable]:
        """根据域名返回对应的刮削解析函数"""
        if 'xchina.co' in domain:
            return self._parse_xchina_html
        elif 'javday.app' in domain:
            return self._parse_javday_html
        elif 'madou.club' in domain:
            return self._parse_madou_club_html
        # --- 新增 ---
        elif 'madouqu.com' in domain:
            return self._parse_madouqu_html
        # --- 新增结束 ---
        # ... 未来可在此处添加其他网站的 elif ...
        return None
    
    def _is_bare_file(self, file_path: str) -> bool:
        """
        判断一个视频文件是否为“裸文件”。
        如果在其父目录中找到除自身外的任何一个其他视频文件，就判定为裸文件。
        """
        task_cat = "文件刮削器-工具"
        video_extensions = [ext.lower() for ext in self.scraper_config.file_extensions]

        # --- 核心修改：增加对输入文件类型的检查 ---
        if os.path.splitext(file_path)[1].lower() not in video_extensions:
            # 如果输入路径本身不是视频文件，则不进行裸文件判断，直接返回False
            return False
        # --- 修改结束 ---

        try:
            parent_dir = os.path.dirname(file_path)
            my_filename = os.path.basename(file_path)

            for entry in os.scandir(parent_dir):
                if entry.is_file() and entry.name != my_filename:
                    if os.path.splitext(entry.name)[1].lower() in video_extensions:
                        ui_logger.info(f"  - ℹ️ [独立性检测] 检测到同级目录下存在另一个视频文件: {entry.name}。判定 '{my_filename}' 为裸文件。", task_category=task_cat)
                        return True
            
            ui_logger.info(f"  - ℹ️ [独立性检测] 未在同级目录下发现其他视频文件。判定 '{my_filename}' 为独立文件。", task_category=task_cat)
            return False
        except Exception as e:
            ui_logger.error(f"  - ❌ [独立性检测] 执行时发生错误: {e}。将默认其为独立文件以保证安全。", task_category=task_cat)
            return False

        # backend/file_scraper_logic.py (函数替换)
    def scrape_url_task(self, file_path: str, urls: Dict[str, str], cancellation_event: threading.Event) -> Dict:
        """
        单个文件的刮削、聚合和文件保存任务。
        """
        item_name = os.path.basename(file_path)
        task_cat = f"文件刮削器-{item_name}"
        ui_logger.info(f"➡️ 开始为 '{item_name}' 执行刮削任务...", task_category=task_cat)

        # --- 核心修改：移除刮削模式的日志输出 ---
        # --- 修改结束 ---

        # 1. 前置决策判断
        if not urls:
            ui_logger.warning(f"⚠️ 跳过 '{item_name}'，原因：未设置任何有效的刮削网址。", task_category=task_cat)
            return {"success": False, "message": "未设置URL"}

        if not self.scraper_config.overwrite_existing and self._check_metadata_exists(file_path):
            ui_logger.info(f"ℹ️ 跳过 '{item_name}'，原因：元数据已存在且未开启覆盖模式。", task_category=task_cat)
            return {"success": True, "message": "已跳过"}

        # 2. 多源聚合刮削
        scraped_data = {}
        priority_list = self.scraper_config.source_priority
        
        ui_logger.info(f"🔍 按优先级顺序开始刮削，顺序: {', '.join(priority_list)}", task_category=task_cat)
        for domain in priority_list:
            if cancellation_event.is_set(): return {"success": False, "message": "任务被取消"}
            url = urls.get(domain)
            if not url:
                continue

            parser = self._get_scraper_for_domain(domain)

            
                
            if not parser:
                ui_logger.warning(f"  - ⚠️ 域名 '{domain}' 没有匹配的解析器，已跳过。", task_category=task_cat)
                continue

            ui_logger.info(f"  - 🔄 正在使用 '{domain}' 刮削: {url}", task_category=task_cat)
            try:
                proxies = self.proxy_manager.get_proxies(url)
                # --- 核心修改：调用新的请求方法 ---
                response = self._make_request(url, timeout=20, proxies=proxies)
                # --- 修改结束 ---
                response.raise_for_status()
                
                partial_data = parser(response.text, task_cat)
                if partial_data:
                    # --- 核心修改：重构聚合逻辑，保留URL来源 ---
                    # 1. 聚合 tags (保持不变)
                    new_tags = partial_data.get('tags')
                    if new_tags:
                        if 'tags' not in scraped_data: scraped_data['tags'] = []
                        existing_tags = set(scraped_data['tags'])
                        tags_to_add = set(new_tags)
                        updated_tags = sorted(list(existing_tags.union(tags_to_add)))
                        if len(updated_tags) > len(existing_tags):
                            ui_logger.info(f"  - [聚合] 为 'tags' 字段新增了 {len(updated_tags) - len(existing_tags)} 个标签。", task_category=task_cat)
                        scraped_data['tags'] = updated_tags

                    # 2. 聚合图片URL，按来源存储
                    for img_key in ['poster_url', 'fanart_url']:
                        # 构造按来源存储的字典键
                        storage_key = f"{img_key}s_by_source" 
                        if storage_key not in scraped_data:
                            scraped_data[storage_key] = {}
                        
                        new_url = partial_data.get(img_key)
                        if new_url and domain not in scraped_data[storage_key]:
                            scraped_data[storage_key][domain] = new_url
                            ui_logger.info(f"  - [聚合] 从 '{domain}' 收集到 '{img_key}': {new_url}", task_category=task_cat)

                    # 3. 对所有其他字段，应用“先到先得”原则
                    for key, value in partial_data.items():
                        if key in ['tags', 'poster_url', 'fanart_url']:
                            continue
                        
                        if key not in scraped_data or not scraped_data[key]:
                            if isinstance(value, list) and not value: continue
                            if isinstance(value, str) and not value.strip(): continue
                            scraped_data[key] = value
                            ui_logger.info(f"  - [聚合] 填充了字段: '{key}'。", task_category=task_cat)
                    # --- 修改结束 ---
            except Exception as e:
                ui_logger.error(f"  - ❌ 访问或解析 '{url}' 失败: {e}", task_category=task_cat)
        
        if not scraped_data.get('title'):
            ui_logger.error(f"❌ 刮削失败！在所有源中都未能获取到最关键的'标题'信息。", task_category=task_cat)
            return {"success": False, "message": "未能获取到标题"}

        # 3. 文件保存与目录结构决策
        ui_logger.info("💾 开始处理文件保存与目录结构...", task_category=task_cat)
        original_path = file_path
        new_path = original_path
        save_dir = ""
        
        is_bare = self._is_bare_file(original_path)
        
        if os.path.isdir(original_path):
            save_dir = original_path
            ui_logger.info(f"  - 路径类型：文件夹。元数据将保存在: {save_dir}", task_category=task_cat)
        elif is_bare:
            ui_logger.info(f"  - 路径类型：裸文件。将为其创建独立文件夹。", task_category=task_cat)
            base_filename, _ = os.path.splitext(os.path.basename(original_path))
            scraped_title = scraped_data.get('title', '').strip()
            safe_title = re.sub(r'[\\/*?:"<>|]', '_', scraped_title) if scraped_title else ''
            
            if safe_title:
                new_folder_name = safe_title
                ui_logger.info(f"  - 命名策略：将使用刮削到的标题 '{safe_title}' 作为新文件夹名。", task_category=task_cat)
            else:
                new_folder_name = base_filename
                ui_logger.warning(f"  - 命名策略：⚠️ 未能获取到有效标题，将回退使用原文件名 '{base_filename}' 作为文件夹名。", task_category=task_cat)

            parent_dir = os.path.dirname(original_path)
            new_folder_path = os.path.join(parent_dir, new_folder_name)

            if os.path.exists(new_folder_path) and not os.path.isdir(new_folder_path):
                ui_logger.error(f"  - ❌ 无法创建文件夹 '{new_folder_path}'，因为已存在同名文件。", task_category=task_cat)
                return {"success": False, "message": "无法创建文件夹，存在同名文件"}
            
            os.makedirs(new_folder_path, exist_ok=True)
            new_path = os.path.join(new_folder_path, os.path.basename(original_path))
            
            try:
                if original_path != new_path:
                    shutil.move(original_path, new_path)
                    ui_logger.info(f"  - ✅ 视频文件已成功移动到: {new_path}", task_category=task_cat)
                else:
                    ui_logger.info(f"  - ℹ️ 视频文件已在目标位置，无需移动。", task_category=task_cat)
            except Exception as e:
                ui_logger.error(f"  - ❌ 移动视频文件失败: {e}", task_category=task_cat)
                return {"success": False, "message": f"移动文件失败: {e}"}

            if self.scraper_config.overwrite_existing:
                old_poster = f"{os.path.splitext(original_path)[0]}-poster.jpg"
                old_nfo = f"{os.path.splitext(original_path)[0]}.nfo"
                if os.path.exists(old_poster): os.remove(old_poster)
                if os.path.exists(old_nfo): os.remove(old_nfo)
                ui_logger.info("  - ℹ️ 已清理散落的旧元数据文件。", task_category=task_cat)

            save_dir = new_folder_path
        else: # 独立文件
            ui_logger.info(f"  - 路径类型：独立文件。元数据将保存在其父目录中。", task_category=task_cat)
            save_dir = os.path.dirname(original_path)

        # --- 核心修改：统一 base_name_for_meta ---
        base_name_for_meta = "movie"
        # --- 修改结束 ---

        # 4. 执行文件写入
        try:
            overwrite = self.scraper_config.overwrite_existing
            final_nfo_path = None
            final_poster_path = None

            nfo_path = os.path.join(save_dir, f"{base_name_for_meta}.nfo")
            nfo_exists = os.path.exists(nfo_path)
            
            if overwrite or not nfo_exists:
                # --- 核心修改：按优先级顺序写入所有图片URL ---
                nfo_parts = ["<?xml version='1.0' encoding='utf-8' standalone='yes'?>", "<movie>"]
                
                # (title, plot, actors, tags 的逻辑保持不变)
                title = scraped_data.get('title')
                if title: nfo_parts.append(f"  <title>{title}</title>")
                plot = scraped_data.get('plot')
                if plot: nfo_parts.append(f"  <plot>{plot}</plot>")
                actors = scraped_data.get('actors')
                if actors:
                    for actor in actors:
                        actor_name = actor.get('name')
                        if actor_name:
                            actor_xml = f"  <actor>\n    <name>{actor_name}</name>\n"
                            if actor.get('thumb'): actor_xml += f"    <thumb>{actor.get('thumb')}</thumb>\n"
                            actor_xml += "  </actor>"
                            nfo_parts.append(actor_xml)
                tags = scraped_data.get('tags')
                if tags:
                    for tag in tags:
                        if tag: nfo_parts.append(f"  <tag>{tag}</tag>")

                # 按源优先级顺序写入图片URL
                poster_urls_by_source = scraped_data.get('poster_urls_by_source', {})
                fanart_urls_by_source = scraped_data.get('fanart_urls_by_source', {})

                for domain in self.scraper_config.source_priority:
                    if domain in poster_urls_by_source:
                        nfo_parts.append(f'  <thumb aspect="poster">{poster_urls_by_source[domain]}</thumb>')
                    if domain in fanart_urls_by_source:
                        nfo_parts.append(f'  <thumb aspect="fanart">{fanart_urls_by_source[domain]}</thumb>')

                nfo_parts.append("</movie>")
                nfo_content = "\n".join(nfo_parts)
                # --- 修改结束 ---

                with open(nfo_path, 'w', encoding='utf-8') as f:
                    f.write(nfo_content)
                log_action = "覆盖" if nfo_exists else "保存"
                ui_logger.info(f"    - ✅ NFO 文件已{log_action}: {nfo_path}", task_category=task_cat)
            else:
                ui_logger.info(f"    - ℹ️ NFO 文件已存在且未开启覆盖，跳过写入。", task_category=task_cat)
            final_nfo_path = nfo_path

                
            main_page_url = next((urls[domain] for domain in priority_list if domain in urls), None)

            # --- 核心修改：按优先级和容错机制下载图片 ---
            image_map = {
                'poster': ('poster_urls_by_source', 'poster.jpg'),
                'fanart': ('fanart_urls_by_source', 'fanart.jpg')
            }

            for img_type, (source_key, file_name) in image_map.items():
                img_path = os.path.join(save_dir, file_name)
                img_exists = os.path.exists(img_path)

                if overwrite or not img_exists:
                    download_success = False
                    # 遍历优先级列表
                    for domain in self.scraper_config.source_priority:
                        urls_by_source = scraped_data.get(source_key, {})
                        img_url = urls_by_source.get(domain)
                        
                        if not img_url:
                            continue # 当前优先级的源没有提供此图片，跳到下一个

                        ui_logger.info(f"    - 🔄 尝试从源 '{domain}' 下载 {img_type} 图片...", task_category=task_cat)
                        try:
                            proxies = self.proxy_manager.get_proxies(img_url)
                            headers = {'Referer': main_page_url} if main_page_url else {}
                            # --- 核心修改：调用新的请求方法 ---
                            img_response = self._make_request(img_url, timeout=30, proxies=proxies, stream=True, headers=headers)
                            # --- 修改结束 ---
                            img_response.raise_for_status()
                            
                            image_data = io.BytesIO(img_response.content)
                            with Image.open(image_data) as img:
                                if img.mode in ['RGBA', 'P']:
                                    img = img.convert('RGB')
                                img.save(img_path, 'JPEG', quality=95)

                            log_action = "覆盖" if img_exists else "下载"
                            ui_logger.info(f"    - ✅ {img_type.capitalize()} 图片已成功{log_action}并转为JPG: {img_path}", task_category=task_cat)
                            if img_type == 'poster':
                                final_poster_path = img_path
                            
                            download_success = True
                            break # 下载成功，跳出循环
                        
                        except Exception as e:
                            ui_logger.warning(f"    - ⚠️ 从源 '{domain}' 下载失败: {e}。将尝试下一个源...", task_category=task_cat)
                    
                    if not download_success:
                         ui_logger.error(f"    - ❌ 尝试了所有源，仍未能成功下载 {img_type} 图片。", task_category=task_cat)
                else:
                    ui_logger.info(f"    - ℹ️ {img_type.capitalize()} 图片已存在且未开启覆盖，跳过下载。", task_category=task_cat)
                    if img_type == 'poster':
                        final_poster_path = img_path
                
        except Exception as e:
            ui_logger.error(f"  - ❌ 写入元数据文件时发生错误: {e}", task_category=task_cat)
            return {"success": False, "message": f"写入文件失败: {e}"}

        # 5. 更新缓存
        ui_logger.info("🔄 正在更新缓存状态...", task_category=task_cat)
        final_metadata_exists = self._check_metadata_exists(new_path)
        if not final_metadata_exists:
            ui_logger.warning(f"  - ⚠️ 刮削任务已执行，但最终检查发现元数据不完整 (可能部分图片下载失败)，'has_metadata' 状态将不会更新为 true。", task_category=task_cat)

        full_cache = self._read_cache()
        scan_dir = self.scraper_config.scan_directory
        if scan_dir in full_cache:
            target_path_in_cache = new_path if new_path in full_cache[scan_dir]["files"] else original_path
            
            if target_path_in_cache in full_cache[scan_dir]["files"]:
                if new_path == original_path:
                    if final_metadata_exists:
                        full_cache[scan_dir]["files"][original_path]["has_metadata"] = True
                    full_cache[scan_dir]["files"][original_path]["last_scraped_timestamp"] = datetime.utcnow().isoformat() + 'Z'
                else:
                    original_data = full_cache[scan_dir]["files"].pop(original_path, {})
                    if final_metadata_exists:
                        original_data["has_metadata"] = True
                    else:
                        original_data["has_metadata"] = False
                    original_data["last_scraped_timestamp"] = datetime.utcnow().isoformat() + 'Z'
                    full_cache[scan_dir]["files"][new_path] = original_data
                
                self._write_cache(full_cache)
                ui_logger.info("  - ✅ 缓存更新成功。", task_category=task_cat)
            else:
                ui_logger.warning(f"  - ⚠️ 未在缓存中找到对应条目 ('{original_path}' 或 '{new_path}')，跳过缓存更新。", task_category=task_cat)
        else:
            ui_logger.warning("  - ⚠️ 未在缓存中找到当前扫描目录，跳过缓存更新。", task_category=task_cat)

        return {
            "success": True, 
            "message": "刮削成功", 
            "data": scraped_data, 
            "new_path": new_path if new_path != original_path else None,
            "final_metadata_status": final_metadata_exists,
            "nfo_file_path": final_nfo_path,
            "poster_file_path": final_poster_path
        }
    
    def batch_scrape_task(self, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """
        批量刮削所有符合条件的文件。
        """
        task_cat = "文件刮削器-批量"
        ui_logger.info("➡️ 开始批量刮削任务...", task_category=task_cat)

        scan_dir = self.scraper_config.scan_directory
        full_cache = self._read_cache()

        if scan_dir not in full_cache:
            ui_logger.error("❌ 任务中止：在缓存中未找到当前扫描目录的数据，请先执行一次扫描。", task_category=task_cat)
            return

        files_to_process = []
        all_files_in_cache = full_cache[scan_dir].get("files", {})
        
        ui_logger.info("🔍 正在筛选需要处理的文件...", task_category=task_cat)
        for path, data in all_files_in_cache.items():
            # 条件1: 必须有URL
            if not data.get("urls"):
                continue
            # 条件2: 如果不覆盖，则元数据必须不存在
            if not self.scraper_config.overwrite_existing and data.get("has_metadata"):
                continue
            
            files_to_process.append({"path": path, "urls": data["urls"]})
        
        if not files_to_process:
            ui_logger.info("✅ 任务完成：没有需要处理的文件。", task_category=task_cat)
            return

        total_items = len(files_to_process)
        ui_logger.info(f"共找到 {total_items} 个文件待处理。", task_category=task_cat)
        task_manager.update_task_progress(task_id, 0, total_items)
        
        cooldown = self.scraper_config.batch_cooldown
        success_count = 0
        skipped_count = 0
        failed_count = 0

        for i, item in enumerate(files_to_process):
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 批量任务被用户取消。", task_category=task_cat)
                break
            
            ui_logger.info(f"--- ( {i+1} / {total_items} ) ---", task_category=task_cat)
            result = self.scrape_url_task(item["path"], item["urls"], cancellation_event)
            
            if result["success"]:
                if result["message"] == "已跳过":
                    skipped_count += 1
                else:
                    success_count += 1
            else:
                failed_count += 1

            task_manager.update_task_progress(task_id, i + 1, total_items)

            if i < total_items - 1:
                ui_logger.info(f"⏱️ 等待冷却时间: {cooldown} 秒...", task_category=task_cat)
                time.sleep(cooldown)

        ui_logger.info("🎉 批量刮削任务全部执行完毕！", task_category=task_cat)
        ui_logger.info(f"  - 成功: {success_count} 项", task_category=task_cat)
        ui_logger.info(f"  - 失败: {failed_count} 项", task_category=task_cat)
        ui_logger.info(f"  - 跳过: {skipped_count} 项", task_category=task_cat)
    
        # backend/file_scraper_logic.py (函数替换)
    def get_media_file(self, path: str, file_type: str) -> Tuple[Optional[str], Optional[str]]:
        """
        获取指定路径关联的媒体文件（图片或NFO），智能判断多种存放方式。
        返回 (文件路径, MIME类型) 或 (None, None)。
        """
        task_cat = "文件刮削器-文件服务"
        
        try:
            if not os.path.exists(path):
                ui_logger.warning(f"  - ⚠️ 请求的文件或目录路径不存在: {path}", task_category=task_cat)
                return None, None

            target_path = None
            
            if os.path.isdir(path):
                if file_type == 'poster': target_path = os.path.join(path, 'poster.jpg')
                elif file_type == 'nfo': target_path = os.path.join(path, 'movie.nfo')
            else: # 路径是文件
                # 检查点 A: 优先查找强关联元数据
                base, _ = os.path.splitext(path)
                if file_type == 'poster': temp_path = f"{base}-poster.jpg"
                elif file_type == 'nfo': temp_path = f"{base}.nfo"
                else: temp_path = None
                
                if temp_path and os.path.exists(temp_path):
                    target_path = temp_path
                
                # 检查点 B: 如果没找到，再在独立环境下查找通用元数据
                if not target_path and not self._is_bare_file(path):
                    parent_dir = os.path.dirname(path)
                    if file_type == 'poster': temp_path = os.path.join(parent_dir, 'poster.jpg')
                    elif file_type == 'nfo': temp_path = os.path.join(parent_dir, 'movie.nfo')
                    
                    if os.path.exists(temp_path):
                        target_path = temp_path

            if target_path:
                mime_type = 'image/jpeg' if file_type == 'poster' else 'text/plain'
                return target_path, mime_type
            else:
                return None, None
                
        except Exception as e:
            ui_logger.error(f"  - ❌ 在查找媒体文件时发生错误: {e}", task_category=task_cat)
            return None, None