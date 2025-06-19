# backend/douban_poster_updater_logic.py (新文件)

import logging
import threading
import time
import requests
import json
import os
import re
import base64
from typing import List, Dict, Any, Optional, Iterable

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
        if not os.path.exists(DOUBAN_CACHE_FILE):
            logging.warning("【豆瓣海报更新】未找到豆瓣缓存文件，任务无法执行。")
            return {}
        try:
            with open(DOUBAN_CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logging.info(f"【豆瓣海报更新】成功加载 {len(data)} 条豆瓣缓存数据。")
            return data
        except Exception as e:
            logging.error(f"【豆瓣海报更新】加载豆瓣缓存文件失败: {e}")
            return {}

    def _get_item_details(self, item_id: str, fields: str = "ProviderIds,ImageTags,ProductionLocations") -> Optional[Dict]:
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


    def _upload_poster_from_url(self, item_id: str, poster_url: str) -> bool:
        """从URL上传海报到Emby"""
        try:
            logging.info(f"     -- 正在从URL下载海报: {poster_url}")
            image_response = self.session.get(poster_url, timeout=30, headers={'Referer': 'https://movie.douban.com/'})
            image_response.raise_for_status()
            image_data = image_response.content
            content_type = image_response.headers.get('Content-Type', 'image/jpeg')

            upload_url = f"{self.base_url}/Items/{item_id}/Images/Primary"
            
            # --- 新增：在上传前先尝试删除旧图片 ---
            try:
                logging.info(f"     -- 正在删除旧的主图...")
                self.session.delete(upload_url, params=self.params, timeout=20)
            except requests.RequestException as e:
                logging.warning(f"     -- 删除旧主图时发生错误（可能是正常的，因为没有旧图）: {e}")
            # --- 结束新增 ---

            # --- 修改：对图片数据进行 Base64 编码 ---
            base64_encoded_data = base64.b64encode(image_data).decode('utf-8')
            headers = {'Content-Type': content_type}
            
            logging.info(f"     -- 正在上传海报到 Emby...")
            # --- 修改：发送 Base64 编码后的数据 ---
            upload_response = self.session.post(upload_url, params=self.params, data=base64_encoded_data, headers=headers, timeout=60)
            upload_response.raise_for_status()
            return True
        except requests.RequestException as e:
            logging.error(f"     -- 上传海报失败: {e}")
            return False

    def _write_poster_tag_to_emby(self, item_id: str, poster_tag: str) -> bool:
        """将海报标签写入Emby的ProviderIds"""
        try:
            item_details = self._get_item_details(item_id, fields="ProviderIds")
            if not item_details: return False

            item_details.setdefault("ProviderIds", {})['DbPosterTag'] = poster_tag
            
            update_url = f"{self.base_url}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            response = self.session.post(update_url, params=self.params, json=item_details, headers=headers, timeout=20)
            response.raise_for_status()
            logging.info(f"     -- 成功将海报标记 '{poster_tag}' 写入 Emby。")
            return True
        except Exception as e:
            logging.error(f"     -- 写入海报标记失败: {e}")
            return False

    # --- 修改此方法 ---
    def run_poster_update_for_items(self, item_ids: Iterable[str], config: DoubanPosterUpdaterConfig, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """为指定的媒体ID列表执行豆瓣海报更新"""
        if not self.douban_map:
            return

        item_ids_list = list(item_ids)
        total_items = len(item_ids_list)
        logging.info(f"【豆瓣海报更新-任务】启动，共需处理 {total_items} 个媒体项。")
        logging.info(f"  - 任务配置：覆盖模式={'开启' if config.overwrite_existing else '关闭'}, 更新间隔={config.update_interval}秒, 跳过大陆={'开启' if config.skip_mainland_china else '关闭'}")
        task_manager.update_task_progress(task_id, 0, total_items)

        if total_items == 0:
            logging.info("【豆瓣海报更新-任务】没有需要处理的媒体项，任务结束。")
            return

        updated_count = 0
        for index, item_id in enumerate(item_ids_list):
            if cancellation_event.is_set():
                logging.warning("【豆瓣海报更新-任务】任务被用户取消。")
                break
            
            task_manager.update_task_progress(task_id, index + 1, total_items)
            
            item_details = self._get_item_details(item_id)
            if not item_details:
                continue

            item_name = item_details.get("Name", f"Item {item_id}")
            logging.info(f"  -> 正在处理: [{item_name}] (ID: {item_id})")

            # --- 新增逻辑：判断是否跳过中国大陆影视 ---
            if config.skip_mainland_china:
                locations = item_details.get("ProductionLocations", [])
                # 只有当 ProductionLocations 存在且明确包含中国相关标识时才跳过
                if locations:
                    is_mainland_china = any(
                        loc.lower() in ["china", "cn", "中国", "中国大陆"] for loc in locations
                    )
                    if is_mainland_china:
                        logging.info(f"     -- 跳过，检测到制片地区为中国大陆: {locations}")
                        continue
            # --- 新增逻辑结束 ---

            provider_ids = item_details.get('ProviderIds', {})
            douban_id = next((v for k, v in provider_ids.items() if k.lower() == 'douban'), None)

            if not douban_id:
                logging.info("     -- 跳过，媒体项缺少豆瓣ID。")
                continue

            douban_entry = self.douban_map.get(douban_id)
            if not douban_entry:
                logging.warning(f"     -- 跳过，本地豆瓣缓存中未找到ID为 {douban_id} 的数据。")
                continue

            poster_url = douban_entry.get('pic', {}).get('large')
            if not poster_url:
                logging.info("     -- 跳过，该豆瓣条目无海报信息。")
                continue

            expected_poster_tag = self._get_douban_poster_tag(poster_url)
            if not expected_poster_tag:
                logging.warning(f"     -- 跳过，无法从豆瓣海报URL中提取有效Tag: {poster_url}")
                continue

            # 智能判断逻辑 (仅当覆盖模式关闭时)
            if not config.overwrite_existing:
                current_poster_tag = provider_ids.get('DbPosterTag')
                if current_poster_tag == expected_poster_tag:
                    logging.info("     -- 跳过，当前海报已是最新豆瓣海报。")
                    continue
            
            # 执行更新
            if self._upload_poster_from_url(item_id, poster_url):
                if self._write_poster_tag_to_emby(item_id, expected_poster_tag):
                    updated_count += 1
                    logging.info(f"     -- 媒体 [{item_name}] 海报更新并标记成功！")
                else:
                    logging.error(f"     -- 媒体 [{item_name}] 海报已更新，但写入标记失败！")
            else:
                logging.error(f"     -- 媒体 [{item_name}] 海报更新失败。")

            # 间隔等待
            time.sleep(config.update_interval)

        logging.info(f"【豆瓣海报更新-任务】执行完毕，共成功更新了 {updated_count} 个项目的海报。")
        return {"updated_count": updated_count}