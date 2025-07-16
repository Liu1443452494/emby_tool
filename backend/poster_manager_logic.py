

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
    
    def _get_emby_item_details(self, item_id: str, fields: str) -> Dict:
        """从 Emby 获取媒体项的详细信息"""
        import requests
        try:
            url = f"{self.config.server_config.server}/Users/{self.config.server_config.user_id}/Items/{item_id}"
            params = {"api_key": self.config.server_config.api_key, "Fields": fields}
            proxies = self.proxy_manager.get_proxies(url)
            response = self.session.get(url, params=params, timeout=15, proxies=proxies)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"【海报管理】获取媒体项 {item_id} 的详情失败: {e}")
            raise e

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

    def _get_aggregated_remote_index(self, task_cat: str, force_refresh: bool = False) -> Dict:
        """通过缓存或并发获取，得到聚合的所有远程文件索引"""
        ui_logger.info("➡️ [阶段1.3] 开始获取并聚合所有远程仓库的索引...", task_category=task_cat)
        
        lock_path = AGGREGATED_INDEX_CACHE_FILE + ".lock"
        

        should_write_cache = False

        if not force_refresh:
            try:
                with FileLock(lock_path, timeout=5):
                    if os.path.exists(AGGREGATED_INDEX_CACHE_FILE):
                        with open(AGGREGATED_INDEX_CACHE_FILE, 'r', encoding='utf-8') as f:
                            cache_data = json.load(f)
                        
                        cached_at = datetime.fromisoformat(cache_data.get("cached_at"))
                        now = datetime.now()
                        
                        if now - cached_at < timedelta(seconds=AGGREGATED_INDEX_CACHE_DURATION):
                            aggregated_index = cache_data.get("aggregated_index", {})
                            if aggregated_index:
                                age = now - cached_at
                                if age.total_seconds() < 60:
                                    age_str = f"{int(age.total_seconds())}秒前"
                                elif age.total_seconds() < 3600:
                                    age_str = f"{int(age.total_seconds() / 60)}分钟前"
                                else:
                                    age_str = f"{age.total_seconds() / 3600:.1f}小时前"
                                
                                ui_logger.info(f"✅ [阶段1.3] 命中本地聚合索引缓存 (更新于 {age_str})。", task_category=task_cat)
                                return aggregated_index
                            else:
                                ui_logger.warning("⚠️ 检测到有效的空缓存文件，可能由之前的网络问题导致，将强制刷新。", task_category=task_cat)
                                should_write_cache = True # 发现空缓存，标记需要重写
                        else:
                            should_write_cache = True # 缓存过期，标记需要重写
                    else:
                        should_write_cache = True # 缓存文件不存在，标记需要写入
            except (Timeout, IOError, json.JSONDecodeError) as e:
                ui_logger.warning(f"⚠️ 读取聚合缓存失败，将强制从网络获取。原因: {e}", task_category=task_cat)
                should_write_cache = True # 读取失败，标记需要重写
        else:
            ui_logger.info("   - [模式] 已启用强制刷新，将忽略本地缓存。", task_category=task_cat)
            should_write_cache = True # 强制刷新，标记需要重写

        remote_file_map = {}
        repos = self.pm_config.github_repos
        total_repos = len(repos)
        successful_fetches = 0
        repos_with_data_count = 0
        
        ui_logger.info(f"   - [模式] 缓存未命中或被强制刷新，正在从网络实时获取所有远程仓库的索引...", task_category=task_cat)
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_repo = {executor.submit(self._get_repo_index, repo.model_dump()): repo for repo in repos}
            for future in future_to_repo:
                repo_config = future_to_repo[future]
                try:
                    time.sleep(0.1)
                    index_content = future.result()
                    if index_content is not None:
                        successful_fetches += 1
                        if "images" in index_content and index_content["images"]:
                            repos_with_data_count += 1
                            for tmdb_id, images in index_content["images"].items():
                                for image_type, image_info in images.items():
                                    key = f"{tmdb_id}-{image_type}"
                                    remote_file_map[key] = image_info
                except Exception as e:
                    ui_logger.error(f"❌ 处理仓库 {repo_config.repo_url} 索引时出错: {e}", task_category=task_cat)


        if should_write_cache:
            total_records_aggregated = len(remote_file_map)
            log_message_prefix = "✅ [阶段5]" if force_refresh else "✅ [阶段1.3]"
            
            if successful_fetches == total_repos:
                try:
                    with FileLock(lock_path, timeout=10):
                        cache_content = {
                            "cached_at": datetime.now().isoformat(),
                            "aggregated_index": remote_file_map
                        }
                        with open(AGGREGATED_INDEX_CACHE_FILE, 'w', encoding='utf-8') as f:
                            json.dump(cache_content, f)
                    
                    if total_records_aggregated == 0:
                        ui_logger.info(f"{log_message_prefix} 成功检查所有({total_repos}/{total_repos})仓库，所有索引均为空。已写入一个空的聚合缓存文件。", task_category=task_cat)
                    else:
                        ui_logger.info(f"{log_message_prefix} 成功聚合所有({total_repos}/{total_repos})仓库的索引。共聚合来自 {repos_with_data_count} 个仓库的 {total_records_aggregated} 条记录，并已写入本地缓存。", task_category=task_cat)

                except Exception as e:
                    ui_logger.error(f"❌ {log_message_prefix} 写入聚合索引缓存失败: {e}", task_category=task_cat)
            else:
                ui_logger.warning(f"⚠️ {log_message_prefix} 未能成功获取所有仓库的索引({successful_fetches}/{total_repos})，聚合缓存更新失败。", task_category=task_cat)
        
        return remote_file_map

    def _classify_pending_files(self, initial_list: List[Dict], remote_map: Dict, overwrite: bool, task_cat: str) -> Tuple[List, List]:
        """将待办列表分为新增和覆盖两类"""
        ui_logger.info("➡️ [阶段2] 开始对待办文件进行分类 (新增/覆盖)...", task_category=task_cat)
        new_files = []
        overwrite_files = []

        skipped_count = 0
        
        for item in initial_list:
            key = f"{item['tmdb_id']}-{item['image_type']}"
            remote_info = remote_map.get(key)
            
            if not remote_info:
                new_files.append(item)
            elif overwrite:
                item['remote_info'] = remote_info
                overwrite_files.append(item)
            else:

                skipped_count += 1
        

        ui_logger.info(f"✅ [阶段2] 分类完成。新增: {len(new_files)} 项, 覆盖: {len(overwrite_files)} 项, 跳过: {skipped_count} 项。", task_category=task_cat)
        return new_files, overwrite_files



    def _calculate_dispatch_plan(self, new_files: List, overwrite_files: List, task_cat: str) -> Dict:
        """核心算法：计算文件分发计划 (打包分配 + 降级策略)"""
        ui_logger.info("➡️ [阶段3] 正在进行精确预计算，生成文件分发计划...", task_category=task_cat)
        
        dispatch_plan = {repo.repo_url: {"new": [], "overwrite": []} for repo in self.pm_config.github_repos}
        
        threshold_bytes = self.pm_config.repository_size_threshold_mb * 1024 * 1024
        temp_repo_states = {
            repo.repo_url: threshold_bytes - repo.state.size_bytes
            for repo in self.pm_config.github_repos
        }



        grouped_overwrite_files = {}
        for item in overwrite_files:
            key = (item['tmdb_id'], item['remote_info']['repo_url'])
            if key not in grouped_overwrite_files:
                grouped_overwrite_files[key] = {"files": [], "total_delta": 0}
            
            new_size = item['size']
            old_size = item['remote_info']['size']
            delta = new_size - old_size
            
            grouped_overwrite_files[key]["files"].append(item)
            grouped_overwrite_files[key]["total_delta"] += delta


        for (tmdb_id, repo_url), group in grouped_overwrite_files.items():
            total_delta = group['total_delta']
            
            if temp_repo_states.get(repo_url, -1) < total_delta:
                file_names = ', '.join([os.path.basename(f['local_path']) for f in group['files']])
                raise ValueError(f"文件覆盖失败：覆盖 TMDB ID {tmdb_id} 的文件 ({file_names}) 将导致仓库 {repo_url} 超出容量限制。")
            
            for item in group['files']:
                dispatch_plan[repo_url]["overwrite"].append(item)
            
            temp_repo_states[repo_url] -= total_delta
            
            file_names_str = ' '.join([os.path.basename(f['local_path']) for f in group['files']])
            ui_logger.info(f"  - [计划-覆盖] [{tmdb_id}] -({file_names_str})-> 分配至原仓库 {repo_url} (空间变化: {total_delta/1024/1024:+.2f} MB)", task_category=task_cat)



        grouped_new_files = {}
        for item in new_files:
            tmdb_id = item['tmdb_id']
            if tmdb_id not in grouped_new_files:
                grouped_new_files[tmdb_id] = {"files": [], "total_size": 0}
            grouped_new_files[tmdb_id]["files"].append(item)
            grouped_new_files[tmdb_id]["total_size"] += item['size']


        for tmdb_id, group in grouped_new_files.items():
            allocated_as_group = False

            for repo in self.pm_config.github_repos:
                if temp_repo_states.get(repo.repo_url, -1) >= group['total_size']:
                    for item in group['files']:
                        dispatch_plan[repo.repo_url]["new"].append(item)
                    temp_repo_states[repo.repo_url] -= group['total_size']
                    ui_logger.info(f"  - [计划-打包] [{tmdb_id}] 图片组 (共 {len(group['files'])} 项, {group['total_size']/1024/1024:.2f} MB) -> 分配至 {repo.repo_url}", task_category=task_cat)
                    allocated_as_group = True
                    break
            

            if not allocated_as_group:
                ui_logger.warning(f"  - ⚠️ [计划-降级] [{tmdb_id}] 图片组 (总大小 {group['total_size']/1024/1024:.2f} MB) 无法整体放入任何仓库，将尝试单独分配...", task_category=task_cat)
                for item in group['files']:
                    allocated_individually = False
                    for repo in self.pm_config.github_repos:
                        if temp_repo_states.get(repo.repo_url, -1) >= item['size']:
                            dispatch_plan[repo.repo_url]["new"].append(item)
                            temp_repo_states[repo.repo_url] -= item['size']
                            ui_logger.info(f"    - [计划-降级分配] {os.path.basename(item['local_path'])} ({item['size']/1024/1024:.2f} MB) -> 分配至 {repo.repo_url}", task_category=task_cat)
                            allocated_individually = True
                            break
                    if not allocated_individually:
                         raise ValueError(f"文件分配失败：文件 {item['local_path']} ({item['size']/1024/1024:.2f} MB) 过大，所有仓库均无足够空间容纳。")

        ui_logger.info("✅ [阶段3] 文件分发计划制定成功。", task_category=task_cat)
        return dispatch_plan

    def _execute_github_write_request(self, method: str, url: str, pat: str, payload: Optional[Dict] = None) -> Dict:
        """通过 curl 执行 GitHub 写入操作（无重试）"""
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

        command.append(url)

        result = subprocess.run(command, input=json_payload_str, capture_output=True, text=True, check=False)
        
        response_data = {}
        try:
            if result.stdout:
                response_data = json.loads(result.stdout)
        except json.JSONDecodeError:

            raise Exception(f"cURL 返回了非JSON响应: {result.stdout or '无输出'} | 错误: {result.stderr or '无错误信息'}")

        if result.returncode != 0 or (response_data.get("message") and response_data.get("documentation_url")):
            error_message = response_data.get('message', f"cURL 错误: {result.stderr}")
            if response_data.get('status') == '422' and "sha" in error_message:
                error_message = f"无效请求 (422)。服务器提示 'sha' 参数有问题。这可能是因为在您操作期间，文件被其他进程修改。请重试。({error_message})"
            elif "409 Conflict" in result.stderr:
                error_message = "GitHub API 返回 409 Conflict 错误，这通常是并发写入冲突导致的。请稍后重试。"

            elif "schannel: failed to receive handshake" in result.stderr or "curl: (35)" in result.stderr:
                error_message = f"SSL/TLS 握手失败。这通常是临时的网络或代理问题。错误: {result.stderr}"

            raise Exception(f"GitHub API 错误: {error_message}")

        return response_data
    
    def _execute_github_write_request_with_retry(self, method: str, url: str, pat: str, payload: Optional[Dict] = None, task_cat: str = "GitHub写入") -> Dict:
        """
        执行 GitHub 写入操作，并增加了针对网络错误的重试逻辑。
        """
        max_retries = 3
        retry_delay = 5  # seconds
        for attempt in range(max_retries):
            try:
                return self._execute_github_write_request(method, url, pat, payload)
            except Exception as e:

                error_str = str(e).lower()
                if "ssl/tls" in error_str or "handshake" in error_str or "curl: (35)" in error_str:
                    if attempt < max_retries - 1:
                        ui_logger.warning(f"  - ⚠️ 网络操作失败 (尝试 {attempt + 1}/{max_retries})，将在 {retry_delay} 秒后重试... 原因: {e}", task_category=task_cat)
                        time.sleep(retry_delay)
                        continue

                raise e

        raise Exception("重试逻辑执行完毕但未能成功。")


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



    def _execute_dispatch_plan(self, dispatch_plan: Dict, task_cat: str, cancellation_event: threading.Event):
        """执行文件上传和索引更新"""
        ui_logger.info("➡️ [阶段4] 开始执行文件上传和索引更新...", task_category=task_cat)
        

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
            match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", repo_url)
            owner, repo_name = match.groups()


            try:

                lock_path = ".lock"
                lock_api_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{lock_path}"
                lock_payload = {
                    "message": f"feat: Acquire lock for task",
                    "content": base64.b64encode(f"locked_at: {datetime.now().isoformat()}".encode()).decode(),
                    "branch": branch
                }
                self._execute_github_write_request_with_retry("PUT", lock_api_url, pat, lock_payload, task_cat=task_cat)
                ui_logger.info(f"    - 🔒 已成功在仓库 {repo_url} 中创建 .lock 文件。", task_category=task_cat)
            
            except Exception as e:
                if "422" in str(e) or "Unprocessable Entity" in str(e):
                    error_message = (
                        f"❌ 无法锁定仓库 {repo_url}，任务中止！\n"
                        f"    - **可能原因**: 上一次备份任务异常中断，导致 .lock 文件未能被自动删除。\n"
                        f"    - **修复建议**: 请手动前往该 GitHub 仓库，检查并删除根目录下的 `.lock` 文件后，再重新运行备份任务。\n"
                        f"    - **补充说明**: 如果您确认没有其他任务正在运行，删除 .lock 文件是安全的操作。重新运行一次完整的备份任务可以修复任何潜在的索引不一致问题。"
                    )
                    ui_logger.error(error_message, task_category=task_cat)

                    raise Exception(f"获取仓库 {repo_url} 的锁失败。")
                else:

                    raise e


            try:

                current_index = self._get_repo_index(repo_config.model_dump())
                if current_index is None:
                    raise Exception("获取最新索引失败，无法继续。")


                files_to_process = plan['overwrite'] + plan['new']
                for item in files_to_process:
                    if cancellation_event.is_set(): raise InterruptedError("任务被取消")
                    
                    action_type = '新增'
                    
                    cooldown = self.pm_config.file_upload_cooldown_seconds
                    if cooldown > 0:
                        ui_logger.info(f"    - ⏱️ 文件上传冷却 {cooldown} 秒...", task_category=task_cat)
                        time.sleep(cooldown)
                    
                    with open(item['local_path'], 'rb') as f:
                        content_b64 = base64.b64encode(f.read()).decode()
                    
                    github_path = f"images/{item['tmdb_id']}/{os.path.basename(item['local_path'])}"
                    api_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{github_path}"
                    
                    payload = {
                        "message": f"feat: Add/Update {item['image_type']} for {item['tmdb_id']}",
                        "content": content_b64,
                        "branch": branch
                    }

                    is_overwrite = 'remote_info' in item
                    if is_overwrite:
                        payload['sha'] = item['remote_info']['sha']
                        action_type = '覆盖'

                    try:
                        response_data = self._execute_github_write_request_with_retry("PUT", api_url, pat, payload, task_cat=task_cat)
                    except Exception as e:
                        if "422" in str(e) and not is_overwrite:
                            ui_logger.info(f"    - 🔄 文件 {github_path} 已存在，触发“新增转覆盖”容错机制...", task_category=task_cat)
                            action_type = '覆盖'
                            get_resp = self.session.get(api_url, headers={"Authorization": f"token {pat}"}, proxies=self.proxy_manager.get_proxies(api_url)).json()
                            payload['sha'] = get_resp['sha']
                            response_data = self._execute_github_write_request_with_retry("PUT", api_url, pat, payload, task_cat=task_cat)
                        else:
                            raise e
                    
                    if action_type == '覆盖':
                        ui_logger.info(f"    - ✅ 覆盖上传成功: {github_path}", task_category=task_cat)
                    else:
                        ui_logger.info(f"    - ⬆️ 新增上传成功: {github_path}", task_category=task_cat)


                    tmdb_id_str = str(item['tmdb_id'])
                    if tmdb_id_str not in current_index['images']:
                        current_index['images'][tmdb_id_str] = {}
                    
                    current_index['images'][tmdb_id_str][item['image_type']] = {
                        "repo_url": repo_url,
                        "sha": response_data['content']['sha'],
                        "size": response_data['content']['size'],
                        "url": response_data['content']['download_url']
                    }


                current_index['last_updated'] = datetime.now().isoformat()
                index_api_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/database.json"
                
                get_index_resp = self.session.get(index_api_url, headers={"Authorization": f"token {pat}"}, proxies=self.proxy_manager.get_proxies(index_api_url)).json()
                index_sha = get_index_resp.get('sha')

                index_payload = {
                    "message": f"chore: Update database index",
                    "content": base64.b64encode(json.dumps(current_index, indent=2).encode()).decode(),
                    "branch": branch
                }
                if index_sha:
                    index_payload['sha'] = index_sha
                
                self._execute_github_write_request_with_retry("PUT", index_api_url, pat, index_payload, task_cat=task_cat)
                ui_logger.info(f"    - 索引文件 database.json 更新成功。", task_category=task_cat)

            finally:

                lock_get_resp = self.session.get(lock_api_url, headers={"Authorization": f"token {pat}"}, proxies=self.proxy_manager.get_proxies(lock_api_url)).json()
                lock_sha = lock_get_resp.get('sha')
                if lock_sha:
                    delete_payload = {
                        "message": "feat: Release lock",
                        "sha": lock_sha,
                        "branch": branch
                    }
                    self._execute_github_write_request_with_retry("DELETE", lock_api_url, pat, delete_payload, task_cat=task_cat)
                    ui_logger.info(f"    - 🔓 已成功从仓库 {repo_url} 中移除 .lock 文件。", task_category=task_cat)

        ui_logger.info("✅ [阶段4] 所有文件上传和索引更新完成。", task_category=task_cat)

    def _update_all_repo_sizes(self, task_cat: str):
        """
        在任务结束后，根据最新的聚合索引，统一计算并回写所有仓库的容量状态。
        """
        ui_logger.info(f"➡️ [阶段5] 正在根据最新索引统一更新所有仓库的容量状态...", task_category=task_cat)
        
        if not os.path.exists(AGGREGATED_INDEX_CACHE_FILE):
            ui_logger.warning("⚠️ 未找到聚合索引缓存文件，跳过容量更新。", task_category=task_cat)
            return
        
        with open(AGGREGATED_INDEX_CACHE_FILE, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        aggregated_index = cache_data.get("aggregated_index", {})

        repo_sizes = {}
        for key, image_info in aggregated_index.items():
            repo_url = image_info.get("repo_url")
            size = image_info.get("size", 0)
            if repo_url:
                repo_sizes[repo_url] = repo_sizes.get(repo_url, 0) + size
        
        current_app_config = app_config_module.load_app_config()
        updated_repos = []
        for repo in current_app_config.poster_manager_config.github_repos:
            new_size_bytes = repo_sizes.get(repo.repo_url, 0)
            if repo.state.size_bytes != new_size_bytes:
                repo.state.size_bytes = new_size_bytes
                repo.state.last_checked = datetime.now().isoformat()
                updated_repos.append(repo)
        
        if updated_repos:
            app_config_module.save_app_config(current_app_config)
            self.pm_config = current_app_config.poster_manager_config
            for repo in updated_repos:
                match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", repo.repo_url)
                name = f"{match.group(1)}/{match.group(2)}" if match else repo.repo_url
                

                size_in_gb = repo.state.size_bytes / (1024 * 1024 * 1024)
                if size_in_gb >= 1:
                    ui_logger.info(f"   - [容量更新] 仓库 {name} 最新容量为 {size_in_gb:.2f} GB。", task_category=task_cat)
                else:
                    size_in_mb = repo.state.size_bytes / (1024 * 1024)
                    ui_logger.info(f"   - [容量更新] 仓库 {name} 最新容量为 {size_in_mb:.2f} MB。", task_category=task_cat)

        else:
            ui_logger.info("   - [容量更新] 所有仓库容量均无变化。", task_category=task_cat)

   
    # backend/poster_manager_logic.py (函数替换)

    # backend/poster_manager_logic.py (函数替换)

    def start_restore_from_remote_task(
        self,
        scope: ScheduledTasksTargetScope,
        content_types: List[str],
        cancellation_event: threading.Event,
        task_id: str,
        task_manager: TaskManager
    ):
        """从 GitHub 备份反向恢复图片到 Emby 的主任务流程 (已修复范围过滤)"""
        from concurrent.futures import as_completed
        
        overwrite = self.pm_config.overwrite_on_restore
        task_cat = "海报恢复(反向)"
        overwrite_text = "强制覆盖" if overwrite else "智能跳过"
        ui_logger.info(f"🎉 任务启动，模式: 从远程备份恢复, 范围: {scope.mode}, 内容: {content_types}, 策略: {overwrite_text}", task_category=task_cat)

        try:
            # 阶段一：获取远程数据和ID映射
            ui_logger.info("➡️ [阶段1/5] 正在获取远程索引和ID映射...", task_category=task_cat)
            remote_map = self._get_aggregated_remote_index(task_cat)
            if not remote_map:
                raise ValueError("无法获取远程聚合索引，任务中止。")

            id_map_file = os.path.join('/app/data', 'id_map.json')
            if not os.path.exists(id_map_file):
                raise ValueError("ID映射表 (id_map.json) 不存在，无法进行反向恢复。请先在“定时任务”页面生成映射表。")
            with open(id_map_file, 'r', encoding='utf-8') as f:
                id_map = json.load(f)

            # 阶段二：根据远程备份，构建初始的 Emby 媒体检查列表
            ui_logger.info("➡️ [阶段2/5] 正在根据远程备份构建初始检查列表...", task_category=task_cat)
            target_tmdb_ids = {
                key.split('-')[0] for key, value in remote_map.items()
                if any(f'-{ct}' in key for ct in content_types)
            }
            
            initial_emby_ids_to_check = set()
            for tmdb_id in target_tmdb_ids:
                if tmdb_id in id_map:
                    initial_emby_ids_to_check.update(id_map[tmdb_id])
            
            if not initial_emby_ids_to_check:
                ui_logger.info("✅ 远程备份中的所有媒体在您的 Emby 库中均未找到，任务完成。", task_category=task_cat)
                return

            ui_logger.info(f"   - 远程数据库包含 {len(target_tmdb_ids)} 个有备份的TMDB ID，对应到本地 Emby 库中的 {len(initial_emby_ids_to_check)} 个媒体实例。", task_category=task_cat)

            # 阶段三：根据用户指定的范围，过滤出最终要处理的媒体
            ui_logger.info("➡️ [阶段3/5] 正在根据用户指定的范围进行过滤...", task_category=task_cat)
            selector = MediaSelector(self.config)
            scoped_emby_ids = set(selector.get_item_ids(scope))
            
            final_item_ids_to_process = initial_emby_ids_to_check.intersection(scoped_emby_ids)

            if not final_item_ids_to_process:
                ui_logger.info("✅ 在指定范围内，没有找到与远程备份匹配的媒体，任务完成。", task_category=task_cat)
                return
            
            ui_logger.info(f"   - 过滤后，最终确定需要处理 {len(final_item_ids_to_process)} 个媒体实例。", task_category=task_cat)

            # 阶段四：构建恢复计划
            ui_logger.info(f"➡️ [阶段4/5] 正在检查目标媒体状态并构建恢复计划...", task_category=task_cat)
            restore_plan = []
            total_items_to_check = len(final_item_ids_to_process)
            task_manager.update_task_progress(task_id, 0, total_items_to_check)

            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_id = {executor.submit(self._get_emby_item_details, item_id, "Name,ImageTags,ProviderIds"): item_id for item_id in final_item_ids_to_process}
                for i, future in enumerate(as_completed(future_to_id)):
                    if cancellation_event.is_set():
                        ui_logger.warning("⚠️ 任务在构建计划阶段被取消。", task_category=task_cat)
                        return
                    
                    item_id = future_to_id[future]
                    try:
                        details = future.result()
                        item_name = details.get("Name", f"ID {item_id}")
                        image_tags = details.get("ImageTags", {})
                        tmdb_id = details.get("ProviderIds", {}).get("Tmdb")

                        if not tmdb_id:
                            ui_logger.debug(f"   - [跳过] 媒体【{item_name}】(Emby Item ID: {item_id}) 缺少 TMDB ID。", task_category=task_cat)
                            continue

                        for image_type in content_types:
                            remote_key = f"{tmdb_id}-{image_type}"
                            if remote_key not in remote_map:
                                continue

                            needs_restore = False
                            if overwrite:
                                needs_restore = True
                            else:
                                type_map = {"poster": "Primary", "logo": "Logo", "fanart": "Backdrop"}
                                if not image_tags.get(type_map.get(image_type)):
                                    needs_restore = True
                                else:
                                    ui_logger.info(f"   - [跳过] 媒体【{item_name}】(Emby Item ID: {item_id}) 已存在 {image_type} 图片。", task_category=task_cat)
                            
                            if needs_restore:
                                restore_plan.append({"item_id": item_id, "item_name": item_name, "image_type": image_type, "tmdb_id": tmdb_id})
                    except Exception as e:
                        ui_logger.error(f"   - ❌ 获取媒体 (Emby Item ID: {item_id}) 详情失败: {e}", task_category=task_cat)
                    finally:
                        task_manager.update_task_progress(task_id, i + 1, total_items_to_check)

            ui_logger.info(f"✅ 恢复计划构建完成，共需恢复 {len(restore_plan)} 张图片。", task_category=task_cat)

            # 阶段五：执行恢复
            ui_logger.info("➡️ [阶段5/5] 开始逐一执行恢复...", task_category=task_cat)
            total_to_restore = len(restore_plan)
            task_manager.update_task_progress(task_id, 0, total_to_restore)

            for i, plan_item in enumerate(restore_plan):
                if cancellation_event.is_set():
                    ui_logger.warning("⚠️ 任务在执行阶段被取消。", task_category=task_cat)
                    return
                
                item_id = plan_item["item_id"]
                item_name = plan_item["item_name"]
                image_type = plan_item["image_type"]
                tmdb_id = plan_item["tmdb_id"]
                
                ui_logger.info(f"  -> 正在为【{item_name}】(Emby Item ID: {item_id}) 恢复 {image_type}...", task_category=task_cat)
                try:
                    self._restore_single_image_from_plan(item_id, image_type, tmdb_id, remote_map, task_cat)
                    ui_logger.info(f"     - ✅ 成功恢复【{item_name}】(Emby Item ID: {item_id}) 的 {image_type} 图片。", task_category=task_cat)
                except Exception as e:
                    ui_logger.error(f"     - ❌ 恢复【{item_name}】(Emby Item ID: {item_id}) 的 {image_type} 图片失败: {e}", task_category=task_cat)

                task_manager.update_task_progress(task_id, i + 1, total_to_restore)

            ui_logger.info("🎉 恢复任务执行完毕。", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 恢复任务执行失败: {e}", task_category=task_cat, exc_info=True)
            raise e


    # backend/poster_manager_logic.py (函数替换)

    def _restore_single_image_from_plan(self, item_id: str, image_type: str, tmdb_id: str, remote_map: Dict, task_cat: str):
        """根据计划，恢复单张指定类型的图片"""
        import requests
        
        key = f"{tmdb_id}-{image_type}"
        image_info = remote_map.get(key)

        if not image_info:
            # --- 核心修改：修正日志打印中的变量位置 ---
            ui_logger.debug(f"     - 跳过: 在远程备份中未找到 TMDB ID {tmdb_id} 的 {image_type} 图片。", task_category=task_cat)
            return

        image_url = image_info.get("url")
        if not image_url:
            ui_logger.warning(f"     - ⚠️ 警告: 远程备份中 TMDB ID {tmdb_id} 的 {image_type} 图片记录缺少下载URL。", task_category=task_cat)
            return

        try:
            cooldown = self.pm_config.image_download_cooldown_seconds
            if cooldown > 0:
                ui_logger.info(f"     - ⏱️ 下载冷却 {cooldown} 秒...", task_category=task_cat)
                time.sleep(cooldown)
            
            ui_logger.debug(f"     - 正在下载: {image_url}", task_category=task_cat)
            proxies = self.proxy_manager.get_proxies(image_url)
            image_response = self.session.get(image_url, timeout=60, proxies=proxies)
            image_response.raise_for_status()
            image_data = image_response.content
            
            emby_image_type_map = {
                "poster": "Primary",
                "logo": "Logo",
                "fanart": "Backdrop"
            }
            emby_image_type = emby_image_type_map.get(image_type)
            if not emby_image_type: return

            upload_url = f"{self.config.server_config.server}/Items/{item_id}/Images/{emby_image_type}"
            
            try:
                delete_proxies = self.proxy_manager.get_proxies(upload_url)
                self.session.delete(upload_url, params={"api_key": self.config.server_config.api_key}, timeout=20, proxies=delete_proxies)
            except requests.RequestException:
                pass

            base64_encoded_data = base64.b64encode(image_data).decode('utf-8')
            headers = {'Content-Type': image_response.headers.get('Content-Type', 'image/jpeg')}
            upload_proxies = self.proxy_manager.get_proxies(upload_url)
            
            upload_response = self.session.post(
                upload_url, 
                params={"api_key": self.config.server_config.api_key}, 
                data=base64_encoded_data,
                headers=headers, 
                timeout=60,
                proxies=upload_proxies
            )
            upload_response.raise_for_status()
            

        except Exception as e:

            raise e


    def start_restore_task(
        self,
        scope: ScheduledTasksTargetScope,
        content_types: List[str],
        cancellation_event: threading.Event,
        task_id: str,
        task_manager: TaskManager
    ):
        """
        恢复任务的入口函数，根据配置分发到不同的执行流程。
        """
        if self.pm_config.restore_mode == 'from_remote':
            from concurrent.futures import as_completed
            # --- 核心修改：补上缺失的 task_manager 参数 ---
            self.start_restore_from_remote_task(scope, content_types, cancellation_event, task_id, task_manager)
            return
        # --- 修改结束 ---

        """从 GitHub 恢复图片到 Emby 的主任务流程 (标准模式)"""
        overwrite = self.pm_config.overwrite_on_restore
        task_cat = f"海报恢复({scope.mode})"
        overwrite_text = "强制覆盖" if overwrite else "智能跳过"
        ui_logger.info(f"🎉 任务启动，模式: 标准, 范围: {scope.mode}, 内容: {content_types}, 策略: {overwrite_text}", task_category=task_cat)

        try:
            # 阶段一：预处理
            ui_logger.info("➡️ [阶段1/3] 正在获取远程索引和媒体列表...", task_category=task_cat)
            remote_map = self._get_aggregated_remote_index(task_cat)
            if not remote_map:
                raise ValueError("无法获取远程聚合索引，任务中止。")

            selector = MediaSelector(self.config)
            media_ids = selector.get_item_ids(scope)
            
            # 阶段二：构建恢复计划
            ui_logger.info(f"➡️ [阶段2/3] 正在构建恢复计划...", task_category=task_cat)
            restore_plan = []
            skipped_for_no_backup = 0
            total_items_to_check = len(media_ids)
            task_manager.update_task_progress(task_id, 0, total_items_to_check)

            item_details_map = {}
            from concurrent.futures import as_completed
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_id = {executor.submit(self._get_emby_item_details, item_id, "Name,ImageTags,ProviderIds"): item_id for item_id in media_ids}
                for future in as_completed(future_to_id):
                    item_id = future_to_id[future]
                    try:
                        item_details_map[item_id] = future.result()
                    except Exception as e:
                        ui_logger.error(f"   - ❌ 获取媒体 {item_id} 详情失败: {e}", task_category=task_cat)

            for i, item_id in enumerate(media_ids):
                if cancellation_event.is_set():
                    ui_logger.warning("⚠️ 任务在构建计划阶段被取消。", task_category=task_cat)
                    return
                
                details = item_details_map.get(item_id)
                if not details:
                    task_manager.update_task_progress(task_id, i + 1, total_items_to_check)
                    continue

                item_name = details.get("Name", f"ID {item_id}")
                image_tags = details.get("ImageTags", {})
                tmdb_id = details.get("ProviderIds", {}).get("Tmdb")

                if not tmdb_id:
                    ui_logger.debug(f"   - [跳过] 媒体【{item_name}】缺少 TMDB ID。", task_category=task_cat)
                    task_manager.update_task_progress(task_id, i + 1, total_items_to_check)
                    continue

                for image_type in content_types:
                    remote_key = f"{tmdb_id}-{image_type}"
                    if remote_key not in remote_map:
                        skipped_for_no_backup += 1
                        continue
                    
                    needs_restore = False
                    if overwrite:
                        needs_restore = True
                    else:
                        type_map = {"poster": "Primary", "logo": "Logo", "fanart": "Backdrop"}
                        if not image_tags.get(type_map.get(image_type)):
                            needs_restore = True
                        else:
                            ui_logger.info(f"   - [跳过] 媒体【{item_name}】已存在 {image_type} 图片。", task_category=task_cat)
                    
                    if needs_restore:
                        restore_plan.append({"item_id": item_id, "item_name": item_name, "image_type": image_type, "tmdb_id": tmdb_id})
                
                task_manager.update_task_progress(task_id, i + 1, total_items_to_check)

            log_message = f"✅ 恢复计划构建完成，共需恢复 {len(restore_plan)} 张图片。"
            if skipped_for_no_backup > 0:
                log_message += f" (因远程无备份而跳过 {skipped_for_no_backup} 张)"
            ui_logger.info(log_message, task_category=task_cat)

            # 阶段三：执行恢复计划
            ui_logger.info("➡️ [阶段3/3] 开始逐一执行恢复...", task_category=task_cat)
            total_to_restore = len(restore_plan)
            task_manager.update_task_progress(task_id, 0, total_to_restore)

            for i, plan_item in enumerate(restore_plan):
                if cancellation_event.is_set():
                    ui_logger.warning("⚠️ 任务在执行阶段被取消。", task_category=task_cat)
                    return
                
                item_id = plan_item["item_id"]
                item_name = plan_item["item_name"]
                image_type = plan_item["image_type"]
                tmdb_id = plan_item["tmdb_id"]
                
                ui_logger.info(f"  -> 正在为【{item_name}】恢复 {image_type}...", task_category=task_cat)
                try:
                    self._restore_single_image_from_plan(item_id, image_type, tmdb_id, remote_map, task_cat)
                    ui_logger.info(f"     - ✅ 成功恢复【{item_name}】的 {image_type} 图片。", task_category=task_cat)
                except Exception as e:
                    ui_logger.error(f"     - ❌ 恢复【{item_name}】的 {image_type} 图片失败: {e}", task_category=task_cat)

                task_manager.update_task_progress(task_id, i + 1, total_to_restore)

            ui_logger.info("🎉 恢复任务执行完毕。", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 恢复任务执行失败: {e}", task_category=task_cat, exc_info=True)
            raise e
        

    # backend/poster_manager_logic.py (新增代码块)

    def start_restore_from_local_task(
        self,
        scope: ScheduledTasksTargetScope,
        content_types: List[str],
        overwrite: bool,
        cancellation_event: threading.Event,
        task_id: str,
        task_manager: TaskManager
    ):
        """从本地缓存恢复图片到 Emby 的主任务流程"""
        from concurrent.futures import as_completed
        
        task_cat = f"海报恢复(本地)"
        overwrite_text = "强制覆盖" if overwrite else "智能跳过"
        ui_logger.info(f"🎉 任务启动，模式: 从本地缓存恢复, 范围: {scope.mode}, 内容: {content_types}, 策略: {overwrite_text}", task_category=task_cat)

        try:
            # 阶段一：获取目标媒体
            ui_logger.info("➡️ [阶段1/4] 正在根据范围获取目标媒体...", task_category=task_cat)
            selector = MediaSelector(self.config)
            media_ids = selector.get_item_ids(scope)
            if not media_ids:
                ui_logger.info("✅ 在指定范围内未找到任何媒体项，任务完成。", task_category=task_cat)
                return

            # 阶段二：扫描本地缓存
            ui_logger.info("➡️ [阶段2/4] 正在扫描本地缓存目录...", task_category=task_cat)
            initial_pending_list = self._scan_local_cache(media_ids, content_types, task_cat)
            if not initial_pending_list:
                ui_logger.info("✅ 在本地缓存中未找到与目标媒体匹配的任何图片，任务完成。", task_category=task_cat)
                return

            # 阶段三：构建恢复计划
            ui_logger.info(f"➡️ [阶段3/4] 正在检查目标媒体状态并构建恢复计划...", task_category=task_cat)
            
            # 将待办列表按 emby_item_id 分组，以便批量获取详情
            emby_ids_to_check = {item['local_path'].split(os.sep)[-2] for item in initial_pending_list}
            
            tmdb_to_emby_map = {}
            for item_id in media_ids:
                tmdb_id = self._get_tmdb_id(item_id)
                if tmdb_id:
                    if tmdb_id not in tmdb_to_emby_map:
                        tmdb_to_emby_map[tmdb_id] = []
                    tmdb_to_emby_map[tmdb_id].append(item_id)

            emby_item_details_map = {}
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_id = {executor.submit(self._get_emby_item_details, item_id, "Name,ImageTags"): item_id for item_id in media_ids}
                for future in as_completed(future_to_id):
                    item_id = future_to_id[future]
                    try:
                        emby_item_details_map[item_id] = future.result()
                    except Exception as e:
                        ui_logger.error(f"   - ❌ 获取媒体 (Emby Item ID: {item_id}) 详情失败: {e}", task_category=task_cat)

            restore_plan = []
            for item in initial_pending_list:
                tmdb_id = item['tmdb_id']
                emby_ids = tmdb_to_emby_map.get(tmdb_id, [])
                for emby_id in emby_ids:
                    details = emby_item_details_map.get(emby_id)
                    if not details:
                        continue

                    image_tags = details.get("ImageTags", {})
                    item_name = details.get("Name", f"ID {emby_id}")
                    image_type = item['image_type']
                    
                    needs_restore = False
                    if overwrite:
                        needs_restore = True
                    else:
                        type_map = {"poster": "Primary", "logo": "Logo", "fanart": "Backdrop"}
                        if not image_tags.get(type_map.get(image_type)):
                            needs_restore = True
                        else:
                            ui_logger.info(f"   - [跳过] 媒体【{item_name}】(Emby Item ID: {emby_id}) 已存在 {image_type} 图片。", task_category=task_cat)
                    
                    if needs_restore:
                        restore_plan.append({
                            "item_id": emby_id,
                            "item_name": item_name,
                            "image_type": image_type,
                            "local_path": item['local_path']
                        })

            ui_logger.info(f"✅ 恢复计划构建完成，共需恢复 {len(restore_plan)} 张图片。", task_category=task_cat)

            # 阶段四：执行恢复
            ui_logger.info("➡️ [阶段4/4] 开始逐一执行恢复...", task_category=task_cat)
            total_to_restore = len(restore_plan)
            task_manager.update_task_progress(task_id, 0, total_to_restore)

            for i, plan_item in enumerate(restore_plan):
                if cancellation_event.is_set():
                    ui_logger.warning("⚠️ 任务在执行阶段被取消。", task_category=task_cat)
                    return
                
                item_id = plan_item["item_id"]
                item_name = plan_item["item_name"]
                image_type = plan_item["image_type"]
                local_path = plan_item["local_path"]
                
                ui_logger.info(f"  -> 正在为【{item_name}】(Emby Item ID: {item_id}) 从本地恢复 {image_type}...", task_category=task_cat)
                try:
                    self._restore_single_image_from_local(item_id, image_type, local_path)
                    ui_logger.info(f"     - ✅ 成功恢复【{item_name}】(Emby Item ID: {item_id}) 的 {image_type} 图片。", task_category=task_cat)
                except Exception as e:
                    ui_logger.error(f"     - ❌ 恢复【{item_name}】(Emby Item ID: {item_id}) 的 {image_type} 图片失败: {e}", task_category=task_cat)

                task_manager.update_task_progress(task_id, i + 1, total_to_restore)

            ui_logger.info("🎉 从本地缓存恢复任务执行完毕。", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 从本地缓存恢复任务执行失败: {e}", task_category=task_cat, exc_info=True)
            raise e

    def _restore_single_image_from_local(self, item_id: str, image_type: str, local_path: str):
        """从本地文件路径恢复单张图片到Emby"""
        import requests
        import mimetypes
        import base64

        if not os.path.exists(local_path):
            raise FileNotFoundError(f"本地文件不存在: {local_path}")

        with open(local_path, 'rb') as f:
            image_data = f.read()

        content_type, _ = mimetypes.guess_type(local_path)
        if not content_type:
            content_type = 'image/jpeg' if image_type in ['poster', 'fanart'] else 'image/png'

        emby_image_type_map = {
            "poster": "Primary",
            "logo": "Logo",
            "fanart": "Backdrop"
        }
        emby_image_type = emby_image_type_map.get(image_type)
        if not emby_image_type:
            return

        upload_url = f"{self.config.server_config.server}/Items/{item_id}/Images/{emby_image_type}"
        
        try:
            delete_proxies = self.proxy_manager.get_proxies(upload_url)
            self.session.delete(upload_url, params={"api_key": self.config.server_config.api_key}, timeout=20, proxies=delete_proxies)
        except requests.RequestException:
            pass

        base64_encoded_data = base64.b64encode(image_data).decode('utf-8')
        headers = {'Content-Type': content_type}
        upload_proxies = self.proxy_manager.get_proxies(upload_url)
        
        upload_response = self.session.post(
            upload_url, 
            params={"api_key": self.config.server_config.api_key}, 
            data=base64_encoded_data,
            headers=headers, 
            timeout=60,
            proxies=upload_proxies
        )
        upload_response.raise_for_status()
        

    def get_stats(self, force_refresh: bool = False) -> Dict:
        """获取状态仪表盘所需的数据"""
        repo_count = len(self.pm_config.github_repos)
        

        remote_map = self._get_aggregated_remote_index("状态获取", force_refresh=force_refresh)
        

        if force_refresh:
            self._update_all_repo_sizes("状态获取")

        total_images = len(remote_map)
        total_size_bytes = 0
        type_counts = {"poster": 0, "logo": 0, "fanart": 0}
        for key, value in remote_map.items():
            total_size_bytes += value.get("size", 0)
            if "poster" in key: type_counts["poster"] += 1
            elif "logo" in key: type_counts["logo"] += 1
            elif "fanart" in key: type_counts["fanart"] += 1

        repo_details = []
        total_capacity_bytes = 0
        threshold_bytes = self.pm_config.repository_size_threshold_mb * 1024 * 1024
        

        current_config = app_config_module.load_app_config()
        
        for repo in current_config.poster_manager_config.github_repos:
            match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", repo.repo_url)
            name = f"{match.group(1)}/{match.group(2)}" if match else repo.repo_url
            used_bytes = repo.state.size_bytes
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

    def _get_emby_image_details(self, item_id: str) -> Dict[str, Dict]:
        """
        一次性获取 Emby 媒体项所有类型图片（海报、Logo、背景图）的详细信息。
        返回一个以图片类型为键的字典。
        """
        import requests
        from urllib.parse import quote, urlencode
        
        task_cat = f"海报管理-调试({item_id})"
        emby_images = {}
        api_key = self.config.server_config.api_key

        try:
            url = f"{self.config.server_config.server}/Items/{item_id}/Images"
            params = {"api_key": api_key}
            proxies = self.proxy_manager.get_proxies(url)
            
            ui_logger.debug(f"➡️ [调试] 正在请求图片元数据: {url}", task_category=task_cat)
            response = self.session.get(url, params=params, timeout=15, proxies=proxies)
            response.raise_for_status()
            
            all_image_metadata = response.json()
            if not all_image_metadata:
                ui_logger.debug(f"   - [调试] 未找到任何图片元数据。", task_category=task_cat)
                return {}

            ui_logger.debug(f"   - [调试] 成功获取到 {len(all_image_metadata)} 条图片元数据。", task_category=task_cat)

            for image_info in all_image_metadata:
                image_type_from_api = image_info.get("ImageType")
                
                type_map = {
                    "Primary": "poster",
                    "Logo": "logo",
                    "Backdrop": "fanart"
                }
                standard_type = type_map.get(image_type_from_api)
                
                if not standard_type:
                    continue

                image_tag = image_info.get("ImageTag")
                base_path = f"Items/{item_id}/Images/{image_type_from_api}"
                

                query_params = {
                    'api_key': api_key,
                    'quality': 100  # 请求最高质量的图片
                }
                if image_tag:
                    query_params['tag'] = image_tag

                
                image_path_to_emby = f"{base_path}?{urlencode(query_params)}"
                
                proxy_url = f"/api/emby-image-proxy?path={quote(image_path_to_emby)}"
                
                ui_logger.debug(f"   - [调试] 为类型 '{standard_type}' 生成的代理 URL: {proxy_url}", task_category=task_cat)

                width = image_info.get('Width', 0)
                height = image_info.get('Height', 0)
                size_bytes = image_info.get('Size', 0)
                
                resolution = f"{width}x{height}" if width and height else "未知分辨率"
                size_str = f"{size_bytes / 1024 / 1024:.2f} MB" if size_bytes > 1024 * 1024 else f"{size_bytes / 1024:.1f} KB"

                emby_images[standard_type] = {
                    "url": proxy_url,
                    "resolution": resolution,
                    "size": size_str
                }
            
            return emby_images

        except requests.RequestException as e:
            ui_logger.error(f"❌ [调试] 获取 Emby 图片元数据列表失败: {e}", task_category=task_cat)
            return {}
        except Exception as e:
            ui_logger.error(f"❌ [调试] 处理 Emby 图片元数据时发生未知错误: {e}", task_category=task_cat, exc_info=True)
            return {}
    def get_single_item_details(self, item_id: str) -> Dict:
        """获取单个媒体项在 Emby 和 GitHub 两侧的图片详情"""

        emby_details = self._get_emby_item_details(item_id, "Name,ProductionYear,ProviderIds")
        emby_images = self._get_emby_image_details(item_id)
        

        github_images = {}
        tmdb_id = emby_details.get("ProviderIds", {}).get("Tmdb")
        if tmdb_id:
            remote_map = self._get_aggregated_remote_index(f"单体查询({emby_details.get('Name')})")
            for img_type in ["poster", "logo", "fanart"]:
                key = f"{tmdb_id}-{img_type}"
                if key in remote_map:
                    gh_info = remote_map[key]
                    size_bytes = gh_info.get("size", 0)
                    github_images[img_type] = {
                        "url": gh_info.get("url"),
                        "resolution": "未知分辨率",
                        "size": f"{size_bytes / 1024 / 1024:.2f} MB" if size_bytes > 1024 * 1024 else f"{size_bytes / 1024:.1f} KB"
                    }

        return {
            "emby": emby_images,
            "github": github_images
        }



    def backup_single_image(self, item_id: str, image_type: str):
        """单体备份：从Emby下载图片，存入本地缓存，再上传到GitHub"""
        item_details = self._get_emby_item_details(item_id, "Name,ProviderIds")
        item_name = item_details.get("Name", f"ID {item_id}")
        image_type_map = {"poster": "海报", "logo": "Logo", "fanart": "背景图"}
        image_type_cn = image_type_map.get(image_type, image_type)
        
        task_cat = f"单体备份-{item_name}"
        ui_logger.info(f"➡️ 开始为【{item_name}】执行单体备份 ({image_type_cn})...", task_category=task_cat)
        
        tmdb_id = item_details.get("ProviderIds", {}).get("Tmdb")
        if not tmdb_id: raise ValueError("媒体项缺少 TMDB ID。")
        
        emby_key = {"poster": "Primary", "logo": "Logo", "fanart": "Backdrop"}.get(image_type)
        emby_image_url = f"{self.config.server_config.server}/Items/{item_id}/Images/{emby_key}"
        proxies = self.proxy_manager.get_proxies(emby_image_url)
        response = self.session.get(emby_image_url, params={"api_key": self.config.server_config.api_key}, timeout=60, proxies=proxies)
        response.raise_for_status()
        image_data = response.content

        filename = {"poster": "poster.jpg", "logo": "clearlogo.png", "fanart": "fanart.jpg"}.get(image_type)
        local_dir = os.path.join(self.pm_config.local_cache_path, tmdb_id)
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, filename)
        with open(local_path, 'wb') as f:
            f.write(image_data)
        ui_logger.info(f"  - ✅ 图片已成功下载并覆盖本地缓存: {local_path}", task_category=task_cat)

        item_info = {
            "local_path": local_path,
            "tmdb_id": tmdb_id,
            "image_type": image_type,
            "size": len(image_data)
        }
        remote_map = self._get_aggregated_remote_index(task_cat)
        
        overwrite_remote = True 
        new_files, overwrite_files = self._classify_pending_files([item_info], remote_map, overwrite_remote, task_cat)
        
        dispatch_plan = self._calculate_dispatch_plan(new_files, overwrite_files, task_cat)
        self._execute_dispatch_plan(dispatch_plan, task_cat, threading.Event())
        

        self._get_aggregated_remote_index(task_cat, force_refresh=True)
        
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
        match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", repo_url)
        if not match:
            raise ValueError(f"无法从仓库URL中解析出 owner 和 repo: {repo_url}")
        owner, repo_name = match.groups()
        
        filename = {"poster": "poster.jpg", "logo": "clearlogo.png", "fanart": "fanart.jpg"}.get(image_type)
        github_path = f"images/{tmdb_id}/{filename}"
        api_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{github_path}"
        delete_payload = {"message": f"refactor: Delete {github_path}", "sha": sha, "branch": branch}
        self._execute_github_write_request("DELETE", api_url, pat, delete_payload)
        ui_logger.info(f"  - ✅ 已成功从 GitHub 删除文件: {github_path}", task_category=task_cat)

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


        self._update_all_repo_sizes(task_cat)
        self._get_aggregated_remote_index(task_cat, force_refresh=True)

        ui_logger.info(f"🎉 单体删除任务完成。", task_category=task_cat)



    def restore_single_image(self, item_id: str, image_type: str):
        """单体恢复：从GitHub下载图片，并恢复到Emby"""
        item_details = self._get_emby_item_details(item_id, "Name,ProviderIds")
        item_name = item_details.get("Name", f"ID {item_id}")
        image_type_map = {"poster": "海报", "logo": "Logo", "fanart": "背景图"}
        image_type_cn = image_type_map.get(image_type, image_type)

        task_cat = f"单体恢复-{item_name}"
        ui_logger.info(f"➡️ 开始为【{item_name}】恢复【{image_type_cn}】...", task_category=task_cat)

        try:
            tmdb_id = item_details.get("ProviderIds", {}).get("Tmdb")
            if not tmdb_id:
                raise ValueError("媒体项缺少 TMDB ID，无法进行恢复。")

            remote_map = self._get_aggregated_remote_index(task_cat)
            
            # --- 核心修改：确保传递给 image_type 的是字符串，而不是列表 ---
            self._restore_single_image_from_plan(item_id, image_type, tmdb_id, remote_map, task_cat)
            
            ui_logger.info(f"🎉 为【{item_name}】恢复【{image_type_cn}】的任务已完成。", task_category=task_cat)
        
        except Exception as e:

            ui_logger.error(f"❌ 为【{item_name}】恢复【{image_type_cn}】的任务失败。", task_category=task_cat)
            raise e



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

            selector = MediaSelector(self.config)
            media_ids = selector.get_item_ids(scope)
            task_manager.update_task_progress(task_id, 10, 100)
            if cancellation_event.is_set(): return

            initial_list = self._scan_local_cache(media_ids, content_types, task_cat)
            task_manager.update_task_progress(task_id, 25, 100)
            if cancellation_event.is_set(): return

            remote_map = self._get_aggregated_remote_index(task_cat, force_refresh=False)
            task_manager.update_task_progress(task_id, 40, 100)
            if cancellation_event.is_set(): return


            new_files, overwrite_files = self._classify_pending_files(initial_list, remote_map, overwrite, task_cat)
            task_manager.update_task_progress(task_id, 50, 100)
            if not new_files and not overwrite_files:
                ui_logger.info("✅ 所有文件均已是最新版本，无需备份。", task_category=task_cat)
                task_manager.update_task_progress(task_id, 100, 100)
                return


            dispatch_plan = self._calculate_dispatch_plan(new_files, overwrite_files, task_cat)
            task_manager.update_task_progress(task_id, 60, 100)
            if cancellation_event.is_set(): return


            self._execute_dispatch_plan(dispatch_plan, task_cat, cancellation_event)
            

            if not cancellation_event.is_set():

                self._get_aggregated_remote_index(task_cat, force_refresh=True)

                self._update_all_repo_sizes(task_cat)

            task_manager.update_task_progress(task_id, 100, 100)
            
            ui_logger.info("🎉 备份任务执行完毕。", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 备份任务执行失败: {e}", task_category=task_cat, exc_info=True)
            raise e