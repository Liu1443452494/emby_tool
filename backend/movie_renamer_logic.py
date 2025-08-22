# backend/movie_renamer_logic.py (新文件)

import logging
import os
import re
import threading
import time
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from log_manager import ui_logger
from models import AppConfig
from task_manager import TaskManager

# backend/movie_renamer_logic.py (类替换 - 修正版)

class MovieRenamerLogic:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.server_config = app_config.server_config
        # 复用剧集重命名的配置
        self.renamer_config = app_config.episode_renamer_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}

        # 编译正则表达式以提高效率
        self.size_regex = re.compile(r'([\[【])\s*(\d+(\.\d+)?)\s*(G|M)B?\s*([\]】])', re.IGNORECASE)
        self.iso_regex = re.compile(r'([\[【])\s*ISO\s*([\]】])', re.IGNORECASE)
        self.chinese_char_regex = re.compile('[\u4e00-\u9fa5]')

    def _get_movie_details_batch(self, item_ids: List[str], task_cat: str) -> List[Dict]:
        """批量获取电影的核心信息"""
        import requests
        
        details_list = []
        
        def fetch_detail(item_id: str):
            try:
                url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
                params = {**self.params, "Fields": "Name,Path,MediaSources"}
                response = requests.get(url, params=params, timeout=15)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                ui_logger.error(f"   - ❌ 获取电影详情 (ID: {item_id}) 失败: {e}", task_category=task_cat)
                return None

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_id = {executor.submit(fetch_detail, item_id): item_id for item_id in item_ids}
            for future in as_completed(future_to_id):
                result = future.result()
                if result:
                    details_list.append(result)
        
        return details_list

    def _get_real_filename_from_mediasources(self, media_sources: List[Dict], task_cat: str) -> Optional[str]:
        """从 MediaSources 中解析出网盘真实文件名"""
        if not media_sources or not isinstance(media_sources, list) or len(media_sources) == 0:
            return None
        
        strm_url = media_sources[0].get("Path")
        if not strm_url:
            return None

        try:
            # 兼容 ?/ 和 / 作为分隔符的情况
            return strm_url.split('?/')[-1].split('/')[-1]
        except Exception as e:
            ui_logger.warning(f"   - ⚠️ 无法从 URL '{strm_url}' 中解析出文件名: {e}", task_category=task_cat)
            return None

    def _get_clouddrive_path(self, emby_strm_path: str, real_filename: str, task_cat: str) -> Optional[str]:
        """根据 Emby 路径和真实文件名，构造 CloudDrive 的绝对路径"""
        emby_root = self.renamer_config.emby_path_root
        clouddrive_root = self.renamer_config.clouddrive_path_root
        
        if not emby_strm_path.startswith(emby_root):
            ui_logger.error(f"   - ❌ 路径错误！Emby 路径 '{emby_strm_path}' 与配置的根目录 '{emby_root}' 不匹配。", task_category=task_cat)
            return None

        relative_dir = os.path.dirname(emby_strm_path).replace(emby_root, '', 1).lstrip('/\\')
        clouddrive_dir = os.path.join(clouddrive_root, relative_dir)
        
        return os.path.join(clouddrive_dir, real_filename)

    def _format_filesize(self, size_bytes: int) -> str:
        """将字节大小格式化为 x.xxG"""
        if size_bytes == 0:
            return "0G"
        gb_size = size_bytes / (1024**3)
        return f"{gb_size:.2f}G"

    def _rename_associated_files(self, old_base_path: str, new_base_path: str, task_cat: str) -> bool:
        """重命名 .strm, .nfo, 和 -thumb.jpg 等关联文件"""
        renamed_any = False
        dir_name = os.path.dirname(old_base_path)
        old_filename_no_ext = os.path.basename(old_base_path)
        new_filename_no_ext = os.path.basename(new_base_path)

        # 遍历目录下的所有文件
        for filename in os.listdir(dir_name):
            if filename.startswith(old_filename_no_ext):
                # 构造旧路径和新路径
                old_file_path = os.path.join(dir_name, filename)
                new_filename = filename.replace(old_filename_no_ext, new_filename_no_ext, 1)
                new_file_path = os.path.join(dir_name, new_filename)
                
                try:
                    os.rename(old_file_path, new_file_path)
                    ui_logger.info(f"     - ✅ 成功重命名关联文件: {filename} -> {new_filename}", task_category=task_cat)
                    renamed_any = True
                except OSError as e:
                    ui_logger.error(f"     - ❌ 重命名关联文件失败: {filename}。错误: {e}", task_category=task_cat)
        
        return renamed_any

    def process_single_movie(self, movie_info: Dict, task_cat: str) -> Dict:
        """处理单个电影的核心逻辑函数"""
        item_id = movie_info.get("Id")
        emby_name = movie_info.get("Name", f"ID {item_id}")
        emby_path = movie_info.get("Path")
        media_sources = movie_info.get("MediaSources")

        ui_logger.info(f"--- 正在处理电影: 【{emby_name}】 ---", task_category=task_cat)

        if not all([emby_path, media_sources]):
            return {"status": "skipped", "message": "缺少路径或 MediaSources 信息"}

        real_filename = self._get_real_filename_from_mediasources(media_sources, task_cat)
        if not real_filename:
            return {"status": "skipped", "message": "无法从 MediaSources 解析真实文件名"}

        # --- 阶段二：预检查 ---
        filename_body, file_ext = os.path.splitext(real_filename)
        
        size_match = self.size_regex.search(filename_body)
        is_iso = file_ext.lower() == '.iso'
        
        # 检查大小标签
        if not size_match:
            ui_logger.info(f"  - [预检查] ➡️ 不合格 (原因: 缺失大小标签)", task_category=task_cat)
        elif size_match.start() > 35:
            ui_logger.info(f"  - [预检查] ➡️ 不合格 (原因: 大小标签位置靠后, 索引 {size_match.start()} > 35)", task_category=task_cat)
        else:
            # 大小标签合格，检查 ISO 标签
            if not is_iso:
                ui_logger.info(f"  - [预检查] ✅ 合格 (大小标签位置规范, 非 ISO 文件)", task_category=task_cat)
                return {"status": "skipped", "message": "命名已规范"}
            
            iso_match = self.iso_regex.search(filename_body)
            if not iso_match:
                ui_logger.info(f"  - [预检查] ➡️ 不合格 (原因: ISO 文件缺失 [ISO] 标签)", task_category=task_cat)
            elif iso_match.start() > 35:
                ui_logger.info(f"  - [预检查] ➡️ 不合格 (原因: [ISO] 标签位置靠后, 索引 {iso_match.start()} > 35)", task_category=task_cat)
            else:
                ui_logger.info(f"  - [预检查] ✅ 合格 (大小和 ISO 标签均位置规范)", task_category=task_cat)
                return {"status": "skipped", "message": "命名已规范"}

        # --- 阶段三：完整处理 ---
        ui_logger.info(f"  - [完整处理] 开始为【{emby_name}】构建理想文件名...", task_category=task_cat)
        
        # 1. 获取/确定所需信息
        size_tag = ""
        if size_match:
            size_tag = size_match.group(0)
            ui_logger.debug(f"    - 从文件名中提取到大小标签: {size_tag}", task_category=task_cat)
        else:
            clouddrive_path = self._get_clouddrive_path(emby_path, real_filename, task_cat)
            if clouddrive_path and os.path.exists(clouddrive_path):
                try:
                    file_size_bytes = os.path.getsize(clouddrive_path)
                    size_tag = f"[{self._format_filesize(file_size_bytes)}]"
                    ui_logger.info(f"    - 成功获取到真实文件大小: {self._format_filesize(file_size_bytes)}", task_category=task_cat)
                except OSError as e:
                    ui_logger.error(f"    - ❌ 获取文件大小失败: {e}", task_category=task_cat)
                    return {"status": "error", "message": f"获取文件大小失败: {e}"}
            else:
                ui_logger.warning(f"    - ⚠️ 无法定位网盘文件或文件不存在，跳过大小获取: {clouddrive_path}", task_category=task_cat)
                return {"status": "skipped", "message": "无法定位网盘文件"}

        iso_tag = ""
        if is_iso:
            iso_tag = "[ISO]"

        clean_body = self.size_regex.sub('', filename_body)
        clean_body = self.iso_regex.sub('', clean_body).strip()

        chinese_title_prefix = ""
        if not self.chinese_char_regex.search(clean_body):
            chinese_title_prefix = f"{emby_name}."
            ui_logger.info(f"    - 检测到纯英文文件名，将添加中文标题前缀: {chinese_title_prefix}", task_category=task_cat)

        # 2. 构建理想文件名
        parts = []
        if iso_tag:
            parts.append(iso_tag)
        if size_tag:
            parts.append(size_tag)
        
        ideal_filename_no_ext = " ".join(parts)
        if chinese_title_prefix:
            ideal_filename_no_ext += f" {chinese_title_prefix}{clean_body}"
        else:
            ideal_filename_no_ext += f" {clean_body}"
        
        ideal_filename = f"{ideal_filename_no_ext.strip()}{file_ext}"
        
        # 3. 比较与执行
        if ideal_filename == real_filename:
            ui_logger.info(f"  - [最终比较] ✅ 文件名无需改动。", task_category=task_cat)
            return {"status": "skipped", "message": "计算后发现无需改动"}

        ui_logger.info(f"  - [执行重命名] 计划: {real_filename} -> {ideal_filename}", task_category=task_cat)
        
        # a. 重命名网盘文件
        old_clouddrive_path = self._get_clouddrive_path(emby_path, real_filename, task_cat)
        new_clouddrive_path = self._get_clouddrive_path(emby_path, ideal_filename, task_cat)
        if not old_clouddrive_path or not new_clouddrive_path:
            return {"status": "error", "message": "无法构造网盘文件路径"}
        
        try:
            os.rename(old_clouddrive_path, new_clouddrive_path)
            ui_logger.info(f"    - ✅ 成功重命名网盘文件。", task_category=task_cat)
        except OSError as e:
            ui_logger.error(f"    - ❌ 重命名网盘文件失败: {e}", task_category=task_cat)
            return {"status": "error", "message": f"重命名网盘文件失败: {e}"}

        # b. 重命名本地关联文件
        local_dir = os.path.dirname(emby_path)
        old_base_path = os.path.join(local_dir, filename_body)
        new_base_path = os.path.join(local_dir, os.path.splitext(ideal_filename)[0])
        self._rename_associated_files(old_base_path, new_base_path, task_cat)

        # c. 修改 .strm 文件内容
        new_strm_path = f"{new_base_path}.strm"
        if os.path.exists(new_strm_path):
            try:
                with open(new_strm_path, 'r', encoding='utf-8') as f:
                    strm_content = f.read()
                
                new_strm_content = strm_content.replace(real_filename, ideal_filename)
                
                with open(new_strm_path, 'w', encoding='utf-8') as f:
                    f.write(new_strm_content)
                ui_logger.info(f"    - ✅ 成功更新 .strm 文件内容。", task_category=task_cat)
            except IOError as e:
                ui_logger.error(f"    - ❌ 更新 .strm 文件内容失败: {e}", task_category=task_cat)
        
        # d. 执行冷却
        # --- 核心修改：直接使用配置中的冷却时间 ---
        cooldown = self.renamer_config.clouddrive_rename_cooldown
        if cooldown > 0:
            ui_logger.debug(f"    - [冷却] ⏱️ 等待 {cooldown} 秒...", task_category=task_cat)
            time.sleep(cooldown)
        # --- 修改结束 ---

        return {"status": "success", "message": f"成功重命名为 {ideal_filename}"}

    def run_rename_task_for_items(self, item_ids: List[str], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager, task_category: str):
        """(定时任务)为指定的电影 ID 列表执行文件重命名。"""
        # --- 核心修改：移除前置检查 ---
        total_items = len(item_ids)
        ui_logger.info(f"【电影重命名任务】启动，共需处理 {total_items} 个电影。", task_category=task_category)
        task_manager.update_task_progress(task_id, 0, total_items)

        ui_logger.info(f"➡️ 正在批量获取 {total_items} 个电影的元数据...", task_category=task_category)
        all_movie_details = self._get_movie_details_batch(item_ids, task_category)
        
        if not all_movie_details:
            ui_logger.warning("⚠️ 未能获取到任何电影的有效信息，任务中止。", task_category=task_category)
            return

        processed_count = 0
        success_count = 0
        skipped_count = 0
        error_count = 0

        for movie_info in all_movie_details:
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务在处理中被用户取消。", task_category=task_category)
                break
            
            result = self.process_single_movie(movie_info, task_category)
            
            if result["status"] == "success":
                success_count += 1
            elif result["status"] == "skipped":
                skipped_count += 1
            else: # error
                error_count += 1

            processed_count += 1
            task_manager.update_task_progress(task_id, processed_count, total_items)

        ui_logger.info(f"---", task_category=task_category)
        ui_logger.info(f"🎉【电影重命名任务】全部执行完毕。", task_category=task_category)
        ui_logger.info(f"  - 成功重命名: {success_count} 项", task_category=task_category)
        ui_logger.info(f"  - 跳过 (已规范): {skipped_count} 项", task_category=task_category)
        ui_logger.info(f"  - 失败: {error_count} 项", task_category=task_category)