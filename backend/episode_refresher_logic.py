import logging
import threading
import time
import requests
import base64
import re
import subprocess
import json
import os
import shutil
from typing import List, Iterable, Optional, Dict, Tuple
from collections import defaultdict
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from filelock import FileLock, Timeout
from datetime import datetime 

try:
    import cv2
    import numpy as np
    from PIL import Image
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False
    logging.warning("【剧集刷新】OpenCV 或 NumPy 未安装，高质量截图功能将不可用。请运行 'pip install opencv-python-headless numpy Pillow'")

from log_manager import ui_logger
from models import AppConfig, EpisodeRefresherConfig
from task_manager import TaskManager
from tmdb_logic import TmdbLogic

# --- 新增常量 ---
GITHUB_DELETE_LOG_FILE = os.path.join('/app/data', 'github_delete_log.json')
GITHUB_DB_CACHE_FILE = os.path.join('/app/data', 'github_database_cache.json')
GITHUB_DB_CACHE_DURATION = 3600  # 缓存1小时

class EpisodeRefresherLogic:
    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """清理文件名中的非法字符"""
        if not name:
            return "Unknown"
        return re.sub(r'[\\/*?:"<>|]', '_', name)
    
    def _find_screenshot_cache_dir_by_tmdbid(self, series_tmdb_id: str) -> Optional[str]:
        """通过 TMDB ID 查找实际存在的缓存目录路径，忽略标题。"""
        douban_data_root = self.app_config.douban_config.directory
        if not douban_data_root:
            return None
        
        base_cache_dir = os.path.join(douban_data_root, "EpisodeScreenshots")
        if not os.path.isdir(base_cache_dir):
            return None

        id_pattern = re.compile(r'\[(\d+)\]$')

        try:
            for dirname in os.listdir(base_cache_dir):
                dirpath = os.path.join(base_cache_dir, dirname)
                if os.path.isdir(dirpath):
                    match = id_pattern.search(dirname)
                    if match and match.group(1) == str(series_tmdb_id):
                        return dirpath
        except OSError as e:
            ui_logger.error(f"【截图缓存】扫描缓存目录时出错: {e}", task_category="截图缓存")
        
        return None
    
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.server_config = app_config.server_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.session = requests.Session()
        self.tmdb_logic = TmdbLogic(app_config)
        self.ffmpeg_available = shutil.which('ffmpeg') is not None and shutil.which('ffprobe') is not None

    @staticmethod
    def _is_generic_episode_title(text: str) -> bool:
        if not text: return True
        pattern = re.compile(r'^(第\s*\d+\s*集|Episode\s*\d+)$', re.IGNORECASE)
        return bool(pattern.match(text.strip()))
    
    def _get_emby_item_details(self, item_id: str, fields: str) -> Optional[Dict]:
        """获取媒体项的详细信息"""
        try:
            url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
            params = {**self.params, "Fields": fields}
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"【剧集刷新】获取媒体详情 (ID: {item_id}) 失败: {e}")
            return None

    def _unlock_item(self, item_id: str, task_category: str) -> bool:
        try:
            details_url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
            details_resp = self.session.get(details_url, params=self.params, timeout=15)
            details_resp.raise_for_status()
            item_details = details_resp.json()
            if item_details.get("LockedFields") and len(item_details["LockedFields"]) > 0:
                ui_logger.debug(f"     - [解锁] 检测到锁定的字段: {item_details['LockedFields']}，正在解锁...", task_category=task_category)
                item_details["LockedFields"] = []
                update_url = f"{self.base_url}/Items/{item_id}"
                headers = {'Content-Type': 'application/json'}
                update_resp = self.session.post(update_url, params=self.params, json=item_details, headers=headers, timeout=20)
                update_resp.raise_for_status()
                ui_logger.debug(f"     - [解锁] 媒体项 (ID: {item_id}) 已成功解锁。", task_category=task_category)
            else:
                ui_logger.debug(f"     - [解锁] 媒体项 (ID: {item_id}) 无需解锁。", task_category=task_category)
            return True
        except requests.RequestException as e:
            ui_logger.error(f"     - [解锁] 解锁媒体项 (ID: {item_id}) 时发生网络错误: {e}", task_category=task_category)
            return False
        except Exception as e:
            ui_logger.error(f"     - [解锁] 解锁媒体项 (ID: {item_id}) 时发生未知错误: {e}", task_category=task_category, exc_info=True)
            return False

    def _refresh_single_episode_by_emby(self, episode_id: str, config: EpisodeRefresherConfig, task_category: str) -> bool:
        try:
            if not self._unlock_item(episode_id, task_category):
                ui_logger.warning(f"     - 解锁媒体项 (ID: {episode_id}) 失败，刷新可能不会生效。", task_category=task_category)
            
            url = f"{self.base_url}/Items/{episode_id}/Refresh"
            params = {
                **self.params,
                "Recursive": "true",
                "MetadataRefreshMode": "FullRefresh",
                "ImageRefreshMode": "Default",
                "ReplaceAllMetadata": str(config.overwrite_metadata).lower(),
                "ReplaceAllImages": "false"
            }
            ui_logger.debug(f"     - [Emby模式] 发送刷新请求到: {url} (图片模式: Default)", task_category=task_category)
            
            response = self.session.post(url, params=params, timeout=30)
            response.raise_for_status()
            
            if response.status_code == 204:
                ui_logger.debug(f"     - [Emby模式] Emby 服务器已成功接收刷新请求 (ID: {episode_id})。", task_category=task_category)
                return True
            else:
                ui_logger.warning(f"     - [Emby模式] Emby 服务器返回异常状态码 {response.status_code} (ID: {episode_id})。", task_category=task_category)
                return False

        except requests.RequestException as e:
            ui_logger.error(f"     - [Emby模式] 刷新分集 (ID: {episode_id}) 时发生网络错误: {e}", task_category=task_category)
            return False

    def _upload_image_from_url(self, item_id: str, image_url: str, task_category: str) -> bool:
        try:
            ui_logger.debug(f"     - [执行] 正在从URL下载图片: {image_url}", task_category=task_category)
            proxies = self.tmdb_logic.proxy_manager.get_proxies(image_url)
            image_response = self.tmdb_logic.session.get(image_url, timeout=30, proxies=proxies)
            image_response.raise_for_status()
            image_data = image_response.content
            content_type = image_response.headers.get('Content-Type', 'image/jpeg')
            return self._upload_image_bytes(item_id, image_data, content_type, task_category)
        except Exception as e:
            ui_logger.error(f"     - [失败❌] 从URL下载并上传图片到 Emby (ID: {item_id}) 失败: {e}", task_category=task_category, exc_info=True)
            return False

    def _upload_image_bytes(self, item_id: str, image_data: bytes, content_type: str, task_category: str) -> bool:
        try:
            upload_url = f"{self.base_url}/Items/{item_id}/Images/Primary"
            
            try:
                self.session.delete(upload_url, params=self.params, timeout=20)
            except requests.RequestException as e:
                ui_logger.debug(f"     - [执行] 删除旧主图时发生错误（可能是正常的）: {e}", task_category=task_category)

            base64_encoded_data = base64.b64encode(image_data).decode('utf-8')
            
            headers = {'Content-Type': content_type}
            
            ui_logger.debug(f"     - [执行] 正在上传图片二进制数据到 Emby...", task_category=task_category)
            upload_response = self.session.post(
                upload_url, 
                params=self.params, 
                data=base64_encoded_data,
                headers=headers, 
                timeout=60
            )
            upload_response.raise_for_status()
            return True
        except Exception as e:
            ui_logger.error(f"     - [失败❌] 上传图片二进制数据到 Emby (ID: {item_id}) 失败: {e}", task_category=task_category, exc_info=True)
            return False

    def _get_video_url_from_item(self, episode_id: str, task_category: str) -> Optional[str]:
        try:
            details_url = f"{self.base_url}/Users/{self.user_id}/Items/{episode_id}"
            details_params = {**self.params, "Fields": "MediaSources"}
            details_resp = self.session.get(details_url, params=details_params, timeout=15)
            details_resp.raise_for_status()
            item_details = details_resp.json()

            media_sources = item_details.get("MediaSources")
            if not media_sources or not isinstance(media_sources, list) or len(media_sources) == 0:
                ui_logger.warning(f"     - [截图] 媒体项 (ID: {episode_id}) 的 MediaSources 字段为空或无效，无法获取流媒体地址。", task_category=task_category)
                return None

            first_source = media_sources[0]
            video_url = first_source.get("DirectStreamUrl") or first_source.get("Path")

            if not video_url:
                ui_logger.warning(f"     - [截图] 在 MediaSources 中既未找到 DirectStreamUrl 也未找到 Path 字段，无法截图。", task_category=task_category)
                return None
            
            if not video_url.startswith(('http://', 'https://')):
                ui_logger.error(f"     - [截图] 从 MediaSources 获取到的流媒体地址不是有效的URL: {video_url}", task_category=task_category)
                return None
            
            ui_logger.debug(f"     - [截图] 成功获取到流媒体 URL: {video_url}", task_category=task_category)
            return video_url
            
        except Exception as e:
            ui_logger.error(f"     - [截图] 获取媒体项流媒体 URL 时出错: {e}", task_category=task_category, exc_info=True)
            return None

    def _get_video_duration(self, video_url: str, task_category: str) -> Optional[float]:
        try:
            command = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-i', video_url
            ]
            ui_logger.debug(f"     - [截图] 正在执行 ffprobe 命令获取视频时长...", task_category=task_category)
            result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=60)
            format_info = json.loads(result.stdout).get('format', {})
            duration_str = format_info.get('duration')
            if duration_str:
                return float(duration_str)
            ui_logger.warning("     - [截图] ffprobe 未返回时长信息。", task_category=task_category)
            return None
        except subprocess.TimeoutExpired:
            ui_logger.error("     - [截图] ffprobe 获取时长超时。", task_category=task_category)
            return None
        except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError) as e:
            ui_logger.error(f"     - [截图] ffprobe 获取时长失败: {e}", task_category=task_category)
            return None
        
    def _get_local_screenshot_path(self, series_tmdb_id: str, season_number: int, episode_number: int, series_name: str) -> Optional[str]:
        """根据剧集信息生成本地截图缓存的完整路径 (用于写入和重命名)"""
        douban_data_root = self.app_config.douban_config.directory
        if not douban_data_root:
            ui_logger.warning("     - [本地缓存] 未配置豆瓣数据根目录，无法使用本地截图缓存功能。", task_category="截图缓存")
            return None
        
        sanitized_name = self._sanitize_filename(series_name)
        folder_name = f"{sanitized_name} [{series_tmdb_id}]"
        
        cache_dir = os.path.join(douban_data_root, "EpisodeScreenshots", folder_name)
        filename = f"season-{season_number}-episode-{episode_number}.jpg"
        return os.path.join(cache_dir, filename)

    def _save_screenshot_to_local(self, image_bytes: bytes, series_tmdb_id: str, season_number: int, episode_number: int, series_name: str, task_category: str) -> bool:
        """将截图二进制数据保存到本地缓存，并智能处理文件夹重命名。"""
        new_filepath = self._get_local_screenshot_path(series_tmdb_id, season_number, episode_number, series_name)
        if not new_filepath:
            return False
        
        new_dir = os.path.dirname(new_filepath)
        old_dir = self._find_screenshot_cache_dir_by_tmdbid(series_tmdb_id)
        final_dir = new_dir
        
        try:
            if old_dir:
                if old_dir != new_dir:
                    ui_logger.info(f"     - [本地缓存] 检测到剧集标题变更，正在重命名缓存文件夹: '{os.path.basename(old_dir)}' -> '{os.path.basename(new_dir)}'", task_category=task_category)
                    os.rename(old_dir, new_dir)
                final_dir = new_dir
            else:
                os.makedirs(new_dir, exist_ok=True)
            
            final_filepath = os.path.join(final_dir, os.path.basename(new_filepath))
            with open(final_filepath, 'wb') as f:
                f.write(image_bytes)
            ui_logger.debug(f"     - [本地缓存] 成功将截图保存到: {final_filepath}", task_category=task_category)
            return True
            
        except OSError as e:
            ui_logger.error(f"     - [本地缓存] 保存或重命名缓存时发生文件系统错误: {e}", task_category=task_category, exc_info=True)
            return False
        except Exception as e:
            ui_logger.error(f"     - [本地缓存] 保存截图到本地时发生未知错误: {e}", task_category=task_category, exc_info=True)
            return False

    def _read_screenshot_from_local(self, series_tmdb_id: str, season_number: int, episode_number: int, task_category: str) -> Optional[bytes]:
        """从本地缓存读取截图二进制数据 (通过TMDB ID查找)"""
        cache_dir = self._find_screenshot_cache_dir_by_tmdbid(series_tmdb_id)
        if not cache_dir:
            return None
        
        filename = f"season-{season_number}-episode-{episode_number}.jpg"
        filepath = os.path.join(cache_dir, filename)

        if not os.path.exists(filepath):
            return None
        
        try:
            with open(filepath, 'rb') as f:
                return f.read()
        except Exception as e:
            ui_logger.error(f"     - [本地缓存] 从本地读取截图失败: {e}", task_category=task_category, exc_info=True)
            return None

    def _delete_local_screenshot(self, series_tmdb_id: str, season_number: int, episode_number: int, task_category: str) -> bool:
        """从本地缓存中删除指定的截图文件 (通过TMDB ID查找)"""
        cache_dir = self._find_screenshot_cache_dir_by_tmdbid(series_tmdb_id)
        if not cache_dir:
            ui_logger.debug(f"     - [本地缓存] 无需删除，未找到TMDB ID为 {series_tmdb_id} 的缓存目录。", task_category=task_category)
            return True

        filename = f"season-{season_number}-episode-{episode_number}.jpg"
        filepath = os.path.join(cache_dir, filename)

        if not os.path.exists(filepath):
            ui_logger.debug(f"     - [本地缓存] 无需删除，文件不存在: {filepath}", task_category=task_category)
            return True
        
        try:
            os.remove(filepath)
            ui_logger.info(f"     - [本地缓存] TMDB已有官方图，成功删除作废的本地截图: {filepath}", task_category=task_category)
            return True
        except Exception as e:
            ui_logger.error(f"     - [本地缓存] 删除本地截图失败: {e}", task_category=task_category, exc_info=True)
            return False
    
    def _split_image_stream(self, stream: bytes) -> List[bytes]:
        """将 ffmpeg image2pipe 输出的二进制流分割成独立的图片列表"""
        images = []
        start_marker = b'\xff\xd8'
        end_marker = b'\xff\xd9'
        
        start = 0
        while True:
            start_pos = stream.find(start_marker, start)
            if start_pos == -1: break
            end_pos = stream.find(end_marker, start_pos)
            if end_pos == -1: break
            
            images.append(stream[start_pos:end_pos+2])
            start = end_pos + 2
        return images

    def _get_best_image_by_variance(self, images: List[bytes], task_category: str) -> Optional[bytes]:
        """通过拉普拉斯方差计算，从图片列表中选择最清晰的一张"""
        if not images:
            return None
        if not OPENCV_AVAILABLE:
            ui_logger.warning("     - [截图-智能模式] OpenCV 未加载，将随机选择一张图片。", task_category=task_category)
            return images[len(images) // 2]

        max_variance = -1
        best_image = None

        for img_bytes in images:
            try:
                pil_img = Image.open(BytesIO(img_bytes))
                cv_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2GRAY)
                variance = cv2.Laplacian(cv_img, cv2.CV_64F).var()
                if variance > max_variance:
                    max_variance = variance
                    best_image = img_bytes
            except Exception as e:
                ui_logger.debug(f"     - [截图-智能模式] 分析单张图片时出错: {e}", task_category=task_category)
                continue
        
        ui_logger.info(f"     - [截图-智能模式] 分析了 {len(images)} 帧，选择了清晰度得分最高的一张 (方差: {max_variance:.2f})。", task_category=task_category)
        return best_image

    def _capture_screenshot(self, video_url: str, seek_time: float, config: EpisodeRefresherConfig, task_category: str) -> Optional[bytes]:
        """使用 ffmpeg 从视频流截图，并根据配置处理黑边和比例"""
        try:
            crop_filter = ""
            try:
                detect_seek_time = max(0, seek_time - 3)
                detect_cmd = [
                    'ffmpeg', '-ss', str(detect_seek_time),
                    '-i', video_url, '-t', '2', '-vf', 'cropdetect',
                    '-f', 'null', '-'
                ]
                ui_logger.debug(f"     - [截图] 正在执行 cropdetect 命令检测黑边...", task_category=task_category)
                detect_result = subprocess.run(detect_cmd, capture_output=True, text=True, timeout=60)
                
                crop_match = re.search(r'crop=(\d+:\d+:\d+:\d+)', detect_result.stderr)
                if crop_match:
                    detected_crop_params = crop_match.group(1)
                    w, h, x, y = map(int, detected_crop_params.split(':'))
                    ui_logger.debug(f"     - [截图] 检测到有效画面区域: {detected_crop_params}", task_category=task_category)

                    crop_filter = f"crop={detected_crop_params}"
                    if config.crop_widescreen_to_16_9 and w / h > 1.8:
                        target_w = round(h * 16 / 9)
                        if target_w < w:
                            offset_x = round((w - target_w) / 2)
                            crop_filter += f",crop={target_w}:{h}:{offset_x}:0"
                            ui_logger.info(f"     - [截图] 将应用宽屏裁剪，最终滤镜: {crop_filter}", task_category=task_category)
                else:
                    ui_logger.warning("     - [截图] 未能检测到黑边信息，将不进行裁剪。", task_category=task_category)
            except Exception as e:
                ui_logger.warning(f"     - [截图] 黑边检测失败，将不进行裁剪。原因: {e}", task_category=task_category)

            if config.use_smart_screenshot:
                ui_logger.info("     - [截图] 启动智能截图模式，将获取1秒内多帧进行筛选...", task_category=task_category)
                capture_cmd = [
                    'ffmpeg', '-ss', str(seek_time),
                    '-i', video_url, '-t', '1',
                    '-q:v', '2', '-f', 'image2pipe', '-'
                ]
                if crop_filter:
                    capture_cmd.insert(7, '-vf')
                    capture_cmd.insert(8, crop_filter)
                
                capture_result = subprocess.run(capture_cmd, capture_output=True, check=True, timeout=60)
                all_frames = self._split_image_stream(capture_result.stdout)
                return self._get_best_image_by_variance(all_frames, task_category)
            else:
                ui_logger.info("     - [截图] 启动快速截图模式，将截取单帧图片...", task_category=task_category)
                capture_cmd = [
                    'ffmpeg', '-ss', str(seek_time),
                    '-i', video_url, '-vframes', '1',
                    '-q:v', '2', '-f', 'image2pipe', '-'
                ]
                if crop_filter:
                    capture_cmd.insert(5, '-vf')
                    capture_cmd.insert(6, crop_filter)
                
                capture_result = subprocess.run(capture_cmd, capture_output=True, check=True, timeout=60)
                return capture_result.stdout

        except Exception as e:
            ui_logger.error(f"     - [失败❌] 截图过程中发生未知错误: {e}", task_category=task_category, exc_info=True)
            return None


    def _get_remote_db(self, config: EpisodeRefresherConfig, force_refresh: bool = False) -> Tuple[Optional[Dict], Optional[str]]:
        task_cat = "远程图床"
        github_conf = config.github_config
        if not github_conf.repo_url:
            return None, None

        # --- 核心修改：定义锁文件目录和路径 ---
        lock_dir = os.path.join(os.path.dirname(GITHUB_DB_CACHE_FILE), "locks")
        os.makedirs(lock_dir, exist_ok=True)
        lock_path = os.path.join(lock_dir, os.path.basename(GITHUB_DB_CACHE_FILE) + ".lock")
        # --- 结束修改 ---

        try:
            # --- 核心修改：使用新的 lock_path ---
            with FileLock(lock_path, timeout=5):
            # --- 结束修改 ---
                if not force_refresh and os.path.exists(GITHUB_DB_CACHE_FILE):
                    mtime = os.path.getmtime(GITHUB_DB_CACHE_FILE)
                    if time.time() - mtime < GITHUB_DB_CACHE_DURATION:
                        with open(GITHUB_DB_CACHE_FILE, 'r', encoding='utf-8') as f:
                            ui_logger.debug("     - [远程图床] 命中本地的数据库文件缓存。", task_category=task_cat)
                            return json.load(f), None # 从缓存加载时，sha为None
        except (Timeout, IOError, json.JSONDecodeError) as e:
            ui_logger.warning(f"     - [远程图床] 读取本地数据库缓存文件失败: {e}，将强制从远程获取。", task_category=task_cat)

        try:
            match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", github_conf.repo_url)
            if not match:
                raise ValueError("无效的 GitHub 仓库 URL 格式。")
            owner, repo = match.groups()
            
            if github_conf.download_cooldown > 0:
                ui_logger.debug(f"     - [远程图床] ⏱️ 下载冷却 {github_conf.download_cooldown} 秒...", task_category=task_cat)
                time.sleep(github_conf.download_cooldown)

            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{github_conf.branch}/database.json"
            ui_logger.debug(f"     - [远程图床] 正在从 Raw URL 下载数据库: {raw_url}", task_category=task_cat)
            proxies = self.tmdb_logic.proxy_manager.get_proxies(raw_url)
            response = self.session.get(raw_url, timeout=30, proxies=proxies)
            
            if response.status_code == 200:
                db_content = response.json()
                # --- 核心修改：使用新的 lock_path ---
                with FileLock(lock_path, timeout=5):
                # --- 结束修改 ---
                    with open(GITHUB_DB_CACHE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(db_content, f, ensure_ascii=False)
                return db_content, None 
            
            ui_logger.warning(f"     - [远程图床] 从 Raw URL 下载失败 (状态码: {response.status_code})，将尝试使用 API 获取...", task_category=task_cat)
            
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/database.json?ref={github_conf.branch}"
            headers = {"Accept": "application/vnd.github.v3+json"}
            if github_conf.personal_access_token:
                headers["Authorization"] = f"token {github_conf.personal_access_token}"
            
            proxies = self.tmdb_logic.proxy_manager.get_proxies(api_url)
            api_response = self.session.get(api_url, headers=headers, timeout=30, proxies=proxies)
            api_response.raise_for_status()
            
            api_data = api_response.json()
            content = base64.b64decode(api_data['content']).decode('utf-8')
            db_content = json.loads(content)
            sha = api_data.get('sha')

            # --- 核心修改：使用新的 lock_path ---
            with FileLock(lock_path, timeout=5):
            # --- 结束修改 ---
                with open(GITHUB_DB_CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(db_content, f, ensure_ascii=False)
            
            return db_content, sha

        except Exception as e:
            ui_logger.error(f"     - [失败❌] 获取远程图床数据库失败: {e}", task_category=task_cat)
            return None, None

        # --- 核心重构：_handle_screenshot_flow ---
    def _handle_screenshot_flow(self, series_tmdb_id: str, episode_id: str, episode_details: Dict, config: EpisodeRefresherConfig, task_category: str) -> Tuple[bool, str]:
        log_prefix = f"     - S{episode_details.get('ParentIndexNumber', 0):02d}E{episode_details.get('IndexNumber', 0):02d}:"
        
        if not self.ffmpeg_available:
            ui_logger.warning(f"{log_prefix} [跳过] ffmpeg 或 ffprobe 未安装，无法执行截图功能。", task_category=task_category)
            return False, "none"

        if config.force_overwrite_screenshots:
            ui_logger.info(f"{log_prefix} [警告⚠️] 用户开启强制覆盖模式！将跳过所有缓存，直接进行实时截图...", task_category=task_category)
            return self._trigger_realtime_screenshot(series_tmdb_id, episode_id, episode_details, config, task_category, log_prefix)

        # 检查远程图床缓存
        if config.screenshot_cache_mode == 'remote':
            ui_logger.debug(f"{log_prefix} [决策] 检查缓存 (模式: 远程图床优先)...", task_category=task_category)
            remote_db, _ = self._get_remote_db(config)
            if remote_db:
                s_key = str(episode_details.get("ParentIndexNumber"))
                e_key = str(episode_details.get("IndexNumber"))
                series_data = remote_db.get("series", {}).get(str(series_tmdb_id), {})
                image_url = series_data.get(f"{s_key}-{e_key}")
                
                if image_url:
                    ui_logger.info(f"{log_prefix} [命中✅] 发现远程图床缓存，准备更新。", task_category=task_category)
                    if self._upload_image_from_url(episode_id, image_url, task_category):
                        return True, "remote"
                    else:
                        ui_logger.warning(f"{log_prefix} [警告⚠️] 远程图床图片下载或上传失败，将继续降级检查。", task_category=task_category)
                else:
                    ui_logger.debug(f"{log_prefix} [跳过] 远程图床无缓存。", task_category=task_category)
            else:
                ui_logger.warning(f"{log_prefix} [警告⚠️] 获取远程图床数据库失败，无法检查远程缓存。", task_category=task_category)

        # 降级检查本地文件缓存
        if config.screenshot_cache_mode in ['remote', 'local']:
            ui_logger.debug(f"{log_prefix} [决策] 降级或优先检查本地文件缓存...", task_category=task_category)
            cached_image_bytes = self._read_screenshot_from_local(series_tmdb_id, episode_details.get("ParentIndexNumber"), episode_details.get("IndexNumber"), task_category)
            if cached_image_bytes:
                ui_logger.info(f"{log_prefix} [命中✅] 发现本地文件缓存，准备更新。", task_category=task_category)
                if self._upload_image_bytes(episode_id, cached_image_bytes, 'image/jpeg', task_category):
                    return True, "local"
                else:
                     ui_logger.warning(f"{log_prefix} [警告⚠️] 本地缓存图片上传失败，将继续降级检查。", task_category=task_category)
            else:
                ui_logger.debug(f"{log_prefix} [跳过] 本地无缓存。", task_category=task_category)

        # 降级到实时截图
        return self._trigger_realtime_screenshot(series_tmdb_id, episode_id, episode_details, config, task_category, log_prefix)

        # --- 新增：实时截图的独立触发函数 ---
    def _trigger_realtime_screenshot(self, series_tmdb_id: str, episode_id: str, episode_details: Dict, config: EpisodeRefresherConfig, task_category: str, log_prefix: str) -> Tuple[bool, str]:
        if config.screenshot_cache_mode == 'remote' and not config.github_config.allow_fallback:
            ui_logger.info(f"{log_prefix} [跳过] 所有缓存均未命中，且用户禁止降级为实时截图，截图流程中止。", task_category=task_category)
            return False, "none"

        ui_logger.info(f"{log_prefix} [决策] 所有缓存均未命中或被跳过，准备实时截图...", task_category=task_category)
        
        duration = None
        if (runtime_ticks := episode_details.get("RunTimeTicks")) and runtime_ticks > 0:
            duration = runtime_ticks / 10_000_000
            ui_logger.debug(f"     - [截图] 视频时长: {duration:.2f}s (来自Emby元数据)。", task_category=task_category)
        
        video_url = self._get_video_url_from_item(episode_id, task_category)
        if not video_url:
            ui_logger.error(f"{log_prefix} [失败❌] 未能获取到视频流 URL，无法截图。", task_category=task_category)
            return False, "none"
            
        if duration is None:
            duration = self._get_video_duration(video_url, task_category)

        seek_time = duration * (config.screenshot_percentage / 100) if duration else config.screenshot_fallback_seconds
        if duration:
            ui_logger.debug(f"     - [截图] 截图位置: {seek_time:.2f}s (基于 {config.screenshot_percentage}%)。", task_category=task_category)
        else:
            ui_logger.warning(f"     - [截图] 获取视频时长失败，将使用保底秒数进行截图: {seek_time}s。", task_category=task_category)

        image_bytes = self._capture_screenshot(video_url, seek_time, config, task_category)
        
        if image_bytes:
            if self._upload_image_bytes(episode_id, image_bytes, 'image/jpeg', task_category):
                ui_logger.info(f"{log_prefix} [成功🎉] 截图生成并上传成功！", task_category=task_category)
                
                # 回写缓存
                if config.screenshot_cache_mode == 'local':
                    self._save_screenshot_to_local(image_bytes, series_tmdb_id, episode_details.get("ParentIndexNumber"), episode_details.get("IndexNumber"), episode_details.get("SeriesName"), task_category)
                    ui_logger.info(f"{log_prefix} [回写] 新截图已保存至本地缓存。", task_category=task_category)
                elif config.screenshot_cache_mode == 'remote' and config.github_config.personal_access_token:
                    self._save_screenshot_to_local(image_bytes, series_tmdb_id, episode_details.get("ParentIndexNumber"), episode_details.get("IndexNumber"), episode_details.get("SeriesName"), task_category)
                    ui_logger.info(f"{log_prefix} [回写] 新截图已暂存至本地 (等待手动备份)。", task_category=task_category)

                self._set_image_source_tag(episode_id, "screenshot", task_category)
                return True, "screenshot"
        
        ui_logger.error(f"{log_prefix} [失败❌] 实时截图失败。", task_category=task_category)
        return False, "none"

    def _set_image_source_tag(self, item_id: str, source: str, task_category: str):
        try:
            item_details = self.tmdb_logic._get_emby_item_details(item_id, fields="ProviderIds")
            if not item_details: return

            item_details.setdefault("ProviderIds", {})['ToolboxImageSource'] = source
            
            update_url = f"{self.base_url}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            self.session.post(update_url, params=self.params, json=item_details, headers=headers, timeout=20).raise_for_status()
            ui_logger.debug(f"     - [标记] 成功将图片来源标记 '{source}' 写入 Emby (ID: {item_id})。", task_category=task_category)
        except Exception as e:
            ui_logger.error(f"     - [失败❌] 写入图片来源标记失败 (ID: {item_id}): {e}", task_category=task_category)

    def _clear_image_source_tag(self, item_id: str, task_category: str):
        try:
            item_details = self.tmdb_logic._get_emby_item_details(item_id, fields="ProviderIds")
            if not item_details: return

            provider_ids = item_details.get("ProviderIds", {})
            if 'ToolboxImageSource' in provider_ids:
                del provider_ids['ToolboxImageSource']
                update_url = f"{self.base_url}/Items/{item_id}"
                headers = {'Content-Type': 'application/json'}
                self.session.post(update_url, params=self.params, json=item_details, headers=headers, timeout=20).raise_for_status()
                ui_logger.debug(f"     - [标记] 成功从 Emby (ID: {item_id}) 移除图片来源标记。", task_category=task_category)
        except Exception as e:
            ui_logger.error(f"     - [失败❌] 移除图片来源标记失败 (ID: {item_id}): {e}", task_category=task_category)

        # 在 backend/episode_refresher_logic.py 文件中

    def _refresh_season_by_toolbox(self, series_tmdb_id: str, season_number: int, emby_episodes: List[Dict], config: EpisodeRefresherConfig, task_category: str) -> int:
        updated_count = 0
        try:
            series_name_for_log = emby_episodes[0].get("SeriesName", f"剧集 {series_tmdb_id}")
            ui_logger.info(f"  -> [工具箱模式] 正在为《{series_name_for_log}》S{season_number:02d} 获取整季TMDB数据...", task_category=task_category)
            tmdb_season_details = self.tmdb_logic.get_season_details(int(series_tmdb_id), season_number)

            if not tmdb_season_details or not tmdb_season_details.get("episodes"):
                ui_logger.warning(f"     - 未能从TMDB获取到 S{season_number:02d} 的有效分集列表。", task_category=task_category)
                return 0
            
            tmdb_episodes_map = {ep.get("episode_number"): ep for ep in tmdb_season_details["episodes"]}

            for emby_episode in emby_episodes:
                episode_num = emby_episode.get("IndexNumber")
                if episode_num is None:
                    continue
                
                log_prefix = f"     - S{season_number:02d}E{episode_num:02d}:"
                ui_logger.info(f"➡️ 开始处理《{series_name_for_log}》S{season_number:02d}E{episode_num:02d}: {emby_episode.get('Name')}", task_category=task_category)

                tmdb_episode = tmdb_episodes_map.get(episode_num)
                
                potential_changes = {}
                image_update_action = None
                
                # --- 日志增强：收集比较信息 ---
                comparison_log = {}

                emby_name = emby_episode.get("Name", "")
                tmdb_name = tmdb_episode.get("name") if tmdb_episode else None
                is_emby_title_generic = self._is_generic_episode_title(emby_name)
                is_tmdb_title_valid = tmdb_name and not self._is_generic_episode_title(tmdb_name)
                
                if is_tmdb_title_valid and tmdb_name != emby_name:
                    potential_changes["Name"] = tmdb_name
                    comparison_log['标题'] = f"Emby({emby_name}) → TMDB({tmdb_name})"
                else:
                    comparison_log['标题'] = f"Emby({emby_name or '无'}) | TMDB({tmdb_name or '无'})"

                emby_overview = emby_episode.get("Overview", "")
                tmdb_overview = tmdb_episode.get("overview") if tmdb_episode else None
                if tmdb_overview and tmdb_overview != emby_overview:
                    potential_changes["Overview"] = tmdb_overview
                    comparison_log['简介'] = "Emby(有) → TMDB(新)" if emby_overview else "Emby(无) → TMDB(有)"
                else:
                    comparison_log['简介'] = f"Emby({'有' if emby_overview else '无'}) | TMDB({'有' if tmdb_overview else '无'})"

                emby_premiere_date = emby_episode.get("PremiereDate", "")
                tmdb_air_date = tmdb_episode.get("air_date") if tmdb_episode else None
                if tmdb_air_date:
                    if not emby_premiere_date or tmdb_air_date != emby_premiere_date[:10]:
                        potential_changes["PremiereDate"] = tmdb_air_date + "T00:00:00.000Z"
                        comparison_log['首播日期'] = f"Emby({emby_premiere_date[:10] if emby_premiere_date else '无'}) → TMDB({tmdb_air_date})"
                    else:
                        comparison_log['首播日期'] = f"Emby/TMDB一致({tmdb_air_date})"
                else:
                    comparison_log['首播日期'] = f"Emby({emby_premiere_date[:10] if emby_premiere_date else '无'}) | TMDB(无)"

                current_image_source = emby_episode.get("ProviderIds", {}).get("ToolboxImageSource")
                emby_has_image = bool(emby_episode.get("ImageTags", {}).get("Primary"))
                tmdb_still_path = tmdb_episode.get("still_path") if tmdb_episode else None

                ui_logger.debug(f"{log_prefix} [决策] 检查外部数据源...")
                if tmdb_still_path:
                    if not emby_has_image or current_image_source == "screenshot":
                        image_update_action = "tmdb"
                        comparison_log['图片'] = "Emby(无/截图) → TMDB(有)"
                    else:
                        ui_logger.info(f"{log_prefix} [保护🛡️] Emby 已有用户自定义图片，跳过图片更新。")
                        comparison_log['图片'] = "Emby(用户图) | TMDB(有)"
                elif config.screenshot_enabled:
                    if not emby_has_image:
                        image_update_action = "screenshot"
                        comparison_log['图片'] = "Emby(无) | TMDB(无) → 截图"
                    elif current_image_source == "screenshot" and config.force_overwrite_screenshots:
                        image_update_action = "screenshot"
                        comparison_log['图片'] = "Emby(截图) | TMDB(无) → 强制截图"
                    else:
                        ui_logger.info(f"{log_prefix} [跳过] Emby 中已有工具截图且未开启强制覆盖，无需截图。")
                        comparison_log['图片'] = "Emby(截图) | TMDB(无)"
                else:
                    comparison_log['图片'] = f"Emby({'有' if emby_has_image else '无'}) | TMDB(无)"
                
                if not potential_changes and not image_update_action:
                    skip_reason = ", ".join([f"{k}({v})" for k, v in comparison_log.items()])
                    ui_logger.info(f"{log_prefix} [跳过] 无需更新。详情: [{skip_reason}]", task_category=task_category)
                    continue

                final_changes_log = []
                
                if potential_changes:
                    if self._unlock_item(emby_episode["Id"], task_category):
                        update_payload = emby_episode.copy()
                        update_payload.update(potential_changes)
                        update_url = f"{self.base_url}/Items/{emby_episode['Id']}"
                        headers = {'Content-Type': 'application/json'}
                        try:
                            self.session.post(update_url, params=self.params, json=update_payload, headers=headers, timeout=20).raise_for_status()
                            field_map = {"Name": "标题", "Overview": "简介", "PremiereDate": "首播日期"}
                            for key in potential_changes.keys():
                                final_changes_log.append(field_map.get(key, key))
                        except Exception as e:
                            ui_logger.error(f"{log_prefix} [失败❌] 应用元数据更新时失败: {e}", task_category=task_category)
                    else:
                        ui_logger.error(f"{log_prefix} [失败❌] 解锁失败，跳过元数据更新。", task_category=task_category)

                if image_update_action == "tmdb":
                    ui_logger.info(f"{log_prefix} [命中✅] 发现 TMDB 官方图，准备更新。", task_category=task_category)
                    image_url = f"https://image.tmdb.org/t/p/original{tmdb_still_path}"
                    if self._upload_image_from_url(emby_episode["Id"], image_url, task_category):
                        final_changes_log.append("图片(TMDB)")
                        if current_image_source == "screenshot":
                            self._clear_image_source_tag(emby_episode["Id"], task_category)
                            ui_logger.info(f"{log_prefix} [记录] 正在将作废截图信息写入待删除日志...", task_category=task_category)
                            self._log_screenshot_for_deletion(
                                series_tmdb_id=series_tmdb_id,
                                series_name=emby_episode.get("SeriesName", "未知剧集"),
                                emby_series_id=emby_episode.get("SeriesId"),
                                season_number=season_number,
                                episode_number=episode_num
                            )
                            if config.screenshot_cache_mode != 'none':
                                self._delete_local_screenshot(series_tmdb_id, season_number, episode_num, task_category)
                
                elif image_update_action == "screenshot":
                    success, source = self._handle_screenshot_flow(series_tmdb_id, emby_episode["Id"], emby_episode, config, task_category)
                    if success:
                        source_map = {"remote": "远程图床", "local": "本地缓存", "screenshot": "实时截图"}
                        final_changes_log.append(f"图片({source_map.get(source, '未知')})")
                        if config.screenshot_cooldown > 0:
                            ui_logger.debug(f"     - [截图] 操作冷却，等待 {config.screenshot_cooldown} 秒...", task_category=task_category)
                            time.sleep(config.screenshot_cooldown)

                if final_changes_log:
                    ui_logger.info(f"{log_prefix} [成功🎉] 本次更新内容: [{', '.join(final_changes_log)}]", task_category=task_category)
                    updated_count += 1
                else:
                    ui_logger.warning(f"{log_prefix} [警告⚠️] 检测到需要更新，但所有更新操作均失败。", task_category=task_category)

        except Exception as e:
            ui_logger.error(f"     - [失败❌] 处理 S{season_number:02d} 时发生严重错误: {e}", task_category=task_category, exc_info=True)
        
        return updated_count

    def run_refresh_for_episodes(self, episode_ids: Iterable[str], config: EpisodeRefresherConfig, cancellation_event: threading.Event, task_id: Optional[str] = None, task_manager: Optional[TaskManager] = None, task_category: str = "剧集刷新"):
        
        episode_ids_list = list(episode_ids)
        total_episodes = len(episode_ids_list)
        
        ui_logger.info(f"任务启动，共需处理 {total_episodes} 个剧集分集。", task_category=task_category)
        ui_logger.info(f"  - 刷新模式: {'工具箱代理刷新' if config.refresh_mode == 'toolbox' else '通知Emby刷新'}", task_category=task_category)
        if config.refresh_mode == 'emby':
            ui_logger.info(f"  - 元数据写入方式: {'覆盖所有元数据' if config.overwrite_metadata else '仅补充缺失'}", task_category=task_category)
        else:
            ui_logger.info(f"  - 截图功能: {'开启' if config.screenshot_enabled else '关闭'}", task_category=task_category)
            if config.screenshot_enabled:
                mode_map = {'none': '无缓存', 'local': '本地文件缓存', 'remote': '远程图床优先'}
                ui_logger.info(f"  - 截图缓存模式: {mode_map.get(config.screenshot_cache_mode, '未知')}", task_category=task_category)
                ui_logger.info(f"  - 智能截图: {'开启' if config.use_smart_screenshot else '关闭'}", task_category=task_category)
        ui_logger.info(f"  - 智能跳过: {'开启' if config.skip_if_complete else '关闭'}", task_category=task_category)
        
        if task_manager and task_id:
            task_manager.update_task_progress(task_id, 0, total_episodes)

        if total_episodes == 0:
            ui_logger.info("没有需要处理的剧集分集，任务结束。", task_category=task_category)
            return {"refreshed_count": 0}

        ui_logger.info("步骤 1/2: 正在获取并筛选需要处理的分集...", task_category=task_category)
        
        all_episode_details = []
        for index, episode_id in enumerate(episode_ids_list):
            if cancellation_event.is_set(): break
            if task_manager and task_id:
                task_manager.update_task_progress(task_id, index + 1, total_episodes)
            try:
                fields_to_get = "SeriesId,SeriesName,Name,Overview,ImageTags,IndexNumber,ParentIndexNumber,PremiereDate,ProviderIds,LockedFields,RunTimeTicks"
                details = self._get_emby_item_details(episode_id, fields_to_get)
                if details:
                    all_episode_details.append(details)
            except requests.RequestException as e:
                logging.error(f"【剧集刷新】获取分集详情 (ID: {episode_id}) 失败: {e}，跳过此分集。")
        
        if cancellation_event.is_set():
            ui_logger.warning("任务在预处理阶段被取消。", task_category=task_category)
            return

        episodes_to_process = []
        if config.skip_if_complete:
            for ep in all_episode_details:
                is_title_ok = bool(ep.get("Name")) and not self._is_generic_episode_title(ep.get("Name"))
                is_overview_ok = bool(ep.get("Overview"))
                
                has_primary_image = bool(ep.get("ImageTags", {}).get("Primary"))
                image_source = ep.get("ProviderIds", {}).get("ToolboxImageSource")
                is_image_ok = has_primary_image and image_source != "screenshot"
                
                if not (is_title_ok and is_overview_ok and is_image_ok):
                    episodes_to_process.append(ep)
            ui_logger.info(f"智能跳过已开启，共筛选出 {len(episodes_to_process)} / {len(all_episode_details)} 个需要处理的分集。", task_category=task_category)
        else:
            episodes_to_process = all_episode_details

        refreshed_count = 0
        
        if config.refresh_mode == 'toolbox':
            grouped_seasons = defaultdict(lambda: defaultdict(list))
            for ep in episodes_to_process:
                if ep.get("SeriesId") and ep.get("ParentIndexNumber") is not None:
                    grouped_seasons[ep["SeriesId"]][ep["ParentIndexNumber"]].append(ep)

            ui_logger.info(f"步骤 2/2: [工具箱模式] 开始按季获取TMDB数据并更新...", task_category=task_category)
            series_tmdb_id_cache = {}
            processed_ep_count = 0
            total_ep_to_process = len(episodes_to_process)
            for series_id, seasons in grouped_seasons.items():
                if cancellation_event.is_set(): break
                
                series_tmdb_id = series_tmdb_id_cache.get(series_id)
                if not series_tmdb_id:
                    series_details = self.tmdb_logic._get_emby_item_details(series_id, fields="ProviderIds")
                    series_tmdb_id = next((v for k, v in series_details.get("ProviderIds", {}).items() if k.lower() == 'tmdb'), None)
                    if series_tmdb_id:
                        series_tmdb_id_cache[series_id] = series_tmdb_id
                    else:
                        ui_logger.warning(f"剧集(ID: {series_id})缺少TMDB ID，跳过该剧集的所有分集。", task_category=task_category)
                        processed_ep_count += sum(len(eps) for eps in seasons.values())
                        if task_manager and task_id:
                            task_manager.update_task_progress(task_id, processed_ep_count, total_ep_to_process)
                        continue
                
                for season_number, emby_episodes in seasons.items():
                    if cancellation_event.is_set(): break
                    refreshed_count += self._refresh_season_by_toolbox(series_tmdb_id, season_number, emby_episodes, config, task_category)
                    processed_ep_count += len(emby_episodes)
                    if task_manager and task_id:
                        task_manager.update_task_progress(task_id, processed_ep_count, total_ep_to_process)
        else:
            ui_logger.info(f"步骤 2/2: [Emby模式] 开始逐个通知Emby刷新...", task_category=task_category)
            for index, episode in enumerate(episodes_to_process):
                if cancellation_event.is_set(): break
                if task_manager and task_id:
                    task_manager.update_task_progress(task_id, index + 1, len(episodes_to_process))
                
                series_name = episode.get("SeriesName", "未知剧集")
                episode_number = episode.get("IndexNumber")
                episode_title = episode.get("Name", f"分集 {episode_number}" if episode_number else f"ID {episode['Id']}")
                log_message = f"{series_name} - "
                if episode_number:
                    log_message += f"第{episode_number}集 - "
                log_message += episode_title
                ui_logger.info(f"进度 {index + 1}/{len(episodes_to_process)}: 正在刷新: {log_message}", task_category=task_category)

                if self._refresh_single_episode_by_emby(episode['Id'], config, task_category):
                    refreshed_count += 1
                time.sleep(0.5)

        ui_logger.info(f"任务执行完毕。共成功处理 {refreshed_count} 个分集。", task_category=task_category)
        if config.refresh_mode == 'emby':
            ui_logger.warning("请注意：Emby 的刷新是在后台进行的，实际元数据更新可能会有延迟。请稍后在 Emby 中查看结果。", task_category=task_category)
        return {"refreshed_count": refreshed_count}
    
    def backup_screenshots_from_emby_task(self, series_ids: Iterable[str], config: EpisodeRefresherConfig, cancellation_event: threading.Event, task_id: Optional[str] = None, task_manager: Optional[TaskManager] = None):
        """
        从 Emby 备份已存在的、由工具箱生成的截图到本地缓存目录。
        """
        task_cat = "截图备份"
        ui_logger.info(f"【{task_cat}】任务启动，开始从 {len(series_ids)} 个剧集中查找并备份已有截图...", task_category=task_cat)
        ui_logger.info(f"  - 备份配置：覆盖本地文件={'开启' if config.backup_overwrite_local else '关闭'}", task_category=task_cat)

        all_episode_ids = []
        if task_manager and task_id:
            task_manager.update_task_progress(task_id, 0, len(series_ids))
        
        for i, series_id in enumerate(series_ids):
            if cancellation_event.is_set():
                ui_logger.warning(f"【{task_cat}】任务在获取分集列表阶段被取消。", task_category=task_cat)
                return
            try:
                episodes_url = f"{self.base_url}/Items"
                episodes_params = {**self.params, "ParentId": series_id, "IncludeItemTypes": "Episode", "Recursive": "true", "Fields": "Id"}
                episodes_resp = self.session.get(episodes_url, params=episodes_params, timeout=30)
                episodes_resp.raise_for_status()
                episodes = episodes_resp.json().get("Items", [])
                all_episode_ids.extend([ep['Id'] for ep in episodes])
            except Exception as e:
                ui_logger.error(f"【{task_cat}】获取剧集 {series_id} 的分集时失败: {e}", task_category=task_cat)
            if task_manager and task_id:
                task_manager.update_task_progress(task_id, i + 1, len(series_ids))
        
        ui_logger.info(f"【{task_cat}】分集列表获取完毕，共找到 {len(all_episode_ids)} 个分集需要检查。", task_category=task_cat)

        backed_up_count = 0
        skipped_count = 0
        failed_count = 0
        total_episodes = len(all_episode_ids)
        if task_manager and task_id:
            task_manager.update_task_progress(task_id, 0, total_episodes)

        series_tmdb_id_cache = {}

        for i, episode_id in enumerate(all_episode_ids):
            if cancellation_event.is_set():
                ui_logger.warning(f"【{task_cat}】任务在处理分集时被取消。", task_category=task_cat)
                break
            
            try:
                ep_details = self._get_emby_item_details(episode_id, fields="ProviderIds,SeriesId,ParentIndexNumber,IndexNumber,Name,SeriesName")
                if not ep_details:
                    ui_logger.warning(f"  -> 无法获取分集 {episode_id} 的详情，跳过。", task_category=task_cat)
                    failed_count += 1
                    continue

                log_prefix = f"  -> 正在处理《{ep_details.get('SeriesName', '未知剧集')}》S{ep_details.get('ParentIndexNumber', 0):02d}E{ep_details.get('IndexNumber', 0):02d}:"

                provider_ids = ep_details.get("ProviderIds", {})
                if provider_ids.get("ToolboxImageSource") != "screenshot":
                    ui_logger.debug(f"{log_prefix} 非工具箱截图，跳过。", task_category=task_cat)
                    skipped_count += 1
                    continue

                series_id = ep_details.get("SeriesId")
                series_tmdb_id = series_tmdb_id_cache.get(series_id)
                if not series_tmdb_id:
                    series_details = self._get_emby_item_details(series_id, fields="ProviderIds")
                    series_tmdb_id = next((v for k, v in series_details.get("ProviderIds", {}).items() if k.lower() == 'tmdb'), None)
                    if not series_tmdb_id:
                        ui_logger.warning(f"{log_prefix} 所属剧集(ID: {series_id})缺少TMDB ID，无法构建缓存路径，跳过。", task_category=task_cat)
                        failed_count += 1
                        continue
                    series_tmdb_id_cache[series_id] = series_tmdb_id
                
                local_path = self._get_local_screenshot_path(
                    series_tmdb_id, 
                    ep_details.get("ParentIndexNumber"), 
                    ep_details.get("IndexNumber"),
                    ep_details.get("SeriesName")
                )
                if not local_path:
                    failed_count += 1
                    continue
                
                if os.path.exists(local_path) and not config.backup_overwrite_local:
                    ui_logger.info(f"{log_prefix} 本地缓存已存在且未开启覆盖，跳过。", task_category=task_cat)
                    skipped_count += 1
                    continue

                image_url = f"{self.base_url}/Items/{episode_id}/Images/Primary?api_key={self.api_key}"
                image_resp = self.session.get(image_url, timeout=30)
                image_resp.raise_for_status()
                image_bytes = image_resp.content

                if self._save_screenshot_to_local(image_bytes, series_tmdb_id, ep_details.get("ParentIndexNumber"), ep_details.get("IndexNumber"), ep_details.get("SeriesName"), task_cat):
                    ui_logger.info(f"{log_prefix} 成功备份到本地。", task_category=task_cat)
                    backed_up_count += 1
                else:
                    ui_logger.error(f"{log_prefix} 备份失败。", task_category=task_cat)
                    failed_count += 1

            except Exception as e:
                ui_logger.error(f"  -> 处理分集 {episode_id} 时发生未知错误: {e}", task_category=task_cat, exc_info=True)
                failed_count += 1
            finally:
                if task_manager and task_id:
                    task_manager.update_task_progress(task_id, i + 1, total_episodes)

        ui_logger.info(f"【{task_cat}】任务执行完毕。成功备份: {backed_up_count} 张, 跳过: {skipped_count} 张, 失败: {failed_count} 张。", task_category=task_cat)
        return {"backed_up_count": backed_up_count, "skipped_count": skipped_count, "failed_count": failed_count}


    def backup_screenshots_to_github_task(self, config: EpisodeRefresherConfig, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "备份到GitHub"
        github_conf = config.github_config
        
        ui_logger.info(f"【{task_cat}】任务启动...", task_category=task_cat)
        
        if not github_conf.repo_url or not github_conf.personal_access_token:
            ui_logger.error(f"【{task_cat}】[失败❌] 未配置完整的 GitHub 仓库 URL 和个人访问令牌 (PAT)，任务中止。", task_category=task_cat)
            raise ValueError("GitHub 仓库 URL 和 PAT 不能为空。")

        douban_data_root = self.app_config.douban_config.directory
        if not douban_data_root:
            ui_logger.error(f"【{task_cat}】[失败❌] 未配置豆瓣数据根目录，无法找到本地截图文件夹，任务中止。", task_category=task_cat)
            raise ValueError("豆瓣数据根目录未配置。")

        local_screenshots_dir = os.path.join(douban_data_root, "EpisodeScreenshots")
        if not os.path.isdir(local_screenshots_dir):
            ui_logger.warning(f"【{task_cat}】[跳过] 本地截图目录 '{local_screenshots_dir}' 不存在，没有可备份的文件。", task_category=task_cat)
            return {"uploaded_count": 0, "skipped_count": 0, "failed_count": 0}

        # 步骤 1: 获取远程状态
        ui_logger.info(f"【{task_cat}】[步骤 1/5] 正在从 GitHub 获取最新的远程数据库...", task_category=task_cat)
        remote_db, remote_sha = self._get_remote_db(config, force_refresh=True)
        if remote_db is None:
            ui_logger.info(f"【{task_cat}】远程仓库似乎没有 'database.json' 文件，将创建一个新的。", task_category=task_cat)
            remote_db = {"version": 2, "last_updated": "", "series": {}}
            remote_sha = None # 新建文件没有 sha

        # 步骤 2: 扫描本地文件
        ui_logger.info(f"【{task_cat}】[步骤 2/5] 正在扫描本地截图文件夹...", task_category=task_cat)
        upload_queue = []
        id_pattern = re.compile(r'\[(\d+)\]$')
        file_pattern = re.compile(r'season-(\d+)-episode-(\d+)\.jpg')

        for series_dir_name in os.listdir(local_screenshots_dir):
            series_dir_path = os.path.join(local_screenshots_dir, series_dir_name)
            if not os.path.isdir(series_dir_path): continue
            
            match_id = id_pattern.search(series_dir_name)
            if not match_id: continue
            tmdb_id = match_id.group(1)

            for filename in os.listdir(series_dir_path):
                match_file = file_pattern.match(filename)
                if not match_file: continue
                
                s_num, e_num = match_file.groups()
                episode_key = f"{s_num}-{e_num}"
                
                remote_series_data = remote_db.get("series", {}).get(tmdb_id, {})
                
                if episode_key not in remote_series_data or github_conf.overwrite_remote:
                    upload_queue.append({
                        "local_path": os.path.join(series_dir_path, filename),
                        "github_path": f"EpisodeScreenshots/{tmdb_id}/{filename}",
                        "tmdb_id": tmdb_id,
                        "episode_key": episode_key
                    })
        
        total_to_upload = len(upload_queue)
        ui_logger.info(f"【{task_cat}】[步骤 2/5] 本地扫描完成，共发现 {total_to_upload} 个需要上传或更新的截图。", task_category=task_cat)
        if total_to_upload == 0:
            ui_logger.info(f"【{task_cat}】本地与远程没有差异，任务完成。", task_category=task_cat)
            return {"uploaded_count": 0, "skipped_count": 0, "failed_count": 0}

        # 步骤 3: 串行上传
        ui_logger.info(f"【{task_cat}】[步骤 3/5] 开始串行上传截图，请稍候...", task_category=task_cat)
        task_manager.update_task_progress(task_id, 0, total_to_upload)
        
        successful_uploads = []
        failed_uploads = []
        
        for i, item in enumerate(upload_queue):
            if cancellation_event.is_set():
                ui_logger.warning(f"【{task_cat}】任务在上传阶段被用户取消。", task_category=task_cat)
                break
            
            ui_logger.info(f"➡️ 正在上传第 {i + 1}/{total_to_upload} 个文件: {os.path.basename(item['local_path'])}", task_category=task_cat)
            try:
                download_url = self._upload_file_to_github(item, github_conf)
                if download_url:
                    item["download_url"] = download_url
                    successful_uploads.append(item)
                    ui_logger.info(f"✅ 上传成功: {os.path.basename(item['local_path'])}", task_category=task_cat)
                else:
                    failed_uploads.append(item)
                    ui_logger.error(f"❌ 上传失败: {os.path.basename(item['local_path'])}", task_category=task_cat)
            except Exception as e:
                ui_logger.error(f"❌ 上传文件 '{item['local_path']}' 时发生严重错误: {e}", task_category=task_cat)
                failed_uploads.append(item)
            
            task_manager.update_task_progress(task_id, i + 1, total_to_upload)

        ui_logger.info(f"【{task_cat}】[步骤 3/5] 截图上传完成。成功: {len(successful_uploads)}, 失败: {len(failed_uploads)}。", task_category=task_cat)
        if failed_uploads:
            ui_logger.error(f"【{task_cat}】⚠️ 由于存在上传失败的截图，任务中止，索引文件将不会更新。", task_category=task_cat)
            return {"uploaded_count": len(successful_uploads), "skipped_count": 0, "failed_count": len(failed_uploads)}

        # 步骤 4: 合并索引
        ui_logger.info(f"【{task_cat}】[步骤 4/5] 正在合并索引文件...", task_category=task_cat)
        final_db = remote_db
        for item in successful_uploads:
            tmdb_id = item["tmdb_id"]
            episode_key = item["episode_key"]
            if tmdb_id not in final_db["series"]:
                final_db["series"][tmdb_id] = {}
            final_db["series"][tmdb_id][episode_key] = item["download_url"]
        
        final_db["last_updated"] = datetime.utcnow().isoformat() + "Z"

        # 步骤 5: 提交索引
        ui_logger.info(f"【{task_cat}】[步骤 5/5] 正在将更新后的索引提交到 GitHub...", task_category=task_cat)
        if self._upload_db_to_github(final_db, remote_sha, github_conf):
            ui_logger.info(f"【{task_cat}】[成功🎉] 索引文件成功更新！备份任务全部完成。", task_category=task_cat)
        else:
            ui_logger.error(f"【{task_cat}】[失败❌] 索引文件提交失败！图片已上传但未记录，请重新运行备份任务以修复索引。", task_category=task_cat)
            return {"uploaded_count": len(successful_uploads), "skipped_count": 0, "failed_count": len(failed_uploads) + 1}

        return {"uploaded_count": len(successful_uploads), "skipped_count": 0, "failed_count": 0}


    def _upload_file_to_github(self, item: Dict, github_conf) -> Optional[str]:
        task_cat = "备份到GitHub"
        try:
            if github_conf.upload_cooldown > 0:
                ui_logger.debug(f"     - [GitHub上传] ⏱️ 上传冷却 {github_conf.upload_cooldown} 秒...", task_category=task_cat)
                time.sleep(github_conf.upload_cooldown)

            with open(item["local_path"], "rb") as f:
                content_bytes = f.read()
            
            content_b64 = base64.b64encode(content_bytes).decode('utf-8')
            
            match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", github_conf.repo_url)
            owner, repo = match.groups()
            
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{item['github_path']}"
            
            sha = None
            # --- 核心修改：无论是否覆盖，都尝试获取 SHA，因为更新操作总是需要它 ---
            try:
                ui_logger.debug(f"     - [GitHub上传] 正在查询文件 '{item['github_path']}' 的当前 SHA...", task_category=task_cat)
                get_headers = {
                    "Accept": "application/vnd.github.v3+json",
                    "Authorization": f"token {github_conf.personal_access_token}"
                }
                proxies = self.tmdb_logic.proxy_manager.get_proxies(api_url)
                get_resp = self.session.get(api_url, headers=get_headers, timeout=20, proxies=proxies)
                if get_resp.status_code == 200:
                    sha = get_resp.json().get('sha')
                    ui_logger.debug(f"     - [GitHub上传] 文件已存在，获取到 SHA: {sha}", task_category=task_cat)
                else:
                    ui_logger.debug(f"     - [GitHub上传] 文件不存在或查询失败 (状态码: {get_resp.status_code})，将作为新文件创建。", task_category=task_cat)
            except Exception as e:
                # 获取SHA失败是正常的（比如文件第一次上传），记录一个debug日志即可
                ui_logger.debug(f"     - [GitHub上传] 查询 SHA 时发生异常 (可能是新文件): {e}", task_category=task_cat)

            payload_dict = {
                "message": f"feat: Add screenshot for {item['github_path']}",
                "content": content_b64,
                "branch": github_conf.branch
            }
            # --- 核心修改：只要获取到了 SHA，就必须附带它 ---
            if sha:
                payload_dict["sha"] = sha

            payload_json_str = json.dumps(payload_dict)

            command = [
                'curl',
                '-L',
                '-X', 'PUT',
                '-H', 'Accept: application/vnd.github.v3+json',
                '-H', f'Authorization: token {github_conf.personal_access_token}',
                '-H', 'Content-Type: application/json',
                '--data-binary', '@-',
                api_url
            ]
            
            proxies = self.tmdb_logic.proxy_manager.get_proxies(api_url)
            if proxies.get('https'):
                command.extend(['--proxy', proxies['https']])

            result = subprocess.run(command, input=payload_json_str, capture_output=True, text=True, check=False)
            
            response_data = {}
            try:
                response_data = json.loads(result.stdout)
            except json.JSONDecodeError:
                if "409 Conflict" in result.stderr:
                     raise Exception(f"GitHub API 返回 409 Conflict 错误，这通常是并发写入冲突导致的。请稍后重试。")
                raise Exception(f"cURL 返回了非JSON响应: {result.stdout} | 错误: {result.stderr}")

            if result.returncode != 0 or 'content' not in response_data or 'download_url' not in response_data.get('content', {}):
                 if "message" in response_data and "documentation_url" in response_data:
                     # --- 核心修改：对 422 错误进行更友好的日志提示 ---
                     error_message = response_data['message']
                     if response_data.get('status') == '422' and "sha" in error_message:
                         error_message = f"无效请求。服务器提示 'sha' 参数有问题。这可能是因为在您操作期间，文件被其他进程修改。请重试。({error_message})"
                     raise Exception(f"GitHub API 错误: {error_message} (状态码: {response_data.get('status', '未知')})")
                 raise Exception(f"cURL 上传失败。返回码: {result.returncode}, 输出: {result.stdout}, 错误: {result.stderr}")

            return response_data["content"]["download_url"]

        except Exception as e:
            ui_logger.error(f"【{task_cat}】上传文件 '{item['local_path']}' 时发生错误: {e}", task_category=task_cat)
            return None



    def _upload_db_to_github(self, db_content: Dict, sha: Optional[str], github_conf) -> bool:
        task_cat = "备份到GitHub"
        try:
            if github_conf.upload_cooldown > 0:
                ui_logger.debug(f"     - [GitHub上传] ⏱️ 上传冷却 {github_conf.upload_cooldown} 秒...", task_category=task_cat)
                time.sleep(github_conf.upload_cooldown)

            content_b64 = base64.b64encode(json.dumps(db_content, indent=2, ensure_ascii=False).encode('utf-8')).decode('utf-8')
            
            match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", github_conf.repo_url)
            owner, repo = match.groups()
            
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/database.json"
            
            # --- 核心修改：在上传前，重新获取一次最新的 SHA ---
            latest_sha = None
            try:
                ui_logger.debug(f"     - [GitHub上传] 正在为 'database.json' 查询最新的 SHA...", task_category=task_cat)
                get_headers = {
                    "Accept": "application/vnd.github.v3+json",
                    "Authorization": f"token {github_conf.personal_access_token}"
                }
                proxies = self.tmdb_logic.proxy_manager.get_proxies(api_url)
                get_resp = self.session.get(api_url, headers=get_headers, timeout=20, proxies=proxies)
                if get_resp.status_code == 200:
                    latest_sha = get_resp.json().get('sha')
                    ui_logger.debug(f"     - [GitHub上传] 成功获取到 'database.json' 的最新 SHA: {latest_sha}", task_category=task_cat)
                else:
                    ui_logger.debug(f"     - [GitHub上传] 'database.json' 在远程不存在，将作为新文件创建。", task_category=task_cat)
            except Exception as e:
                ui_logger.debug(f"     - [GitHub上传] 查询 'database.json' 的 SHA 时发生异常: {e}", task_category=task_cat)
            # --- 结束核心修改 ---

            payload_dict = {
                "message": f"feat: Update database.json - {datetime.utcnow().isoformat()}",
                "content": content_b64,
                "branch": github_conf.branch
            }
            # --- 核心修改：使用最新获取的 SHA ---
            if latest_sha:
                payload_dict["sha"] = latest_sha

            payload_json_str = json.dumps(payload_dict)

            command = [
                'curl',
                '-L',
                '-X', 'PUT',
                '-H', 'Accept: application/vnd.github.v3+json',
                '-H', f'Authorization: token {github_conf.personal_access_token}',
                '-H', 'Content-Type: application/json',
                '--data-binary', '@-',
                api_url
            ]

            proxies = self.tmdb_logic.proxy_manager.get_proxies(api_url)
            if proxies.get('https'):
                command.extend(['--proxy', proxies['https']])

            result = subprocess.run(command, input=payload_json_str, capture_output=True, text=True, check=False)

            if result.returncode != 0:
                raise Exception(f"cURL 上传失败。返回码: {result.returncode}, 输出: {result.stdout}, 错误: {result.stderr}")
            
            try:
                response_json = json.loads(result.stdout)
                if "message" in response_json and "documentation_url" in response_json:
                     raise Exception(f"GitHub API 返回错误: {response_json['message']}")
            except json.JSONDecodeError:
                pass

            return True
        except Exception as e:
            ui_logger.error(f"【{task_cat}】上传 database.json 时发生错误: {e}", task_category=task_cat)
            return False
        

    def get_local_screenshots_for_series(self, series_id: str) -> List[Dict]:
        """
        扫描指定剧集的本地截图缓存目录，并返回存在截图文件的分集信息列表。
        """
        task_cat = f"精准覆盖扫描({series_id})"
        ui_logger.info(f"➡️ 开始为剧集(ID: {series_id})扫描本地截图...", task_category=task_cat)

        series_details = self._get_emby_item_details(series_id, fields="ProviderIds,Name")
        if not series_details:
            ui_logger.error(f"❌ 无法获取剧集 {series_id} 的详情，扫描中止。", task_category=task_cat)
            return []

        series_tmdb_id = next((v for k, v in series_details.get("ProviderIds", {}).items() if k.lower() == 'tmdb'), None)
        if not series_tmdb_id:
            ui_logger.error(f"❌ 剧集《{series_details.get('Name')}》缺少 TMDB ID，无法定位缓存目录。", task_category=task_cat)
            return []

        cache_dir = self._find_screenshot_cache_dir_by_tmdbid(series_tmdb_id)
        if not cache_dir:
            ui_logger.warning(f"⚠️ 未找到剧集《{series_details.get('Name')}》的本地截图缓存目录。", task_category=task_cat)
            return []

        ui_logger.info(f"🔍 找到缓存目录: {os.path.basename(cache_dir)}，开始扫描文件...", task_category=task_cat)
        
        file_pattern = re.compile(r'season-(\d+)-episode-(\d+)\.jpg', re.IGNORECASE)
        found_episodes = set()

        for filename in os.listdir(cache_dir):
            match = file_pattern.match(filename)
            if match:
                season_num = int(match.group(1))
                episode_num = int(match.group(2))
                found_episodes.add((season_num, episode_num))
        
        if not found_episodes:
            ui_logger.info("✅ 扫描完成，但未发现任何有效的截图文件。", task_category=task_cat)
            return []

        ui_logger.info(f"✅ 扫描完成，共找到 {len(found_episodes)} 个有效截图。正在匹配Emby分集信息...", task_category=task_cat)

        try:
            episodes_url = f"{self.base_url}/Items"
            episodes_params = {**self.params, "ParentId": series_id, "IncludeItemTypes": "Episode", "Recursive": "true", "Fields": "Id,Name,IndexNumber,ParentIndexNumber,SeriesName,ProviderIds"}
            episodes_resp = self.session.get(episodes_url, params=episodes_params, timeout=30)
            episodes_resp.raise_for_status()
            all_emby_episodes = episodes_resp.json().get("Items", [])
            
            result_list = []
            for ep in all_emby_episodes:
                key = (ep.get("ParentIndexNumber"), ep.get("IndexNumber"))
                if key in found_episodes:
                    result_list.append(ep)
            
            ui_logger.info(f"🎉 成功匹配到 {len(result_list)} 个可用于覆盖的分集。", task_category=task_cat)
            return result_list

        except Exception as e:
            ui_logger.error(f"❌ 在获取或匹配Emby分集信息时出错: {e}", task_category=task_cat, exc_info=True)
            return []
        

    def precise_upload_from_local_task(self, series_tmdb_id: str, series_name: str, episodes: List[Dict], config: EpisodeRefresherConfig, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """
        根据前端指令，从本地读取已有的新截图，并精准上传覆盖到 GitHub。
        """
        task_cat = f"精准覆盖-{series_name}"
        github_conf = config.github_config
        
        ui_logger.info(f"【{task_cat}】任务启动，共收到 {len(episodes)} 个分集的更新请求。", task_category=task_cat)
        
        if not github_conf.repo_url or not github_conf.personal_access_token:
            ui_logger.error(f"【{task_cat}】❌ 任务中止：未配置完整的 GitHub 仓库 URL 和个人访问令牌 (PAT)。", task_category=task_cat)
            raise ValueError("GitHub 仓库 URL 和 PAT 不能为空。")

        # 步骤 1: 获取远程数据库状态
        ui_logger.info(f"【{task_cat}】[步骤 1/3] 正在从 GitHub 获取最新的远程数据库...", task_category=task_cat)
        remote_db, remote_sha = self._get_remote_db(config, force_refresh=True)
        if remote_db is None:
            ui_logger.info(f"【{task_cat}】远程仓库似乎没有 'database.json' 文件，将创建一个新的。", task_category=task_cat)
            remote_db = {"version": 2, "last_updated": "", "series": {}}
            remote_sha = None

        # 步骤 2: 串行处理每个请求的分集
        ui_logger.info(f"【{task_cat}】[步骤 2/3] 开始逐一处理请求的分集...", task_category=task_cat)
        task_manager.update_task_progress(task_id, 0, len(episodes))
        
        successful_uploads = []
        failed_uploads = []
        skipped_uploads = []

        for i, episode_info in enumerate(episodes):
            if cancellation_event.is_set():
                ui_logger.warning(f"【{task_cat}】任务在处理中被用户取消。", task_category=task_cat)
                break
            
            season_number = episode_info.get("season_number")
            episode_number = episode_info.get("episode_number")
            log_prefix = f"➡️ S{season_number:02d}E{episode_number:02d}:"

            # 定位本地截图
            local_path = self._get_local_screenshot_path(series_tmdb_id, season_number, episode_number, series_name)
            if not local_path:
                ui_logger.error(f"{log_prefix} ❌ 无法构造本地路径，跳过。", task_category=task_cat)
                failed_uploads.append(episode_info)
                continue

            if not os.path.exists(local_path):
                ui_logger.warning(f"{log_prefix} ⚠️ 未在本地找到新截图 '{os.path.basename(local_path)}'，跳过此分集。", task_category=task_cat)
                skipped_uploads.append(episode_info)
                continue
            
            # 准备上传
            upload_item = {
                "local_path": local_path,
                "github_path": f"EpisodeScreenshots/{series_tmdb_id}/{os.path.basename(local_path)}",
                "tmdb_id": series_tmdb_id,
                "episode_key": f"{season_number}-{episode_number}"
            }

            try:
                download_url = self._upload_file_to_github(upload_item, github_conf)
                if download_url:
                    upload_item["download_url"] = download_url
                    successful_uploads.append(upload_item)
                    ui_logger.info(f"{log_prefix} ✅ 成功上传到 GitHub。", task_category=task_cat)
                else:
                    failed_uploads.append(episode_info)
                    ui_logger.error(f"{log_prefix} ❌ 上传失败。", task_category=task_cat)
            except Exception as e:
                failed_uploads.append(episode_info)
                ui_logger.error(f"{log_prefix} ❌ 上传时发生严重错误: {e}", task_category=task_cat)
            
            task_manager.update_task_progress(task_id, i + 1, len(episodes))

        # 步骤 3: 更新索引文件
        if not successful_uploads:
            ui_logger.info(f"【{task_cat}】[步骤 3/3] 本次没有任何文件成功上传，无需更新索引。", task_category=task_cat)
        else:
            ui_logger.info(f"【{task_cat}】[步骤 3/3] 正在合并并提交更新后的索引文件...", task_category=task_cat)
            final_db = remote_db
            for item in successful_uploads:
                tmdb_id = item["tmdb_id"]
                episode_key = item["episode_key"]
                if tmdb_id not in final_db["series"]:
                    final_db["series"][tmdb_id] = {}
                final_db["series"][tmdb_id][episode_key] = item["download_url"]
            final_db["last_updated"] = datetime.utcnow().isoformat() + "Z"

            if self._upload_db_to_github(final_db, remote_sha, github_conf):
                ui_logger.info(f"【{task_cat}】🎉 索引文件更新成功！", task_category=task_cat)
            else:
                ui_logger.error(f"【{task_cat}】❌ 索引文件更新失败！图片已上传但未记录，请重新运行以修复索引。", task_category=task_cat)
        
        ui_logger.info(f"【{task_cat}】任务执行完毕。成功: {len(successful_uploads)}, 失败: {len(failed_uploads)}, 跳过: {len(skipped_uploads)}", task_category=task_cat)
        return {"success": len(successful_uploads), "failed": len(failed_uploads), "skipped": len(skipped_uploads)}
    

    def _log_screenshot_for_deletion(self, series_tmdb_id: str, series_name: str, emby_series_id: str, season_number: int, episode_number: int):
        task_cat = "远程清理-记录"
        log_prefix = f"S{season_number:02d}E{episode_number:02d}:"
        
        lock_dir = os.path.join(os.path.dirname(GITHUB_DELETE_LOG_FILE), "locks")
        os.makedirs(lock_dir, exist_ok=True)
        lock_path = os.path.join(lock_dir, os.path.basename(GITHUB_DELETE_LOG_FILE) + ".lock")

        try:
            with FileLock(lock_path, timeout=10):
                if os.path.exists(GITHUB_DELETE_LOG_FILE):
                    with open(GITHUB_DELETE_LOG_FILE, 'r', encoding='utf-8') as f:
                        log_data = json.load(f)
                else:
                    log_data = {}

                episode_key = f"{season_number}-{episode_number}"
                
                if series_tmdb_id not in log_data:
                    log_data[series_tmdb_id] = {
                        "series_name": series_name,
                        "emby_series_id": emby_series_id,
                        "episodes": {}
                    }
                
                if episode_key in log_data[series_tmdb_id]["episodes"]:
                    ui_logger.debug(f"{log_prefix} [跳过] 该分集已存在于待删除日志中。", task_category=task_cat)
                    return

                log_data[series_tmdb_id]["episodes"][episode_key] = {
                    "github_path": f"EpisodeScreenshots/{series_tmdb_id}/season-{season_number}-episode-{episode_number}.jpg",
                    "pending_deletion": True,
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }

                with open(GITHUB_DELETE_LOG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(log_data, f, indent=2, ensure_ascii=False)
                
                ui_logger.info(f"{log_prefix} [成功] 已将分集信息记录到待删除日志。", task_category=task_cat)

        except Timeout:
            ui_logger.error(f"{log_prefix} ❌ 获取日志文件锁超时，无法记录待删除项！", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"{log_prefix} ❌ 写入待删除日志时发生错误: {e}", task_category=task_cat, exc_info=True)

    def get_github_delete_log(self) -> List[Dict]:
        task_cat = "远程清理-审核"
        if not os.path.exists(GITHUB_DELETE_LOG_FILE):
            return []

        lock_dir = os.path.join(os.path.dirname(GITHUB_DELETE_LOG_FILE), "locks")
        os.makedirs(lock_dir, exist_ok=True)
        lock_path = os.path.join(lock_dir, os.path.basename(GITHUB_DELETE_LOG_FILE) + ".lock")

        try:
            with FileLock(lock_path, timeout=5):
                with open(GITHUB_DELETE_LOG_FILE, 'r', encoding='utf-8') as f:
                    log_data = json.load(f)
        except (IOError, json.JSONDecodeError, Timeout) as e:
            ui_logger.error(f"❌ 读取待删除日志文件失败: {e}", task_category=task_cat)
            return []

        # 获取所有剧集下的所有分集信息
        series_episodes_map = {}
        for tmdb_id, series_info in log_data.items():
            emby_series_id = series_info.get("emby_series_id")
            if not emby_series_id:
                continue
            try:
                episodes_url = f"{self.base_url}/Items"
                episodes_params = {**self.params, "ParentId": emby_series_id, "IncludeItemTypes": "Episode", "Recursive": "true", "Fields": "Id,Name,IndexNumber,ParentIndexNumber,ImageTags"}
                episodes_resp = self.session.get(episodes_url, params=episodes_params, timeout=30)
                episodes_resp.raise_for_status()
                episodes = episodes_resp.json().get("Items", [])
                
                episode_map = {f"{ep.get('ParentIndexNumber')}-{ep.get('IndexNumber')}": ep for ep in episodes}
                series_episodes_map[tmdb_id] = episode_map
            except Exception as e:
                ui_logger.warning(f"⚠️ 获取剧集 {series_info.get('series_name')} (ID: {emby_series_id}) 的分集信息失败: {e}", task_category=task_cat)

        # 聚合最终结果
        results = []
        for tmdb_id, series_info in log_data.items():
            for episode_key, log_item in series_info.get("episodes", {}).items():
                emby_info = None
                if tmdb_id in series_episodes_map and episode_key in series_episodes_map[tmdb_id]:
                    emby_ep = series_episodes_map[tmdb_id][episode_key]
                    
                    # --- 核心修改：生成相对路径的代理URL ---
                    image_proxy_url = None
                    if emby_ep.get("ImageTags", {}).get("Primary"):
                        # 不再拼接完整的 http://... 地址
                        # 而是生成一个符合 Nginx 代理规则的相对路径
                        image_path = f"Items/{emby_ep.get('Id')}/Images/Primary?api_key={self.api_key}"
                        image_proxy_url = f"/api/emby-image-proxy?path={image_path}"

                    emby_info = {
                        "episode_id": emby_ep.get("Id"),
                        "title": emby_ep.get("Name"),
                        "image_url": image_proxy_url
                    }
                    # --- 核心修改结束 ---
                
                github_conf = self.app_config.episode_refresher_config.github_config
                github_url = ""
                if github_conf.repo_url:
                    match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", github_conf.repo_url)
                    if match:
                        owner, repo = match.groups()
                        github_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{github_conf.branch}/{log_item.get('github_path')}"

                results.append({
                    "log_item": {
                        "tmdb_id": tmdb_id,
                        "series_name": series_info.get("series_name"),
                        "emby_series_id": series_info.get("emby_series_id"), # 确保 emby_series_id 也被传递
                        "episode_key": episode_key,
                        **log_item
                    },
                    "emby_info": emby_info,
                    "github_info": {"image_url": github_url}
                })
        return results

    def save_github_delete_log(self, new_log_data: Dict):
        task_cat = "远程清理-审核"
        lock_dir = os.path.join(os.path.dirname(GITHUB_DELETE_LOG_FILE), "locks")
        os.makedirs(lock_dir, exist_ok=True)
        lock_path = os.path.join(lock_dir, os.path.basename(GITHUB_DELETE_LOG_FILE) + ".lock")
        try:
            with FileLock(lock_path, timeout=10):
                with open(GITHUB_DELETE_LOG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(new_log_data, f, indent=2, ensure_ascii=False)
            ui_logger.info("✅ 成功保存审核后的待删除日志。", task_category=task_cat)
            return True
        except Exception as e:
            ui_logger.error(f"❌ 保存待删除日志文件失败: {e}", task_category=task_cat)
            return False

    def _delete_file_from_github(self, github_path: str, sha: str, github_conf) -> bool:
        task_cat = "远程清理-执行"
        try:
            if github_conf.delete_cooldown > 0:
                ui_logger.debug(f"     - [GitHub删除] ⏱️ 删除冷却 {github_conf.delete_cooldown} 秒...", task_category=task_cat)
                time.sleep(github_conf.delete_cooldown)

            match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", github_conf.repo_url)
            owner, repo = match.groups()
            
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{github_path}"
            
            payload = {
                "message": f"chore: Remove obsolete screenshot {github_path}",
                "sha": sha,
                "branch": github_conf.branch
            }
            
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"token {github_conf.personal_access_token}"
            }
            proxies = self.tmdb_logic.proxy_manager.get_proxies(api_url)
            
            response = self.session.delete(api_url, headers=headers, json=payload, timeout=30, proxies=proxies)
            response.raise_for_status()
            
            ui_logger.info(f"     - ✅ 成功从 GitHub 删除文件: {github_path}", task_category=task_cat)
            return True

        except requests.HTTPError as e:
            ui_logger.error(f"     - ❌ 从 GitHub 删除文件失败 (HTTP {e.response.status_code}): {e.response.text}", task_category=task_cat)
            return False
        except Exception as e:
            ui_logger.error(f"     - ❌ 从 GitHub 删除文件时发生未知错误: {e}", task_category=task_cat, exc_info=True)
            return False

    def cleanup_github_screenshots_task(self, config: EpisodeRefresherConfig, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "远程清理-执行"
        ui_logger.info(f"【{task_cat}】任务启动...", task_category=task_cat)
        
        if not os.path.exists(GITHUB_DELETE_LOG_FILE):
            ui_logger.info(f"【{task_cat}】[步骤 1/6] 待删除日志文件不存在，没有需要清理的项目。", task_category=task_cat)
            return

        # 步骤 1: 读取并过滤
        ui_logger.info(f"【{task_cat}】[步骤 1/6] 正在读取并筛选待办事项...", task_category=task_cat)
        with open(GITHUB_DELETE_LOG_FILE, 'r', encoding='utf-8') as f:
            log_data = json.load(f)
        
        delete_plan = []
        for tmdb_id, series_info in log_data.items():
            for episode_key, item in series_info.get("episodes", {}).items():
                if item.get("pending_deletion"):
                    delete_plan.append({
                        "tmdb_id": tmdb_id,
                        "episode_key": episode_key,
                        "github_path": item.get("github_path")
                    })
        
        if not delete_plan:
            ui_logger.info(f"【{task_cat}】[步骤 1/6] 筛选完成，没有需要清理的项目。", task_category=task_cat)
            return
        
        ui_logger.info(f"【{task_cat}】[步骤 1/6] 筛选完成，共生成 {len(delete_plan)} 项清理计划。", task_category=task_cat)
        task_manager.update_task_progress(task_id, 0, len(delete_plan))

        # 步骤 2: 获取远程状态
        ui_logger.info(f"【{task_cat}】[步骤 2/6] 正在获取远程 GitHub 索引文件...", task_category=task_cat)
        remote_db, remote_sha = self._get_remote_db(config, force_refresh=True)
        if remote_db is None:
            ui_logger.error(f"【{task_cat}】❌ 无法获取远程索引文件，任务中止。", task_category=task_cat)
            raise Exception("无法获取远程索引文件")

        # 步骤 3 & 4: 执行文件删除
        ui_logger.info(f"【{task_cat}】[步骤 3/6] 开始逐个删除远程截图文件...", task_category=task_cat)
        github_conf = config.github_config
        match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", github_conf.repo_url)
        owner, repo = match.groups()
        
        for i, item in enumerate(delete_plan):
            if cancellation_event.is_set():
                ui_logger.warning(f"【{task_cat}】任务在删除文件阶段被用户取消。", task_category=task_cat)
                return

            github_path = item["github_path"]
            ui_logger.info(f"➡️ 正在处理第 {i + 1}/{len(delete_plan)} 项: {github_path}", task_category=task_cat)
            
            # 获取SHA
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{github_path}"
            headers = {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {github_conf.personal_access_token}"}
            proxies = self.tmdb_logic.proxy_manager.get_proxies(api_url)
            
            try:
                get_resp = self.session.get(api_url, headers=headers, timeout=20, proxies=proxies)
                if get_resp.status_code == 404:
                    ui_logger.info(f"     - ⚠️ 文件在远程已不存在，跳过删除。", task_category=task_cat)
                    task_manager.update_task_progress(task_id, i + 1, len(delete_plan))
                    continue
                get_resp.raise_for_status()
                sha = get_resp.json().get('sha')
                if not sha:
                    raise ValueError("未能从API响应中获取SHA")
            except Exception as e:
                ui_logger.error(f"     - ❌ 获取文件SHA失败: {e}，任务中止！", task_category=task_cat)
                raise e

            # 删除文件
            if not self._delete_file_from_github(github_path, sha, github_conf):
                ui_logger.error(f"     - ❌ 删除文件失败，任务中止！", task_category=task_cat)
                raise Exception(f"删除文件 {github_path} 失败")
            
            task_manager.update_task_progress(task_id, i + 1, len(delete_plan))

        # 步骤 5: 更新索引
        ui_logger.info(f"【{task_cat}】[步骤 4/6] 所有文件删除成功，正在更新远程索引...", task_category=task_cat)
        for item in delete_plan:
            tmdb_id = item["tmdb_id"]
            episode_key = item["episode_key"]
            if tmdb_id in remote_db.get("series", {}) and episode_key in remote_db["series"][tmdb_id]:
                del remote_db["series"][tmdb_id][episode_key]
                if not remote_db["series"][tmdb_id]: # 如果剧集下没有分集了，删除整个剧集条目
                    del remote_db["series"][tmdb_id]
        
        if not self._upload_db_to_github(remote_db, remote_sha, github_conf):
            ui_logger.error(f"【{task_cat}】❌ 远程索引更新失败！任务中止，请重试。", task_category=task_cat)
            raise Exception("远程索引更新失败")
        
        ui_logger.info(f"【{task_cat}】[步骤 5/6] 远程索引更新成功！", task_category=task_cat)

        # 步骤 6: 清理本地日志
        ui_logger.info(f"【{task_cat}】[步骤 6/6] 正在清理本地已处理的日志条目...", task_category=task_cat)
        lock_path = os.path.join(os.path.dirname(GITHUB_DELETE_LOG_FILE), "locks", os.path.basename(GITHUB_DELETE_LOG_FILE) + ".lock")
        with FileLock(lock_path, timeout=10):
            with open(GITHUB_DELETE_LOG_FILE, 'r', encoding='utf-8') as f:
                final_log_data = json.load(f)
            
            for item in delete_plan:
                tmdb_id = item["tmdb_id"]
                episode_key = item["episode_key"]
                if tmdb_id in final_log_data and episode_key in final_log_data[tmdb_id]["episodes"]:
                    del final_log_data[tmdb_id]["episodes"][episode_key]
                    if not final_log_data[tmdb_id]["episodes"]:
                        del final_log_data[tmdb_id]
            
            with open(GITHUB_DELETE_LOG_FILE, 'w', encoding='utf-8') as f:
                json.dump(final_log_data, f, indent=2, ensure_ascii=False)
        
        ui_logger.info(f"【{task_cat}】🎉 任务全部完成！", task_category=task_cat)