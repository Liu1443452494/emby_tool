# backend/local_extractor.py (最终修正版)

import os
import shutil
import logging
import threading
import platform  # 导入 platform 模块
from typing import List, Dict

from models import AppConfig, LocalExtractRequest
from task_manager import TaskManager

def _get_long_path_prefix():
    """根据操作系统返回长路径前缀"""
    if platform.system() == "Windows":
        return "\\\\?\\"
    return ""

def extract_local_media_task(
    config: AppConfig,
    req: LocalExtractRequest,
    cancellation_event: threading.Event,
    task_id: str,
    task_manager: TaskManager
):
    """
    从本地源文件夹提取媒体信息文件到全局下载目录的任务。
    新逻辑：根据用户指定的后缀名和特定文件名进行匹配。
    """
    source_path = req.source_path
    extensions = [ext.lower() for ext in req.extensions]
    filenames = [fname.lower() for fname in req.filenames]

    if 'logo' in filenames:
        extended_filenames = set(filenames)
        extended_filenames.add('clearlogo')
        filenames = list(extended_filenames)

    logging.info(f"【本地提取】任务启动，源目录: {source_path}")
    
    # --- 核心修改 1: 获取长路径前缀 ---
    long_path_prefix = _get_long_path_prefix()

    # --- 核心修改 2: 对源路径应用长路径支持 ---
    prefixed_source_path = long_path_prefix + os.path.abspath(source_path)

    if not os.path.isdir(prefixed_source_path):
        logging.error(f"【本地提取】源目录 '{source_path}' 不存在或不是一个目录，任务中止。")
        raise ValueError("源目录无效")

    download_dir = config.download_config.download_directory
    if not download_dir:
        logging.error("【本地提取】全局下载目录未配置，任务中止。")
        raise ValueError("全局下载目录未配置")

    overwrite_behavior = config.download_config.download_behavior
    logging.info(f"【本地提取】目标目录: {download_dir}, 文件处理方式: {overwrite_behavior}")
    logging.info(f"【本地提取】需要提取的后缀: {extensions}")
    logging.info(f"【本地提取】最终查找的特定文件名: {filenames}")

    if not extensions and not filenames:
        logging.warning("【本地提取】没有指定任何文件后缀或特定文件名，任务结束。")
        task_manager.update_task_progress(task_id, 0, 0)
        return {"found": 0, "copied": 0, "skipped": 0, "failed": 0}

    found_files = []
    logging.info("【本地提取】第一阶段：正在扫描源目录以查找匹配文件...")
    task_manager.update_task_progress(task_id, 0, -1)

    # --- 核心修改 3: 使用带前缀的路径进行扫描 ---
    for root, _, files in os.walk(prefixed_source_path):
        if cancellation_event.is_set():
            logging.warning("【本地提取】任务在扫描阶段被取消。")
            return
        for file in files:
            file_lower = file.lower()
            file_name_without_ext, file_ext = os.path.splitext(file_lower)
            
            should_add = False
            if file_ext in extensions:
                should_add = True
            elif file_name_without_ext in filenames:
                should_add = True
            
            if should_add:
                source_file_path = os.path.join(root, file)
                found_files.append(source_file_path)
                task_manager.update_task_progress(task_id, len(found_files), -1)

    total_files = len(found_files)
    logging.info(f"【本地提取】扫描完成，共找到 {total_files} 个匹配的文件。")
    logging.info("【本地提取】第二阶段：开始复制文件...")
    task_manager.update_task_progress(task_id, 0, total_files)

    copied_count = 0
    skipped_count = 0
    failed_count = 0
    failed_files = []

    for i, src_file in enumerate(found_files):
        if cancellation_event.is_set():
            logging.warning("【本地提取】任务在复制阶段被取消。")
            break
        
        try:
            # --- 核心修改 4: 对所有文件操作的路径都应用长路径支持 ---
            # 注意：os.walk 返回的 src_file 已经包含了前缀
            
            # 计算相对路径时，要从带前缀的源路径开始计算
            relative_path = os.path.relpath(src_file, prefixed_source_path)
            
            # 构造目标路径
            prefixed_dest_file = long_path_prefix + os.path.abspath(os.path.join(download_dir, relative_path))
            
            if os.path.exists(prefixed_dest_file) and overwrite_behavior == "skip":
                logging.info(f"  -> 跳过 (已存在): {relative_path}")
                skipped_count += 1
                continue

            prefixed_dest_dir = os.path.dirname(prefixed_dest_file)
            os.makedirs(prefixed_dest_dir, exist_ok=True)
            
            shutil.copy2(src_file, prefixed_dest_file)
            logging.info(f"  -> 成功复制: {relative_path}")
            copied_count += 1

        except Exception as e:
            # 去掉前缀，方便日志阅读
            clean_src_path = src_file.replace(long_path_prefix, "", 1)
            error_msg = f"【本地提取】复制文件 '{clean_src_path}' 时出错: {e}"
            logging.error(error_msg)
            failed_count += 1
            failed_files.append({"path": clean_src_path, "error": str(e)})
        finally:
            task_manager.update_task_progress(task_id, i + 1, total_files)

    logging.info(f"【本地提取】任务完成。共找到 {total_files} 个文件，成功复制 {copied_count} 个，跳过 {skipped_count} 个，失败 {failed_count} 个。")

    if failed_files:
        logging.warning("--- 以下文件在复制过程中失败 ---")
        for failed_item in failed_files:
            logging.warning(f"  文件: {failed_item['path']}")
            logging.warning(f"  原因: {failed_item['error']}")
        logging.warning("---------------------------------")

    return {"found": total_files, "copied": copied_count, "skipped": skipped_count, "failed": failed_count}