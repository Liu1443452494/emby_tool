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

        self._physical_library_cache: Optional[List[Dict]] = None

        # 编译正则表达式以提高效率
        self.size_regex = re.compile(r'([\[【])\s*(\d+(\.\d+)?)\s*(G|M)B?\s*([\]】])', re.IGNORECASE)
        self.iso_regex = re.compile(r'([\[【])\s*ISO\s*([\]】])', re.IGNORECASE)
        self.chinese_char_regex = re.compile('[\u4e00-\u9fa5]')

    def _get_library_for_item(self, item_path: str, task_cat: str) -> Optional[Dict]:
        """根据媒体项的物理路径，定位其所属的媒体库。"""
        import requests
        try:
            # 1. 获取所有媒体库及其扫描路径 (带缓存)
            if self._physical_library_cache is None:
                ui_logger.info(f"  - [媒体库定位] 首次运行，正在从 Emby 获取所有媒体库的物理路径...", task_category=task_cat)
                folders_url = f"{self.base_url}/Library/VirtualFolders/Query"
                folders_params = self.params
                # 兼容 Jellyfin 的路径
                try:
                    folders_response = requests.get(folders_url, params=folders_params, timeout=15)
                    if folders_response.status_code == 404:
                        folders_url = f"{self.base_url}/emby/Library/VirtualFolders/Query"
                        folders_response = requests.get(folders_url, params=folders_params, timeout=15)
                    folders_response.raise_for_status()
                    self._physical_library_cache = folders_response.json().get("Items", [])
                except requests.RequestException as e:
                    ui_logger.error(f"  - ❌ [媒体库定位] 获取媒体库物理路径失败: {e}", task_category=task_cat)
                    self._physical_library_cache = []
            
            # 2. 进行前缀匹配
            for library in self._physical_library_cache:
                if library.get("CollectionType") == "boxsets": continue # 显式跳过合集
                locations = library.get("Locations", [])
                for loc_path in locations:
                    # 确保路径格式一致，避免因尾部斜杠导致匹配失败
                    normalized_loc_path = os.path.join(loc_path, '')
                    normalized_item_path = os.path.join(item_path, '')
                    if normalized_item_path.startswith(normalized_loc_path):
                        library_info = {"Id": library.get("ItemId", library.get("Id")), "Name": library.get("Name")}
                        ui_logger.info(f"  - [媒体库定位] ✅ 成功匹配！媒体项位于媒体库【{library_info['Name']}】中。", task_category=task_cat)
                        return library_info
            
            ui_logger.warning(f"  - ⚠️ [媒体库定位] 未能为路径 '{item_path}' 匹配到任何媒体库。", task_category=task_cat)
            return None
        except Exception as e:
            ui_logger.error(f"  - ❌ [媒体库定位] 发生未知错误: {e}", task_category=task_cat, exc_info=True)
            return None

    def _trigger_library_scan(self, library_id: str, library_name: str, task_cat: str):
        """触发指定媒体库的文件扫描。"""
        import requests
        ui_logger.info(f"  - [媒体库扫描] 正在为媒体库【{library_name}】(ID: {library_id}) 触发文件扫描...", task_category=task_cat)
        try:
            url = f"{self.base_url}/Library/Refresh"
            params = {**self.params, "Recursive": "true"}
            response = requests.post(url, params=params, timeout=30)
            response.raise_for_status()
            ui_logger.info(f"  - [媒体库扫描] ✅ 已成功发送扫描指令。", task_category=task_cat)
        except requests.RequestException as e:
            ui_logger.error(f"  - ❌ [媒体库扫描] 向 Emby 发送扫描指令失败: {e}", task_category=task_cat)

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

    # --- 核心修改：重构此函数，增加 target_item_id 参数 ---
    def _find_source_and_get_filename(self, media_sources: List[Dict], target_item_id: str, task_cat: str) -> Optional[Tuple[Dict, str]]:
        """
        从 MediaSources 数组中精确查找与 target_item_id 匹配的源，并返回该源对象和解析出的文件名。
        """
        ui_logger.info(f"  - [数据解析] 🔍 开始在 {len(media_sources)} 个媒体源中查找匹配 ID: {target_item_id} 的源...", task_category=task_cat)
        
        if not media_sources or not isinstance(media_sources, list):
            ui_logger.warning("    - ⚠️ 'MediaSources' 字段为空或格式不正确，无法查找。", task_category=task_cat)
            return None

        found_source = None
        for i, source in enumerate(media_sources):
            source_item_id = source.get("ItemId")
            ui_logger.debug(f"    - 正在检查源 {i+1}/{len(media_sources)}: 其 ItemId 为 '{source_item_id}'", task_category=task_cat)
            if str(source_item_id) == str(target_item_id):
                found_source = source
                ui_logger.info(f"    - ✅ 命中！在第 {i+1} 个位置找到了匹配的媒体源。", task_category=task_cat)
                break
        
        if not found_source:
            ui_logger.error(f"    - ❌ 严重错误: 遍历了所有媒体源，但未找到任何一个源的 ItemId 与目标 ID '{target_item_id}' 匹配！", task_category=task_cat)
            return None

        strm_url = found_source.get("Path")
        if not strm_url:
            ui_logger.error("    - ❌ 匹配到的媒体源中缺少 'Path' 字段，无法解析文件名。", task_category=task_cat)
            return None
        
        ui_logger.debug(f"    - 从命中的源获取到 Path (URL): \"{strm_url}\"", task_category=task_cat)

        try:
            filename = strm_url.split('?/')[-1].split('/')[-1]
            ui_logger.info(f"    - 成功从 URL 中解析出真实文件名: '{filename}'", task_category=task_cat)
            return found_source, filename
        except Exception as e:
            ui_logger.error(f"    - ❌ 从 URL '{strm_url}' 解析文件名时出错: {e}", task_category=task_cat)
            return None
    # --- 修改结束 ---

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

    # backend/movie_renamer_logic.py (函数替换)

    def _rename_associated_files(self, old_base_path: str, new_base_path: str, task_cat: str) -> bool:
        """
        精确地重命名关联文件，通过主动构建目标清单并查找匹配项的方式。
        """
        renamed_any = False
        dir_name = os.path.dirname(old_base_path)
        old_filename_no_ext = os.path.basename(old_base_path)
        new_filename_no_ext = os.path.basename(new_base_path)

        # --- 核心修改：采用“主动构建，精确查找”的新逻辑 ---

        # 1. 定义构建模板
        BASE_EXTENSIONS = ['.nfo', '.jpg', '.png', '.webp']
        SUFFIX_MODIFIERS = ['-poster', '-fanart', '-clearlogo', '-thumb']

        # 2. 构建期望查找的关联文件清单
        target_filenames = set()
        # 第一轮：直接拼接 (e.g., '测试.nfo')
        for ext in BASE_EXTENSIONS:
            target_filenames.add(f"{old_filename_no_ext}{ext}")
        
        # 第二轮：后缀拼接 (e.g., '测试-poster.jpg')
        for suffix in SUFFIX_MODIFIERS:
            for ext in BASE_EXTENSIONS:
                target_filenames.add(f"{old_filename_no_ext}{suffix}{ext}")
        
        ui_logger.info(f"     - [关联文件扫描] 已构建 {len(target_filenames)} 个潜在关联文件目标，开始在目录中查找...", task_category=task_cat)
        ui_logger.debug(f"       - 目标清单: {target_filenames}", task_category=task_cat)

        try:
            # 3. 遍历实际文件并执行操作
            for filename in os.listdir(dir_name):
                # 检查当前文件是否在我们的目标清单中
                if filename in target_filenames:
                    old_file_path = os.path.join(dir_name, filename)
                    
                    # 构造新文件名，精确替换基础部分
                    new_filename = filename.replace(old_filename_no_ext, new_filename_no_ext, 1)
                    new_file_path = os.path.join(dir_name, new_filename)

                    # 安全检查
                    if old_file_path == new_file_path:
                        continue

                    try:
                        os.rename(old_file_path, new_file_path)
                        ui_logger.info(f"       - ✅ 成功重命名关联文件: {filename} -> {new_filename}", task_category=task_cat)
                        renamed_any = True
                    except OSError as e:
                        ui_logger.error(f"       - ❌ 重命名关联文件 '{filename}' 失败: {e}", task_category=task_cat)
            
            ui_logger.info("     - [关联文件扫描] 扫描和处理完成。", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"     - ❌ 在处理关联文件时发生未知错误: {e}", task_category=task_cat)

        # --- 修改结束 ---
        return renamed_any

    # backend/movie_renamer_logic.py (函数替换)

    def process_single_movie(self, movie_info: Dict, task_cat: str) -> Optional[Dict]:
        """
        处理单个电影的核心逻辑函数。
        成功重命名后，返回其所在的 library_info 字典。
        如果跳过或失败，返回 None。
        """
        item_id = movie_info.get("Id")
        emby_name = movie_info.get("Name", f"ID {item_id}")
        emby_path = movie_info.get("Path")
        media_sources = movie_info.get("MediaSources")

        ui_logger.info(f"--- 正在处理电影: 【{emby_name}】 (ID: {item_id}) ---", task_category=task_cat)

        if not all([emby_path, media_sources]):
            ui_logger.warning(f"  - [跳过] 媒体项缺少 Path 或 MediaSources 关键信息。", task_category=task_cat)
            return None

        find_result = self._find_source_and_get_filename(media_sources, item_id, task_cat)
        if not find_result:
            ui_logger.error(f"  - [跳过] 无法为 ID {item_id} 找到匹配的媒体源或解析文件名。", task_category=task_cat)
            return None
        
        target_source, real_filename = find_result

        # --- 阶段二：预检查 ---
        ui_logger.info(f"  - [预检查] 正在检查文件名: '{real_filename}'", task_category=task_cat)
        filename_body, file_ext = os.path.splitext(real_filename)
        
        size_match = self.size_regex.search(filename_body)
        is_iso = file_ext.lower() == '.iso'
        
        if size_match and size_match.start() <= 20:
            if not is_iso:
                ui_logger.info(f"    - ✅ 合格 (大小标签位置规范, 非 ISO 文件)", task_category=task_cat)
                return None
            
            iso_match = self.iso_regex.search(filename_body)
            if iso_match and iso_match.start() <= 20:
                ui_logger.info(f"    - ✅ 合格 (大小和 ISO 标签均位置规范)", task_category=task_cat)
                return None

        ui_logger.info(f"    - ➡️ 不合格，将执行重命名流程。", task_category=task_cat)

        # --- 阶段三：完整处理 ---
        ui_logger.info(f"  - [完整处理] 开始为【{emby_name}】构建理想文件名...", task_category=task_cat)
        
        size_tag = ""
        if size_match:
            size_tag = size_match.group(0)
        else:
            clouddrive_path = self._get_clouddrive_path(emby_path, real_filename, task_cat)
            if clouddrive_path and os.path.exists(clouddrive_path):
                try:
                    file_size_bytes = os.path.getsize(clouddrive_path)
                    size_tag = f"[{self._format_filesize(file_size_bytes)}]"
                except OSError as e:
                    ui_logger.error(f"    - ❌ 获取文件大小失败: {e}", task_category=task_cat)
                    return None
            else:
                ui_logger.warning(f"    - ⚠️ 无法定位网盘文件或文件不存在，跳过大小获取: {clouddrive_path}", task_category=task_cat)
                return None

        iso_tag = "[ISO]" if is_iso else ""
        clean_body = self.size_regex.sub('', filename_body)
        clean_body = self.iso_regex.sub('', clean_body).strip()

        chinese_title_prefix = ""
        if not self.chinese_char_regex.search(clean_body):
            chinese_title_prefix = f"{emby_name}."

        parts = [p for p in [iso_tag, size_tag] if p]
        ideal_filename_no_ext = " ".join(parts)
        ideal_filename_no_ext += f" {chinese_title_prefix}{clean_body}"
        ideal_filename = f"{ideal_filename_no_ext.strip()}{file_ext}"
        
        if ideal_filename == real_filename:
            ui_logger.info(f"  - [最终比较] ✅ 文件名无需改动。", task_category=task_cat)
            return None

        ui_logger.info(f"  - [执行重命名] 计划: {real_filename} -> {ideal_filename}", task_category=task_cat)
        
        old_clouddrive_path = self._get_clouddrive_path(emby_path, real_filename, task_cat)
        new_clouddrive_path = self._get_clouddrive_path(emby_path, ideal_filename, task_cat)
        if not old_clouddrive_path or not new_clouddrive_path:
            return None
        
        try:
            os.rename(old_clouddrive_path, new_clouddrive_path)
            ui_logger.info(f"    - ✅ 成功重命名网盘文件。", task_category=task_cat)
        except OSError as e:
            ui_logger.error(f"    - ❌ 重命名网盘文件失败: {e}", task_category=task_cat)
            return None

        local_dir = os.path.dirname(emby_path)
        old_base_path = os.path.join(local_dir, filename_body)
        new_base_path = os.path.join(local_dir, os.path.splitext(ideal_filename)[0])
        self._rename_associated_files(old_base_path, new_base_path, task_cat)

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
        
        cooldown = self.renamer_config.clouddrive_rename_cooldown
        if cooldown > 0:
            time.sleep(cooldown)

        # 成功后，定位媒体库并返回信息
        return self._get_library_for_item(emby_path, task_cat)

    # backend/movie_renamer_logic.py (函数替换)

    def run_rename_task_for_items(self, item_ids: List[str], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager, task_category: str):
        """(定时任务)为指定的电影 ID 列表执行文件重命名，并在任务结束后统一触发媒体库扫描。"""
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
        # --- 新增：用于任务内聚合需要扫描的媒体库 ---
        libraries_to_scan = {}

        for movie_info in all_movie_details:
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务在处理中被用户取消。", task_category=task_category)
                break
            
            # --- 修改：接收返回值 ---
            library_info = self.process_single_movie(movie_info, task_category)
            
            if library_info:
                success_count += 1
                # --- 新增：将需要扫描的库ID和名称存入字典 ---
                libraries_to_scan[library_info['Id']] = library_info['Name']
            else:
                # process_single_movie 返回 None 代表跳过或失败
                # 这里的计数逻辑可以根据需要细化，但目前笼统处理
                skipped_count += 1

            processed_count += 1
            task_manager.update_task_progress(task_id, processed_count, total_items)

        # --- 新增：任务结束后统一触发扫描 ---
        if not cancellation_event.is_set() and libraries_to_scan:
            ui_logger.info(f"---", task_category=task_category)
            ui_logger.info(f"➡️ 所有文件处理完毕，将为 {len(libraries_to_scan)} 个媒体库触发文件扫描...", task_category=task_category)
            for lib_id, lib_name in libraries_to_scan.items():
                self._trigger_library_scan(lib_id, lib_name, task_category)
        # --- 新增结束 ---

        ui_logger.info(f"---", task_category=task_category)
        ui_logger.info(f"🎉【电影重命名任务】全部执行完毕。", task_category=task_category)
        ui_logger.info(f"  - 成功重命名: {success_count} 项", task_category=task_category)
        ui_logger.info(f"  - 跳过或失败: {total_items - success_count} 项", task_category=task_category)