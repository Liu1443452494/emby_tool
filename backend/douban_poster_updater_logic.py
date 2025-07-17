
import logging
import threading
import time
import requests
import json
import os
import re
import base64
from typing import List, Dict, Any, Optional, Iterable

# --- 核心修改：导入 ui_logger ---
from log_manager import ui_logger
from models import AppConfig, DoubanPosterUpdaterConfig
from task_manager import TaskManager
from douban_manager import DOUBAN_CACHE_FILE

class DoubanPosterUpdaterLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.server_config = app_config.server_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.session = requests.Session()
        self.douban_map = self._load_douban_data()

    def _load_douban_data(self) -> Dict:
        task_cat = "海报更新-初始化"
        if not os.path.exists(DOUBAN_CACHE_FILE):
            ui_logger.warning("未找到豆瓣缓存文件，任务无法执行。", task_category=task_cat)
            return {}
        try:
            with open(DOUBAN_CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            ui_logger.info(f"成功加载 {len(data)} 条豆瓣缓存数据。", task_category=task_cat)
            return data
        except Exception as e:
            ui_logger.error(f"加载豆瓣缓存文件失败: {e}", task_category=task_cat)
            return {}

    def _get_item_details(self, item_id: str, fields: str = "ProviderIds,ImageTags") -> Optional[Dict]:
        """获取媒体项的详细信息"""
        try:
            url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
            params = {**self.params, "Fields": fields}
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"【豆瓣海报更新】获取媒体详情 (ID: {item_id}) 失败: {e}")
            return None

    def _get_douban_poster_tag(self, url: str) -> Optional[str]:
        """从豆瓣海报URL中提取唯一标识"""
        match = re.search(r'/(p\d+)\.', url)
        return match.group(1) if match else None


    def _upload_poster_from_url(self, item_id: str, poster_url: str, task_cat: str) -> bool:
        """从URL上传海报到Emby"""
        try:
            ui_logger.debug(f"     -- 正在从URL下载海报: {poster_url}", task_category=task_cat)
            image_response = self.session.get(poster_url, timeout=30, headers={'Referer': 'https://movie.douban.com/'})
            image_response.raise_for_status()
            image_data = image_response.content
            content_type = image_response.headers.get('Content-Type', 'image/jpeg')

            upload_url = f"{self.base_url}/Items/{item_id}/Images/Primary"
            
            try:
                ui_logger.debug(f"     -- 正在删除旧的主图...", task_category=task_cat)
                self.session.delete(upload_url, params=self.params, timeout=20)
            except requests.RequestException as e:
                ui_logger.warning(f"     -- 删除旧主图时发生错误（可能是正常的，因为没有旧图）: {e}", task_category=task_cat)

            base64_encoded_data = base64.b64encode(image_data).decode('utf-8')
            headers = {'Content-Type': content_type}
            
            ui_logger.debug(f"     -- 正在上传海报到 Emby...", task_category=task_cat)
            upload_response = self.session.post(upload_url, params=self.params, data=base64_encoded_data, headers=headers, timeout=60)
            upload_response.raise_for_status()
            return True
        except requests.RequestException as e:
            ui_logger.error(f"     -- 上传海报失败: {e}", task_category=task_cat)
            return False

    def _write_poster_tag_to_emby(self, item_id: str, poster_tag: str, task_cat: str) -> bool:
        """将海报标签写入Emby的ProviderIds"""
        try:
            item_details = self._get_item_details(item_id, fields="ProviderIds")
            if not item_details: return False

            item_details.setdefault("ProviderIds", {})['DbPosterTag'] = poster_tag
            
            update_url = f"{self.base_url}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            response = self.session.post(update_url, params=self.params, json=item_details, headers=headers, timeout=20)
            response.raise_for_status()
            ui_logger.debug(f"     -- 成功将海报标记 '{poster_tag}' 写入 Emby。", task_category=task_cat)
            return True
        except Exception as e:
            ui_logger.error(f"     -- 写入海报标记失败: {e}", task_category=task_cat)
            return False

    def run_poster_update_for_items(self, item_ids: Iterable[str], config: DoubanPosterUpdaterConfig, cancellation_event: threading.Event, task_id: Optional[str] = None, task_manager: Optional[TaskManager] = None):
        """为指定的媒体ID列表执行豆瓣海报更新"""
        task_cat = "定时任务-豆瓣海报更新"
        if not self.douban_map:
            ui_logger.error("本地豆瓣数据库为空，任务无法执行。", task_category=task_cat)
            return

        item_ids_list = list(item_ids)
        total_items = len(item_ids_list)
        ui_logger.info(f"任务启动，共需处理 {total_items} 个媒体项。", task_category=task_cat)
        ui_logger.info(f"  - 任务配置：覆盖模式={'开启' if config.overwrite_existing else '关闭'}, 更新间隔={config.update_interval}秒, 跳过大陆={'开启' if config.skip_mainland_china else '关闭'}", task_category=task_cat)
        
        if task_manager and task_id:
            task_manager.update_task_progress(task_id, 0, total_items)

        if total_items == 0:
            ui_logger.info("没有需要处理的媒体项，任务结束。", task_category=task_cat)
            return

        updated_count = 0
        for index, item_id in enumerate(item_ids_list):
            if cancellation_event.is_set():
                ui_logger.warning("任务被用户取消。", task_category=task_cat)
                break
            
            if task_manager and task_id:
                task_manager.update_task_progress(task_id, index + 1, total_items)
            
            item_summary = self._get_item_details(item_id, fields="ProviderIds,Name")
            if not item_summary:
                continue

            item_name = item_summary.get("Name", f"Item {item_id}")
            ui_logger.info(f"  -> 正在处理【{item_name}】(ID: {item_id})", task_category=task_cat)

            provider_ids = item_summary.get('ProviderIds', {})
            douban_id = next((v for k, v in provider_ids.items() if k.lower() == 'douban'), None)

            if not douban_id:
                ui_logger.debug("     -- 跳过，媒体项缺少豆瓣ID。", task_category=task_cat)
                continue

            douban_entry = self.douban_map.get(douban_id)
            if not douban_entry:
                ui_logger.warning(f"     -- 跳过，本地豆瓣缓存中未找到ID为 {douban_id} 的数据。", task_category=task_cat)
                continue

            if config.skip_mainland_china:
                countries = douban_entry.get("countries", [])
                if any(loc in ["中国大陆", "中国"] for loc in countries):
                    ui_logger.info(f"     -- 跳过，根据豆瓣数据检测到制片地区为中国大陆: {countries}", task_category=task_cat)
                    continue

            poster_url = douban_entry.get('pic', {}).get('large')
            if not poster_url:
                ui_logger.debug("     -- 跳过，该豆瓣条目无海报信息。", task_category=task_cat)
                continue

            expected_poster_tag = self._get_douban_poster_tag(poster_url)
            if not expected_poster_tag:
                ui_logger.warning(f"     -- 跳过，无法从豆瓣海报URL中提取有效Tag: {poster_url}", task_category=task_cat)
                continue

            if not config.overwrite_existing:
                provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
                current_poster_tag = provider_ids_lower.get('dbpostertag')
                if current_poster_tag == expected_poster_tag:
                    ui_logger.debug("     -- 跳过，当前海报已是最新豆瓣海报。", task_category=task_cat)
                    continue
            
            if self._upload_poster_from_url(item_id, poster_url, task_cat):
                if self._write_poster_tag_to_emby(item_id, expected_poster_tag, task_cat):
                    updated_count += 1
                    ui_logger.info(f"     -- 媒体【{item_name}】海报更新并标记成功！", task_category=task_cat)
                else:
                    ui_logger.error(f"     -- 媒体【{item_name}】海报已更新，但写入标记失败！", task_category=task_cat)
            else:
                ui_logger.error(f"     -- 媒体【{item_name}】海报更新失败。", task_category=task_cat)

            time.sleep(config.update_interval)

        ui_logger.info(f"任务执行完毕，共成功更新了 {updated_count} 个项目的海报。", task_category=task_cat)
        return {"updated_count": updated_count}