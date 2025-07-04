# backend/poster_manager_logic.py

import logging
import os
import json
import threading
import time
import re
import base64
import subprocess
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
from filelock import FileLock, Timeout
from datetime import datetime, timedelta

from log_manager import ui_logger
from models import AppConfig, PosterManagerConfig, ScheduledTasksTargetScope
from task_manager import TaskManager
from media_selector import MediaSelector
from proxy_manager import ProxyManager
import config as app_config_module

# --- 常量定义 ---
AGGREGATED_INDEX_CACHE_FILE = os.path.join('/app/data', 'poster_manager_aggregated_index.json')
AGGREGATED_INDEX_CACHE_DURATION = 3600  # 缓存1小时 (3600秒)

class PosterManagerLogic:
    def __init__(self, config: AppConfig):
        self.config = config
        self.pm_config = config.poster_manager_config
        self.proxy_manager = ProxyManager(config)
        self.session = self._create_session()

    def _create_session(self):
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _get_tmdb_id(self, item_id: str) -> Optional[str]:
        """从 Emby 获取媒体项的 TMDB ID"""
        try:
            url = f"{self.config.server_config.server}/Users/{self.config.server_config.user_id}/Items/{item_id}"
            params = {"api_key": self.config.server_config.api_key, "Fields": "ProviderIds"}
            proxies = self.proxy_manager.get_proxies(url)
            response = self.session.get(url, params=params, timeout=15, proxies=proxies)
            response.raise_for_status()
            provider_ids = response.json().get("ProviderIds", {})
            return provider_ids.get("Tmdb")
        except Exception as e:
            logging.error(f"【海报备份】获取媒体项 {item_id} 的 TMDB ID 失败: {e}")
            return None

    def _scan_local_cache(self, media_ids: List[str], content_types: List[str], task_cat: str) -> List[Dict]:
        """扫描本地缓存目录，生成初始待办列表"""
        ui_logger.info(f"➡️ [阶段1.2] 开始扫描本地缓存目录: {self.pm_config.local_cache_path}", task_category=task_cat)
        
        if not self.pm_config.local_cache_path or not os.path.isdir(self.pm_config.local_cache_path):
            raise ValueError(f"本地缓存路径 '{self.pm_config.local_cache_path}' 无效或未配置。")

        type_map = {
            "poster": "poster.jpg",
            "logo": "clearlogo.png",
            "fanart": "fanart.jpg"
        }
        
        initial_pending_list = []
        tmdb_id_map = {}

        # 批量获取TMDB ID以减少API调用
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_id = {executor.submit(self._get_tmdb_id, item_id): item_id for item_id in media_ids}
            for future in future_to_id:
                item_id = future_to_id[future]
                try:
                    tmdb_id = future.result()
                    if tmdb_id:
                        tmdb_id_map[item_id] = tmdb_id
                except Exception as e:
                    logging.error(f"【海报备份】获取 TMDB ID 时出错 (Emby ID: {item_id}): {e}")

        for item_id in media_ids:
            tmdb_id = tmdb_id_map.get(item_id)
            if not tmdb_id:
                ui_logger.warning(f"⚠️ 跳过 Emby ID: {item_id}，因为它没有关联的 TMDB ID。", task_category=task_cat)
                continue

            item_cache_dir = os.path.join(self.pm_config.local_cache_path, tmdb_id)
            if not os.path.isdir(item_cache_dir):
                continue

            for content_type in content_types:
                filename = type_map.get(content_type)
                if not filename: continue
                
                filepath = os.path.join(item_cache_dir, filename)
                if os.path.isfile(filepath):
                    try:
                        file_size = os.path.getsize(filepath)
                        initial_pending_list.append({
                            "local_path": filepath,
                            "tmdb_id": tmdb_id,
                            "image_type": content_type,
                            "size": file_size
                        })
                    except OSError as e:
                        ui_logger.error(f"❌ 无法获取文件大小: {filepath}。错误: {e}", task_category=task_cat)
        
        ui_logger.info(f"✅ [阶段1.2] 本地扫描完成，共找到 {len(initial_pending_list)} 个待处理文件。", task_category=task_cat)
        return initial_pending_list

    def _get_repo_index(self, repo_config: Dict) -> Optional[Dict]:
        """获取单个仓库的 database.json 内容"""
        repo_url = repo_config['repo_url']
        branch = repo_config.get('branch', 'main')
        pat = repo_config.get('personal_access_token') or self.pm_config.global_personal_access_token
        
        match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", repo_url)
        if not match:
            logging.error(f"【海报备份】无效的 GitHub 仓库 URL: {repo_url}")
            return None
        owner, repo = match.groups()
        
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/database.json?ref={branch}"
        headers = {"Accept": "application/vnd.github.v3+json"}
        if pat:
            headers["Authorization"] = f"token {pat}"
        
        try:
            proxies = self.proxy_manager.get_proxies(api_url)
            response = self.session.get(api_url, headers=headers, timeout=30, proxies=proxies)
            if response.status_code == 404:
                return {"version": 1, "last_updated": "", "images": {}} # 仓库是新的，返回空索引
            response.raise_for_status()
            
            content = base64.b64decode(response.json()['content']).decode('utf-8')
            return json.loads(content)
        except Exception as e:
            logging.error(f"【海报备份】获取仓库 {repo_url} 的索引失败: {e}")
            return None

    def _get_aggregated_remote_index(self, task_cat: str) -> Dict:
        """通过缓存或并发获取，得到聚合的所有远程文件索引"""
        ui_logger.info("➡️ [阶段1.3] 开始获取并聚合所有远程仓库的索引...", task_category=task_cat)
        
        lock_path = AGGREGATED_INDEX_CACHE_FILE + ".lock"
        try:
            with FileLock(lock_path, timeout=5):
                if os.path.exists(AGGREGATED_INDEX_CACHE_FILE):
                    with open(AGGREGATED_INDEX_CACHE_FILE, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                    cached_at = datetime.fromisoformat(cache_data.get("cached_at"))
                    if datetime.now() - cached_at < timedelta(seconds=AGGREGATED_INDEX_CACHE_DURATION):
                        ui_logger.info("✅ [阶段1.3] 命中本地聚合索引缓存。", task_category=task_cat)
                        return cache_data.get("aggregated_index", {})
        except (Timeout, IOError, json.JSONDecodeError) as e:
            ui_logger.warning(f"⚠️ 读取聚合缓存失败，将强制从网络获取。原因: {e}", task_category=task_cat)

        remote_file_map = {}
        repos = self.pm_config.github_repos
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_repo = {executor.submit(self._get_repo_index, repo.model_dump()): repo for repo in repos}
            for future in future_to_repo:
                repo_config = future_to_repo[future]
                try:
                    time.sleep(0.1) # 内部短冷却
                    index_content = future.result()
                    if index_content and "images" in index_content:
                        for tmdb_id, images in index_content["images"].items():
                            for image_type, image_info in images.items():
                                key = f"{tmdb_id}-{image_type}"
                                remote_file_map[key] = image_info
                except Exception as e:
                    ui_logger.error(f"❌ 处理仓库 {repo_config.repo_url} 索引时出错: {e}", task_category=task_cat)

        # 回写缓存
        try:
            with FileLock(lock_path, timeout=10):
                cache_content = {
                    "cached_at": datetime.now().isoformat(),
                    "aggregated_index": remote_file_map
                }
                with open(AGGREGATED_INDEX_CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(cache_content, f)
                ui_logger.info("✅ [阶段1.3] 成功聚合远程索引并已写入本地缓存。", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"❌ 写入聚合索引缓存失败: {e}", task_category=task_cat)
            
        return remote_file_map

    def _classify_pending_files(self, initial_list: List[Dict], remote_map: Dict, task_cat: str) -> Tuple[List, List]:
        """将待办列表分为新增和覆盖两类"""
        ui_logger.info("➡️ [阶段2] 开始对待办文件进行分类 (新增/覆盖)...", task_category=task_cat)
        new_files = []
        overwrite_files = []
        
        for item in initial_list:
            key = f"{item['tmdb_id']}-{item['image_type']}"
            remote_info = remote_map.get(key)
            
            if not remote_info:
                new_files.append(item)
            elif self.pm_config.overwrite_remote_files:
                item['remote_info'] = remote_info
                overwrite_files.append(item)
        
        ui_logger.info(f"✅ [阶段2] 分类完成。新增: {len(new_files)} 项, 覆盖: {len(overwrite_files)} 项。", task_category=task_cat)
        return new_files, overwrite_files

    def _calculate_dispatch_plan(self, new_files: List, overwrite_files: List, task_cat: str) -> Dict:
        """核心算法：计算文件分发计划"""
        ui_logger.info("➡️ [阶段3] 正在进行精确预计算，生成文件分发计划...", task_category=task_cat)
        
        dispatch_plan = {repo.repo_url: {"new": [], "overwrite": []} for repo in self.pm_config.github_repos}
        
        # 初始化仓库临时状态
        threshold_bytes = self.pm_config.repository_size_threshold_mb * 1024 * 1024
        temp_repo_states = {
            repo.repo_url: threshold_bytes - (repo.state.size_kb * 1024)
            for repo in self.pm_config.github_repos
        }

        # 1. 处理覆盖文件
        for item in overwrite_files:
            new_size = item['size']
            old_size = item['remote_info']['size']
            delta = new_size - old_size
            repo_url = item['remote_info']['repo_url']
            
            if temp_repo_states.get(repo_url, -1) < delta:
                raise ValueError(f"文件覆盖失败：覆盖文件 {item['local_path']} 将导致仓库 {repo_url} 超出容量限制。")
            
            dispatch_plan[repo_url]["overwrite"].append(item)
            temp_repo_states[repo_url] -= delta
            ui_logger.info(f"  - [计划-覆盖] {os.path.basename(item['local_path'])} -> 分配至原仓库 {repo_url} (空间变化: {delta/1024/1024:+.2f} MB)", task_category=task_cat)

        # 2. 处理新增文件
        for item in new_files:
            allocated = False
            for repo in self.pm_config.github_repos: # 按优先级顺序
                if temp_repo_states.get(repo.repo_url, -1) >= item['size']:
                    dispatch_plan[repo.repo_url]["new"].append(item)
                    temp_repo_states[repo.repo_url] -= item['size']
                    ui_logger.info(f"  - [计划-新增] {os.path.basename(item['local_path'])} ({item['size']/1024/1024:.2f} MB) -> 分配至 {repo.repo_url}", task_category=task_cat)
                    allocated = True
                    break
            if not allocated:
                raise ValueError(f"文件分配失败：文件 {item['local_path']} ({item['size']/1024/1024:.2f} MB) 过大，所有仓库均无足够空间容纳。")

        ui_logger.info("✅ [阶段3] 文件分发计划制定成功。", task_category=task_cat)
        return dispatch_plan
    
    def _execute_github_write_request(self, method: str, url: str, pat: str, payload: Optional[Dict] = None) -> Dict:
        """通过 curl 执行 GitHub 写入操作"""
        command = [
            'curl', '-L', '-X', method,
            '-H', 'Accept: application/vnd.github.v3+json',
            '-H', f'Authorization: token {pat}',
            '-H', 'Content-Type: application/json'
        ]
        
        json_payload_str = ""
        if payload:
            command.extend(['--data-binary', '@-'])
            json_payload_str = json.dumps(payload)

        proxies = self.proxy_manager.get_proxies(url)
        if proxies.get('https'):
            command.extend(['--proxy', proxies['https']])

        result = subprocess.run(command, input=json_payload_str, capture_output=True, text=True, check=False)
        
        response_data = {}
        try:
            if result.stdout:
                response_data = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise Exception(f"cURL 返回了非JSON响应: {result.stdout} | 错误: {result.stderr}")

        if result.returncode != 0 or (response_data.get("message") and response_data.get("documentation_url")):
            error_message = response_data.get('message', f"cURL 错误: {result.stderr}")
            if response_data.get('status') == '422' and "sha" in error_message:
                error_message = f"无效请求 (422)。服务器提示 'sha' 参数有问题。这可能是因为在您操作期间，文件被其他进程修改。请重试。({error_message})"
            elif "409 Conflict" in result.stderr:
                error_message = "GitHub API 返回 409 Conflict 错误，这通常是并发写入冲突导致的。请稍后重试。"
            raise Exception(f"GitHub API 错误: {error_message}")

        return response_data

    def _get_latest_repo_size(self, repo_url: str, pat: str) -> int:
        """获取仓库的最新大小 (KB)"""
        match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", repo_url)
        owner, repo = match.groups()
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {"Accept": "application/vnd.github.v3+json"}
        if pat:
            headers["Authorization"] = f"token {pat}"
        
        proxies = self.proxy_manager.get_proxies(api_url)
        response = self.session.get(api_url, headers=headers, timeout=30, proxies=proxies)
        response.raise_for_status()
        return response.json().get('size', 0)

    # TODO: 实现阶段四的执行逻辑
    def _execute_dispatch_plan(self, dispatch_plan: Dict, task_cat: str, cancellation_event: threading.Event):
        """执行文件上传和索引更新"""
        ui_logger.info("➡️ [阶段4] 开始执行文件上传和索引更新...", task_category=task_cat)
        
        # 按优先级处理仓库
        for repo_config in self.pm_config.github_repos:
            repo_url = repo_config.repo_url
            plan = dispatch_plan.get(repo_url)
            if not plan or (not plan['new'] and not plan['overwrite']):
                continue

            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务在执行阶段被取消。", task_category=task_cat)
                return

            ui_logger.info(f"  - 正在处理仓库: {repo_url}", task_category=task_cat)
            pat = repo_config.personal_access_token or self.pm_config.global_personal_access_token
            branch = repo_config.branch
            match = re.match(r"httpshttps?://github\.com/([^/]+)/([^/]+)", repo_url)
            owner, repo_name = match.groups()

            # 1. 加锁
            lock_path = ".lock"
            lock_api_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{lock_path}"
            lock_payload = {
                "message": f"feat: Acquire lock for task",
                "content": base64.b64encode(f"locked_at: {datetime.now().isoformat()}".encode()).decode(),
                "branch": branch
            }
            self._execute_github_write_request("PUT", lock_api_url, pat, lock_payload)
            ui_logger.info(f"    - 🔒 已成功在仓库 {repo_url} 中创建 .lock 文件。", task_category=task_cat)

            try:
                # 2. 获取最新索引
                current_index = self._get_repo_index(repo_config.model_dump())
                if current_index is None:
                    raise Exception("获取最新索引失败，无法继续。")

                # 3. 上传文件
                files_to_process = plan['overwrite'] + plan['new']
                for item in files_to_process:
                    if cancellation_event.is_set(): raise InterruptedError("任务被取消")
                    
                    time.sleep(self.pm_config.file_upload_cooldown_seconds)
                    
                    with open(item['local_path'], 'rb') as f:
                        content_b64 = base64.b64encode(f.read()).decode()
                    
                    github_path = f"images/{item['tmdb_id']}/{os.path.basename(item['local_path'])}"
                    api_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{github_path}"
                    
                    payload = {
                        "message": f"feat: Add/Update {item['image_type']} for {item['tmdb_id']}",
                        "content": content_b64,
                        "branch": branch
                    }

                    # 如果是覆盖，带上SHA
                    if 'remote_info' in item:
                        payload['sha'] = item['remote_info']['sha']

                    try:
                        response_data = self._execute_github_write_request("PUT", api_url, pat, payload)
                    except Exception as e:
                        # 新增转覆盖容错
                        if "422" in str(e) and 'remote_info' not in item:
                            ui_logger.warning(f"    - 🔄 文件 {github_path} 已存在，触发“新增转覆盖”容错机制...", task_category=task_cat)
                            # 获取SHA重试
                            get_resp = self.session.get(api_url, headers={"Authorization": f"token {pat}"}, proxies=self.proxy_manager.get_proxies(api_url)).json()
                            payload['sha'] = get_resp['sha']
                            response_data = self._execute_github_write_request("PUT", api_url, pat, payload)
                        else:
                            raise e

                    # 4. 更新内存中的索引
                    tmdb_id_str = str(item['tmdb_id'])
                    if tmdb_id_str not in current_index['images']:
                        current_index['images'][tmdb_id_str] = {}
                    
                    current_index['images'][tmdb_id_str][item['image_type']] = {
                        "repo_url": repo_url,
                        "sha": response_data['content']['sha'],
                        "size": response_data['content']['size'],
                        "url": response_data['content']['download_url']
                    }
                    ui_logger.info(f"    - ⬆️ 上传成功: {github_path}", task_category=task_cat)

                # 5. 提交更新后的索引
                current_index['last_updated'] = datetime.now().isoformat()
                index_api_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/database.json"
                
                # 获取最新的 index SHA
                get_index_resp = self.session.get(index_api_url, headers={"Authorization": f"token {pat}"}, proxies=self.proxy_manager.get_proxies(index_api_url)).json()
                index_sha = get_index_resp.get('sha')

                index_payload = {
                    "message": f"chore: Update database index",
                    "content": base64.b64encode(json.dumps(current_index, indent=2).encode()).decode(),
                    "branch": branch
                }
                if index_sha:
                    index_payload['sha'] = index_sha
                
                self._execute_github_write_request("PUT", index_api_url, pat, index_payload)
                ui_logger.info(f"    - 索引文件 database.json 更新成功。", task_category=task_cat)

                # 6. 更新config中的仓库大小
                latest_size_kb = self._get_latest_repo_size(repo_url, pat)
                current_config = app_config_module.load_app_config()
                for r in current_config.poster_manager_config.github_repos:
                    if r.repo_url == repo_url:
                        r.state.size_kb = latest_size_kb
                        r.state.last_checked = datetime.now().isoformat()
                        break
                app_config_module.save_app_config(current_config)
                ui_logger.info(f"    - 仓库 {repo_url} 最新容量 {latest_size_kb} KB 已回写配置。", task_category=task_cat)

            finally:
                # 7. 解锁
                # 获取锁文件的SHA
                lock_get_resp = self.session.get(lock_api_url, headers={"Authorization": f"token {pat}"}, proxies=self.proxy_manager.get_proxies(lock_api_url)).json()
                lock_sha = lock_get_resp.get('sha')
                if lock_sha:
                    delete_payload = {
                        "message": "feat: Release lock",
                        "sha": lock_sha,
                        "branch": branch
                    }
                    self._execute_github_write_request("DELETE", lock_api_url, pat, delete_payload)
                    ui_logger.info(f"    - 🔓 已成功从仓库 {repo_url} 中移除 .lock 文件。", task_category=task_cat)

        ui_logger.info("✅ [阶段4] 所有文件上传和索引更新完成。", task_category=task_cat)

    def _restore_single_item(self, item_id: str, tmdb_id: str, content_types: List[str], remote_map: Dict, task_cat: str):
        """恢复单个媒体项的图片"""
        import requests
        
        item_name = ""
        try:
            # 尝试获取 Emby 媒体项名称用于日志记录
            details = self._get_emby_item_details(item_id, "Name")
            item_name = details.get("Name", f"ID {item_id}")
        except Exception:
            item_name = f"ID {item_id}"

        ui_logger.info(f"  -> 正在为【{item_name}】执行恢复...", task_category=task_cat)
        
        for image_type in content_types:
            key = f"{tmdb_id}-{image_type}"
            image_info = remote_map.get(key)

            if not image_info:
                ui_logger.debug(f"     - 跳过: 在远程备份中未找到【{item_name}】的 {image_type} 图片。", task_category=task_cat)
                continue

            image_url = image_info.get("url")
            if not image_url:
                ui_logger.warning(f"     - ⚠️ 警告: 远程备份中【{item_name}】的 {image_type} 图片记录缺少下载URL。", task_category=task_cat)
                continue

            try:
                # 应用图片下载冷却
                time.sleep(self.pm_config.image_download_cooldown_seconds)
                
                ui_logger.debug(f"     - 正在下载: {image_url}", task_category=task_cat)
                proxies = self.proxy_manager.get_proxies(image_url)
                image_response = self.session.get(image_url, timeout=60, proxies=proxies)
                image_response.raise_for_status()
                image_data = image_response.content
                
                # 准备上传到 Emby
                emby_image_type_map = {
                    "poster": "Primary",
                    "logo": "Logo",
                    "fanart": "Backdrop"
                }
                emby_image_type = emby_image_type_map.get(image_type)
                if not emby_image_type: continue

                upload_url = f"{self.config.server_config.server}/Items/{item_id}/Images/{emby_image_type}"
                
                # 删除旧图
                try:
                    delete_proxies = self.proxy_manager.get_proxies(upload_url)
                    self.session.delete(upload_url, params={"api_key": self.config.server_config.api_key}, timeout=20, proxies=delete_proxies)
                except requests.RequestException:
                    # 删除失败是正常情况（可能原本就没有图）
                    pass

                # 上传新图
                headers = {'Content-Type': image_response.headers.get('Content-Type', 'image/jpeg')}
                upload_proxies = self.proxy_manager.get_proxies(upload_url)
                upload_response = self.session.post(
                    upload_url, 
                    params={"api_key": self.config.server_config.api_key}, 
                    data=image_data, 
                    headers=headers, 
                    timeout=60,
                    proxies=upload_proxies
                )
                upload_response.raise_for_status()
                ui_logger.info(f"     - ✅ 成功恢复【{item_name}】的 {image_type} 图片。", task_category=task_cat)

            except Exception as e:
                ui_logger.error(f"     - ❌ 恢复【{item_name}】的 {image_type} 图片失败: {e}", task_category=task_cat)


    def start_restore_task(
        self,
        scope: ScheduledTasksTargetScope,
        content_types: List[str],
        cancellation_event: threading.Event,
        task_id: str,
        task_manager: TaskManager
    ):
        """从 GitHub 恢复图片到 Emby 的主任务流程"""
        task_cat = f"海报恢复({scope.mode})"
        ui_logger.info(f"🎉 任务启动，模式: {scope.mode}, 内容: {content_types}", task_category=task_cat)

        try:
            # 阶段一：预处理
            ui_logger.info("➡️ [阶段1/2] 正在获取远程索引和媒体列表...", task_category=task_cat)
            remote_map = self._get_aggregated_remote_index(task_cat)
            if not remote_map:
                raise ValueError("无法获取远程聚合索引，任务中止。")

            selector = MediaSelector(self.config)
            media_ids = selector.get_item_ids(scope)
            
            total_items = len(media_ids)
            task_manager.update_task_progress(task_id, 0, total_items)
            ui_logger.info(f"✅ [阶段1/2] 预处理完成，共需检查 {total_items} 个媒体项。", task_category=task_cat)
            
            # 阶段二：执行恢复
            ui_logger.info("➡️ [阶段2/2] 开始逐一恢复媒体项...", task_category=task_cat)
            
            # 批量获取TMDB ID
            tmdb_id_map = {}
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_id = {executor.submit(self._get_tmdb_id, item_id): item_id for item_id in media_ids}
                for future in future_to_id:
                    item_id = future_to_id[future]
                    try:
                        tmdb_id = future.result()
                        if tmdb_id:
                            tmdb_id_map[item_id] = tmdb_id
                    except Exception as e:
                        logging.error(f"【海报恢复】获取 TMDB ID 时出错 (Emby ID: {item_id}): {e}")

            for i, item_id in enumerate(media_ids):
                if cancellation_event.is_set():
                    ui_logger.warning("⚠️ 任务在执行阶段被取消。", task_category=task_cat)
                    return

                tmdb_id = tmdb_id_map.get(item_id)
                if not tmdb_id:
                    ui_logger.debug(f"  -> 跳过 Emby ID: {item_id}，因为它没有关联的 TMDB ID。", task_category=task_cat)
                else:
                    self._restore_single_item(item_id, tmdb_id, content_types, remote_map, task_cat)
                
                task_manager.update_task_progress(task_id, i + 1, total_items)

            ui_logger.info("🎉 恢复任务执行完毕。", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 恢复任务执行失败: {e}", task_category=task_cat, exc_info=True)
            raise e
        
    def get_stats(self) -> Dict:
        """获取状态仪表盘所需的数据"""
        total_images = 0
        total_size_bytes = 0
        repo_count = len(self.pm_config.github_repos)
        
        remote_map = self._get_aggregated_remote_index("状态获取")
        total_images = len(remote_map)
        
        type_counts = {"poster": 0, "logo": 0, "fanart": 0}
        for key, value in remote_map.items():
            total_size_bytes += value.get("size", 0)
            if "poster" in key: type_counts["poster"] += 1
            elif "logo" in key: type_counts["logo"] += 1
            elif "fanart" in key: type_counts["fanart"] += 1

        repo_details = []
        total_capacity_bytes = 0
        threshold_bytes = self.pm_config.repository_size_threshold_mb * 1024 * 1024
        
        for repo in self.pm_config.github_repos:
            match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", repo.repo_url)
            name = f"{match.group(1)}/{match.group(2)}" if match else repo.repo_url
            used_bytes = repo.state.size_kb * 1024
            repo_details.append({
                "name": name,
                "used_bytes": used_bytes,
                "threshold_bytes": threshold_bytes,
                "last_checked": repo.state.last_checked
            })
            total_capacity_bytes += threshold_bytes

        return {
            "total_images": total_images,
            "total_size_bytes": total_size_bytes,
            "repo_count": repo_count,
            "total_capacity_bytes": total_capacity_bytes,
            "type_counts": type_counts,
            "repo_details": repo_details
        }

    def get_single_item_details(self, item_id: str) -> Dict:
        """获取单个媒体项在 Emby 和 GitHub 两侧的图片详情"""
        # 1. 获取 Emby 侧信息
        emby_details = self._get_emby_item_details(item_id, "ImageTags,Name,ProductionYear,ProviderIds")
        emby_images = {}
        image_tags = emby_details.get("ImageTags", {})
        for img_type, emby_key in {"poster": "Primary", "logo": "Logo", "fanart": "Backdrop"}.items():
            if image_tags.get(emby_key):
                # 仅返回存在即可，具体URL由前端代理拼接
                emby_images[img_type] = {"url": f"/api/emby-image-proxy?path=Items/{item_id}/Images/{emby_key}"}
        
        # 2. 获取 GitHub 侧信息
        github_images = {}
        tmdb_id = emby_details.get("ProviderIds", {}).get("Tmdb")
        if tmdb_id:
            remote_map = self._get_aggregated_remote_index(f"单体查询({emby_details.get('Name')})")
            for img_type in ["poster", "logo", "fanart"]:
                key = f"{tmdb_id}-{img_type}"
                if key in remote_map:
                    github_images[img_type] = remote_map[key]

        return {
            "emby": emby_images,
            "github": github_images
        }

    def backup_single_image(self, item_id: str, image_type: str):
        """单体备份：从Emby下载图片，存入本地缓存，再上传到GitHub"""
        task_cat = f"单体备份({item_id}-{image_type})"
        ui_logger.info(f"➡️ 开始执行单体备份...", task_category=task_cat)
        
        # 1. 获取必要信息
        tmdb_id = self._get_tmdb_id(item_id)
        if not tmdb_id: raise ValueError("媒体项缺少 TMDB ID。")
        
        # 2. 从Emby下载图片
        emby_key = {"poster": "Primary", "logo": "Logo", "fanart": "Backdrop"}.get(image_type)
        emby_image_url = f"{self.config.server_config.server}/Items/{item_id}/Images/{emby_key}"
        proxies = self.proxy_manager.get_proxies(emby_image_url)
        response = self.session.get(emby_image_url, params={"api_key": self.config.server_config.api_key}, timeout=60, proxies=proxies)
        response.raise_for_status()
        image_data = response.content

        # 3. 写入本地缓存
        filename = {"poster": "poster.jpg", "logo": "clearlogo.png", "fanart": "fanart.jpg"}.get(image_type)
        local_dir = os.path.join(self.pm_config.local_cache_path, tmdb_id)
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, filename)
        with open(local_path, 'wb') as f:
            f.write(image_data)
        ui_logger.info(f"  - ✅ 图片已成功下载并覆盖本地缓存: {local_path}", task_category=task_cat)

        # 4. 执行上传（复用备份流程）
        item_info = {
            "local_path": local_path,
            "tmdb_id": tmdb_id,
            "image_type": image_type,
            "size": len(image_data)
        }
        remote_map = self._get_aggregated_remote_index(task_cat)
        new_files, overwrite_files = self._classify_pending_files([item_info], remote_map, task_cat)
        
        dispatch_plan = self._calculate_dispatch_plan(new_files, overwrite_files, task_cat)
        self._execute_dispatch_plan(dispatch_plan, task_cat, threading.Event())
        
        ui_logger.info(f"🎉 单体备份任务完成。", task_category=task_cat)

    def delete_single_image(self, item_id: str, image_type: str):
        """单体删除：从GitHub删除图片和索引条目"""
        task_cat = f"单体删除({item_id}-{image_type})"
        ui_logger.info(f"➡️ 开始执行单体删除...", task_category=task_cat)

        tmdb_id = self._get_tmdb_id(item_id)
        if not tmdb_id: raise ValueError("媒体项缺少 TMDB ID。")

        remote_map = self._get_aggregated_remote_index(task_cat)
        key = f"{tmdb_id}-{image_type}"
        image_info = remote_map.get(key)
        if not image_info: raise ValueError("在远程备份中未找到该图片。")

        repo_url = image_info['repo_url']
        sha = image_info['sha']
        
        repo_config = next((r for r in self.pm_config.github_repos if r.repo_url == repo_url), None)
        if not repo_config: raise ValueError(f"配置中找不到仓库 {repo_url}。")

        pat = repo_config.personal_access_token or self.pm_config.global_personal_access_token
        branch = repo_config.branch
        match = re.match(r"httpshttps?://github\.com/([^/]+)/([^/]+)", repo_url)
        owner, repo_name = match.groups()
        
        # 1. 删除文件
        filename = {"poster": "poster.jpg", "logo": "clearlogo.png", "fanart": "fanart.jpg"}.get(image_type)
        github_path = f"images/{tmdb_id}/{filename}"
        api_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{github_path}"
        delete_payload = {"message": f"refactor: Delete {github_path}", "sha": sha, "branch": branch}
        self._execute_github_write_request("DELETE", api_url, pat, delete_payload)
        ui_logger.info(f"  - ✅ 已成功从 GitHub 删除文件: {github_path}", task_category=task_cat)

        # 2. 更新索引
        index = self._get_repo_index(repo_config.model_dump())
        if str(tmdb_id) in index['images'] and image_type in index['images'][str(tmdb_id)]:
            del index['images'][str(tmdb_id)][image_type]
            if not index['images'][str(tmdb_id)]:
                del index['images'][str(tmdb_id)]
        
        index['last_updated'] = datetime.now().isoformat()
        index_api_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/database.json"
        get_index_resp = self.session.get(index_api_url, headers={"Authorization": f"token {pat}"}, proxies=self.proxy_manager.get_proxies(index_api_url)).json()
        index_sha = get_index_resp.get('sha')
        index_payload = {
            "message": "chore: Update index after deletion",
            "content": base64.b64encode(json.dumps(index, indent=2).encode()).decode(),
            "branch": branch,
            "sha": index_sha
        }
        self._execute_github_write_request("PUT", index_api_url, pat, index_payload)
        ui_logger.info(f"  - ✅ 索引文件 database.json 更新成功。", task_category=task_cat)

        # 3. 更新仓库大小
        latest_size_kb = self._get_latest_repo_size(repo_url, pat)
        current_config = app_config_module.load_app_config()
        for r in current_config.poster_manager_config.github_repos:
            if r.repo_url == repo_url:
                r.state.size_kb = latest_size_kb
                r.state.last_checked = datetime.now().isoformat()
                break
        app_config_module.save_app_config(current_config)
        ui_logger.info(f"  - ✅ 仓库 {repo_url} 最新容量 {latest_size_kb} KB 已回写配置。", task_category=task_cat)
        
        # 4. 清理聚合缓存
        if os.path.exists(AGGREGATED_INDEX_CACHE_FILE):
            os.remove(AGGREGATED_INDEX_CACHE_FILE)
            ui_logger.info(f"  - ✅ 本地聚合缓存已清理。", task_category=task_cat)

        ui_logger.info(f"🎉 单体删除任务完成。", task_category=task_cat)


    def start_backup_task(
        self,
        scope: ScheduledTasksTargetScope,
        content_types: List[str],
        overwrite: bool,
        cancellation_event: threading.Event,
        task_id: str,
        task_manager: TaskManager
    ):
        """从本地缓存备份到 GitHub 的主任务流程"""
        task_cat = f"海报备份({scope.mode})"
        ui_logger.info(f"🎉 任务启动，模式: {scope.mode}, 内容: {content_types}, 覆盖: {overwrite}", task_category=task_cat)

        try:
            # 阶段一：预处理
            selector = MediaSelector(self.config)
            media_ids = selector.get_item_ids(scope)
            task_manager.update_task_progress(task_id, 10, 100)
            if cancellation_event.is_set(): return

            initial_list = self._scan_local_cache(media_ids, content_types, task_cat)
            task_manager.update_task_progress(task_id, 25, 100)
            if cancellation_event.is_set(): return

            remote_map = self._get_aggregated_remote_index(task_cat)
            task_manager.update_task_progress(task_id, 40, 100)
            if cancellation_event.is_set(): return

            # 阶段二：分类
            new_files, overwrite_files = self._classify_pending_files(initial_list, remote_map, task_cat)
            task_manager.update_task_progress(task_id, 50, 100)
            if not new_files and not overwrite_files:
                ui_logger.info("✅ 所有文件均已是最新版本，无需备份。", task_category=task_cat)
                task_manager.update_task_progress(task_id, 100, 100)
                return

            # 阶段三：分发计划
            dispatch_plan = self._calculate_dispatch_plan(new_files, overwrite_files, task_cat)
            task_manager.update_task_progress(task_id, 60, 100)
            if cancellation_event.is_set(): return

            # 阶段四：执行
            self._execute_dispatch_plan(dispatch_plan, task_cat, cancellation_event)
            task_manager.update_task_progress(task_id, 100, 100)
            
            ui_logger.info("🎉 备份任务执行完毕。", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 备份任务执行失败: {e}", task_category=task_cat, exc_info=True)
            raise e