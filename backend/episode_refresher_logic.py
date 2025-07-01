# backend/episode_refresher_logic.py (完整代码)

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
from typing import List, Iterable, Optional, Dict
from collections import defaultdict

from log_manager import ui_logger
from models import AppConfig, EpisodeRefresherConfig
from task_manager import TaskManager
from tmdb_logic import TmdbLogic

class EpisodeRefresherLogic:
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
        """判断标题是否为“第X集”这种通用格式"""
        if not text: return True
        pattern = re.compile(r'^(第\s*\d+\s*集|Episode\s*\d+)$', re.IGNORECASE)
        return bool(pattern.match(text.strip()))

    def _unlock_item(self, item_id: str, task_category: str) -> bool:
        try:
            details_url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
            details_resp = self.session.get(details_url, params=self.params, timeout=15)
            details_resp.raise_for_status()
            item_details = details_resp.json()
            if item_details.get("LockedFields") and len(item_details["LockedFields"]) > 0:
                ui_logger.debug(f"     - 检测到锁定的字段: {item_details['LockedFields']}，正在解锁...", task_category=task_category)
                item_details["LockedFields"] = []
                update_url = f"{self.base_url}/Items/{item_id}"
                headers = {'Content-Type': 'application/json'}
                update_resp = self.session.post(update_url, params=self.params, json=item_details, headers=headers, timeout=20)
                update_resp.raise_for_status()
                ui_logger.debug(f"     - 媒体项 (ID: {item_id}) 已成功解锁。", task_category=task_category)
            else:
                ui_logger.debug(f"     - 媒体项 (ID: {item_id}) 无需解锁。", task_category=task_category)
            return True
        except requests.RequestException as e:
            ui_logger.error(f"     - 解锁媒体项 (ID: {item_id}) 时发生网络错误: {e}", task_category=task_category)
            return False
        except Exception as e:
            ui_logger.error(f"     - 解锁媒体项 (ID: {item_id}) 时发生未知错误: {e}", task_category=task_category, exc_info=True)
            return False


    def _refresh_single_episode_by_emby(self, episode_id: str, config: EpisodeRefresherConfig, task_category: str) -> bool:
        try:
            if not self._unlock_item(episode_id, task_category):
                ui_logger.warning(f"     - 解锁媒体项 (ID: {episode_id}) 失败，刷新可能不会生效。", task_category=task_category)
            
            url = f"{self.base_url}/Items/{episode_id}/Refresh"
            
            # --- 核心修改：调整图片刷新模式 ---
            # 将 ImageRefreshMode 从 FullRefresh 改为 Default
            # 这将使 Emby 只下载缺失的图片，而不会删除已有的图片（比如我们的截图）
            params = {
                **self.params,
                "Recursive": "true",
                "MetadataRefreshMode": "FullRefresh",
                "ImageRefreshMode": "Default", # <--- 修改点
                "ReplaceAllMetadata": str(config.overwrite_metadata).lower(),
                "ReplaceAllImages": "false" # <--- 修改点：配合 Default 模式，设置为 false
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
            ui_logger.debug(f"     - 正在从URL下载图片: {image_url}", task_category=task_category)
            proxies = self.tmdb_logic.proxy_manager.get_proxies(image_url)
            image_response = self.tmdb_logic.session.get(image_url, timeout=30, proxies=proxies)
            image_response.raise_for_status()
            image_data = image_response.content
            content_type = image_response.headers.get('Content-Type', 'image/jpeg')
            return self._upload_image_bytes(item_id, image_data, content_type, task_category)
        except Exception as e:
            ui_logger.error(f"     - 从URL下载并上传图片到 Emby (ID: {item_id}) 失败: {e}", task_category=task_category, exc_info=True)
            return False

    def _upload_image_bytes(self, item_id: str, image_data: bytes, content_type: str, task_category: str) -> bool:
        """通用上传二进制图片数据的方法"""
        try:
            upload_url = f"{self.base_url}/Items/{item_id}/Images/Primary"
            
            try:
                self.session.delete(upload_url, params=self.params, timeout=20)
            except requests.RequestException as e:
                ui_logger.warning(f"     - 删除旧主图时发生错误（可能是正常的）: {e}", task_category=task_category)

            base64_encoded_data = base64.b64encode(image_data).decode('utf-8')
            
            headers = {'Content-Type': content_type}
            
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
            ui_logger.error(f"     - 上传图片二进制数据到 Emby (ID: {item_id}) 失败: {e}", task_category=task_category, exc_info=True)
            return False

    def _get_video_url_from_item(self, episode_id: str, task_category: str) -> Optional[str]:
        """从 Emby 获取媒体项的流媒体 URL，兼容 DirectStreamUrl 和 MediaSources[].Path"""
        try:
            details_url = f"{self.base_url}/Users/{self.user_id}/Items/{episode_id}"
            details_params = {**self.params, "Fields": "MediaSources"}
            details_resp = self.session.get(details_url, params=details_params, timeout=15)
            details_resp.raise_for_status()
            item_details = details_resp.json()

            ui_logger.debug(f"     - [截图-调试] 获取到的分集(ID: {episode_id})完整信息: {json.dumps(item_details, indent=2, ensure_ascii=False)}", task_category=task_category)

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
        """使用 ffprobe 获取视频时长"""
        try:
            command = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-i', video_url
            ]
            ui_logger.debug(f"     - [截图] 执行 ffprobe 命令获取时长...", task_category=task_category)
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

    def _capture_screenshot(self, video_url: str, seek_time: float, config: EpisodeRefresherConfig, task_category: str) -> Optional[bytes]:
        """使用 ffmpeg 从视频流截图，并根据配置处理黑边和比例"""
        try:
            crop_detect_cmd = [
                'ffmpeg', '-ss', str(seek_time - 3 if seek_time > 5 else 1),
                '-i', video_url, '-t', '2', '-vf', 'cropdetect',
                '-f', 'null', '-'
            ]
            ui_logger.debug(f"     - [截图-检测] 执行 cropdetect 命令...", task_category=task_category)
            result = subprocess.run(crop_detect_cmd, capture_output=True, text=True, timeout=60)
            
            crop_filter = ""
            crop_match = re.search(r'crop=(\d+:\d+:\d+:\d+)', result.stderr)
            if crop_match:
                detected_crop_params = crop_match.group(1)
                w, h, x, y = map(int, detected_crop_params.split(':'))
                ui_logger.debug(f"     - [截图-检测] 检测到有效画面区域: {detected_crop_params}", task_category=task_category)

                if config.crop_widescreen_to_16_9 and w / h > 1.8:
                    target_w = round(h * 16 / 9)
                    if target_w < w:
                        offset_x = round((w - target_w) / 2)
                        crop_filter = f"crop={detected_crop_params},crop={target_w}:{h}:{offset_x}:0"
                        ui_logger.info(f"     - [截图-裁剪] 已将宽屏截图从 {w}x{h} 裁剪为 16:9 ({target_w}x{h})", task_category=task_category)
                    else:
                        crop_filter = f"crop={detected_crop_params}"
                else:
                    crop_filter = f"crop={detected_crop_params}"
            else:
                ui_logger.warning("     - [截图-检测] 未能检测到黑边信息，将不进行裁剪。", task_category=task_category)

            capture_cmd = [
                'ffmpeg', '-ss', str(seek_time),
                '-i', video_url, '-vframes', '1',
                '-q:v', '2', '-f', 'image2pipe', '-'
            ]
            if crop_filter:
                capture_cmd.insert(5, '-vf')
                capture_cmd.insert(6, crop_filter)

            ui_logger.debug(f"     - [截图-执行] 执行 ffmpeg 命令: {' '.join(capture_cmd)}", task_category=task_category)
            capture_result = subprocess.run(capture_cmd, capture_output=True, check=True, timeout=60)
            return capture_result.stdout

        except subprocess.TimeoutExpired:
            ui_logger.error("     - [截图] ffmpeg 截图或检测超时。", task_category=task_category)
            return None
        except subprocess.CalledProcessError as e:
            if 'cropdetect' in ' '.join(e.cmd):
                 ui_logger.warning(f"     - [截图-回退] 黑边检测失败，尝试不裁剪直接截图。错误: {e.stderr}", task_category=task_category)
                 try:
                    fallback_cmd = ['ffmpeg', '-ss', str(seek_time), '-i', video_url, '-vframes', '1', '-q:v', '2', '-f', 'image2pipe', '-']
                    fallback_result = subprocess.run(fallback_cmd, capture_output=True, check=True, timeout=60)
                    return fallback_result.stdout
                 except Exception as fallback_e:
                    ui_logger.error(f"     - [截图-回退] 无裁剪截图也失败: {fallback_e}", task_category=task_category)
                    return None
            else:
                ui_logger.error(f"     - [截图] ffmpeg 截图失败: {e.stderr}", task_category=task_category)
                return None
        except Exception as e:
            ui_logger.error(f"     - [截图] 截图过程中发生未知错误: {e}", task_category=task_category, exc_info=True)
            return None

    def _handle_screenshot_flow(self, episode_id: str, episode_details: Dict, config: EpisodeRefresherConfig, task_category: str) -> bool:
        """完整的截图流程"""
        if not self.ffmpeg_available:
            ui_logger.warning("     - [截图] ffmpeg 或 ffprobe 未安装，跳过截图功能。", task_category=task_category)
            return False

        duration = None
        
        runtime_ticks = episode_details.get("RunTimeTicks")
        if runtime_ticks and runtime_ticks > 0:
            duration = runtime_ticks / 10_000_000
            ui_logger.debug(f"     - [截图] 从 Emby 元数据中直接获取到时长: {duration:.2f}s", task_category=task_category)
        
        video_url = None
        if duration is None:
            ui_logger.debug("     - [截图] Emby元数据中无时长，尝试调用 ffprobe 获取...", task_category=task_category)
            video_url = self._get_video_url_from_item(episode_id, task_category)
            if video_url:
                duration = self._get_video_duration(video_url, task_category)

        if duration:
            seek_time = duration * (config.screenshot_percentage / 100)
        else:
            ui_logger.warning(f"     - [截图] 所有方式均获取视频时长失败，将使用保底秒数: {config.screenshot_fallback_seconds}s", task_category=task_category)
            seek_time = config.screenshot_fallback_seconds
        
        if not video_url:
            video_url = self._get_video_url_from_item(episode_id, task_category)

        if not video_url:
            ui_logger.error(f"     - [截图] 最终未能获取到视频流 URL，无法截图。", task_category=task_category)
            return False

        image_bytes = self._capture_screenshot(video_url, seek_time, config, task_category)
        if image_bytes:
            return self._upload_image_bytes(episode_id, image_bytes, 'image/jpeg', task_category)
        
        return False

    def _set_image_source_tag(self, item_id: str, source: str, task_category: str):
        """为媒体项写入图片来源标签"""
        try:
            item_details = self.tmdb_logic._get_emby_item_details(item_id, fields="ProviderIds")
            if not item_details: return

            item_details.setdefault("ProviderIds", {})['ToolboxImageSource'] = source
            
            update_url = f"{self.base_url}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            self.session.post(update_url, params=self.params, json=item_details, headers=headers, timeout=20).raise_for_status()
            ui_logger.debug(f"     - 成功将图片来源标记 '{source}' 写入 Emby (ID: {item_id})。", task_category=task_category)
        except Exception as e:
            ui_logger.error(f"     - 写入图片来源标记失败 (ID: {item_id}): {e}", task_category=task_category)

    def _clear_image_source_tag(self, item_id: str, task_category: str):
        """清理媒体项的图片来源标签"""
        try:
            item_details = self.tmdb_logic._get_emby_item_details(item_id, fields="ProviderIds")
            if not item_details: return

            provider_ids = item_details.get("ProviderIds", {})
            if 'ToolboxImageSource' in provider_ids:
                del provider_ids['ToolboxImageSource']
                update_url = f"{self.base_url}/Items/{item_id}"
                headers = {'Content-Type': 'application/json'}
                self.session.post(update_url, params=self.params, json=item_details, headers=headers, timeout=20).raise_for_status()
                ui_logger.debug(f"     - 成功从 Emby (ID: {item_id}) 移除图片来源标记。", task_category=task_category)
        except Exception as e:
            ui_logger.error(f"     - 移除图片来源标记失败 (ID: {item_id}): {e}", task_category=task_category)

    # backend/episode_refresher_logic.py (修改 _refresh_season_by_toolbox 函数)

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
                
                log_prefix = f"     - 《{series_name_for_log}》S{season_number:02d}E{episode_num:02d}:"

                tmdb_episode = tmdb_episodes_map.get(episode_num)
                if not tmdb_episode:
                    ui_logger.debug(f"{log_prefix} 在TMDB返回的列表中未找到对应分集。", task_category=task_category)
                    continue

                potential_changes = {}
                reasons_to_skip = []

                # --- 核心修改：增加详细的日志理由 ---

                # 1. 检查元数据
                emby_name = emby_episode.get("Name", "")
                tmdb_name = tmdb_episode.get("name")
                if tmdb_name and not self._is_generic_episode_title(tmdb_name) and tmdb_name != emby_name:
                    potential_changes["Name"] = tmdb_name
                else:
                    if not tmdb_name:
                        reasons_to_skip.append("标题(TMDB源为空)")
                    elif self._is_generic_episode_title(tmdb_name):
                        reasons_to_skip.append(f"标题(TMDB源为通用标题'{tmdb_name}')")
                    elif tmdb_name == emby_name:
                        reasons_to_skip.append("标题(与Emby相同)")

                emby_overview = emby_episode.get("Overview", "")
                tmdb_overview = tmdb_episode.get("overview")
                if tmdb_overview and tmdb_overview != emby_overview:
                    potential_changes["Overview"] = tmdb_overview
                else:
                    if not tmdb_overview:
                        reasons_to_skip.append("简介(TMDB源为空)")
                    elif tmdb_overview == emby_overview:
                        reasons_to_skip.append("简介(与Emby相同)")

                emby_premiere_date = emby_episode.get("PremiereDate", "")
                tmdb_air_date = tmdb_episode.get("air_date")
                if tmdb_air_date:
                    if not emby_premiere_date or tmdb_air_date != emby_premiere_date[:10]:
                        potential_changes["PremiereDate"] = tmdb_air_date + "T00:00:00.000Z"
                    else:
                        reasons_to_skip.append("首播日期(与Emby相同)")
                else:
                    reasons_to_skip.append("首播日期(TMDB源为空)")

                # 2. 检查图片
                current_image_source = emby_episode.get("ProviderIds", {}).get("ToolboxImageSource")
                emby_has_image = bool(emby_episode.get("ImageTags", {}).get("Primary"))
                tmdb_still_path = tmdb_episode.get("still_path")

                if tmdb_still_path:
                    # 即使 TMDB 有图，如果 Emby 的图来源不是截图，我们也不主动更新（遵循非激进策略）
                    # 只有当 Emby 无图，或者 Emby 的图是截图时，才认为需要用 TMDB 的图更新
                    if not emby_has_image or current_image_source == "screenshot":
                        potential_changes["Image"] = ("tmdb", tmdb_still_path)
                    else:
                        reasons_to_skip.append("图片(Emby已有非截图主图)")
                elif config.screenshot_enabled:
                    should_screenshot = False
                    if not emby_has_image:
                        should_screenshot = True
                    elif config.force_overwrite_screenshots and current_image_source == "screenshot":
                        should_screenshot = True
                    
                    if should_screenshot:
                        potential_changes["Image"] = ("screenshot", None)
                    else:
                        if emby_has_image:
                            reasons_to_skip.append("图片(已有图且未强制覆盖截图)")
                        else: # 逻辑上不会到这里，但作为兜底
                            reasons_to_skip.append("图片(截图条件不满足)")
                else:
                    reasons_to_skip.append("图片(TMDB无图且未开启截图)")

                # 3. 根据检查结果执行操作或打印详细日志
                if not potential_changes:
                    # 将理由列表组合成一个字符串
                    reason_str = ", ".join(reasons_to_skip) if reasons_to_skip else "未知原因"
                    ui_logger.info(f"{log_prefix} 无需更新 ({reason_str})", task_category=task_category)
                    continue

                # 4. 应用变更 (此部分逻辑不变)
                final_changes_log = []
                
                metadata_to_update = {k: v for k, v in potential_changes.items() if k != "Image"}
                if metadata_to_update:
                    if self._unlock_item(emby_episode["Id"], task_category):
                        update_payload = emby_episode.copy()
                        update_payload.update(metadata_to_update)
                        update_url = f"{self.base_url}/Items/{emby_episode['Id']}"
                        headers = {'Content-Type': 'application/json'}
                        try:
                            self.session.post(update_url, params=self.params, json=update_payload, headers=headers, timeout=20).raise_for_status()
                            final_changes_log.extend(metadata_to_update.keys())
                        except Exception as e:
                            ui_logger.error(f"{log_prefix} 应用元数据更新时失败: {e}", task_category=task_category)
                    else:
                        ui_logger.error(f"{log_prefix} 解锁失败，跳过元数据更新。", task_category=task_category)

                if "Image" in potential_changes:
                    img_source, img_data = potential_changes["Image"]
                    if img_source == "tmdb":
                        image_url = f"https://image.tmdb.org/t/p/original{img_data}"
                        if self._upload_image_from_url(emby_episode["Id"], image_url, task_category):
                            final_changes_log.append("图片(TMDB)")
                            if current_image_source == "screenshot":
                                self._clear_image_source_tag(emby_episode["Id"], task_category)
                    elif img_source == "screenshot":
                        if self._handle_screenshot_flow(emby_episode["Id"], emby_episode, config, task_category):
                            final_changes_log.append("图片(截图)")
                            self._set_image_source_tag(emby_episode["Id"], "screenshot", task_category)

                if final_changes_log:
                    ui_logger.info(f"{log_prefix} 成功更新到Emby，内容: [{', '.join(final_changes_log)}]", task_category=task_category)
                    updated_count += 1
                else:
                    ui_logger.warning(f"{log_prefix} 检测到需要更新，但所有更新操作均失败。", task_category=task_category)

                time.sleep(0.2)

        except Exception as e:
            ui_logger.error(f"     - 处理 S{season_number:02d} 时发生错误: {e}", task_category=task_category, exc_info=True)
        
        return updated_count

    def run_refresh_for_episodes(
        self, 
        episode_ids: Iterable[str], 
        config: EpisodeRefresherConfig, 
        cancellation_event: threading.Event, 
        task_id: Optional[str] = None, 
        task_manager: Optional[TaskManager] = None,
        task_category: str = "剧集刷新"
    ):
        episode_ids_list = list(episode_ids)
        total_episodes = len(episode_ids_list)
        
        ui_logger.info(f"任务启动，共需处理 {total_episodes} 个剧集分集。", task_category=task_category)
        ui_logger.info(f"  - 刷新模式: {'工具箱代理刷新' if config.refresh_mode == 'toolbox' else '通知Emby刷新'}", task_category=task_category)
        if config.refresh_mode == 'emby':
            ui_logger.info(f"  - 元数据写入方式: {'覆盖所有元数据' if config.overwrite_metadata else '仅补充缺失'}", task_category=task_category)
        else:
            ui_logger.info(f"  - 截图功能: {'开启' if config.screenshot_enabled else '关闭'}", task_category=task_category)
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
                details_url = f"{self.base_url}/Users/{self.user_id}/Items/{episode_id}"
                details_params = {**self.params, "Fields": fields_to_get}
                details_resp = self.session.get(details_url, params=details_params, timeout=15)
                details_resp.raise_for_status()
                all_episode_details.append(details_resp.json())
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