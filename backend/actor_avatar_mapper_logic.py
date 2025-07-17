# backend/actor_avatar_mapper_logic.py (新文件)

import logging
import os
import json
import threading
import time
import re
import base64
import subprocess
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from filelock import FileLock, Timeout
from datetime import datetime

from log_manager import ui_logger
from models import AppConfig, ScheduledTasksTargetScope
from task_manager import TaskManager
from media_selector import MediaSelector
from proxy_manager import ProxyManager

# --- 新增常量 ---
ACTOR_AVATAR_MAP_FILE = os.path.join('/app/data', 'actor_avatar_map.json')
ACTOR_AVATAR_MAP_LOCK_FILE = ACTOR_AVATAR_MAP_FILE + ".lock"
GITHUB_AVATAR_MAP_PATH = "database/actor_avatar_map.json"
# --- 新增结束 ---

class ActorAvatarMapperLogic:
    def __init__(self, config: AppConfig):
        self.config = config
        self.server_config = config.server_config
        self.github_config = config.episode_refresher_config.github_config
        self.proxy_manager = ProxyManager(config)
        self.session = self._create_session()

    def _create_session(self):
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        session = requests.Session()
        retry_strategy = Retry(
            total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    # backend/actor_avatar_mapper_logic.py (函数替换)

    def save_avatar_choice_to_map(self, tmdb_person_id: int, image_info: Dict[str, Any]):
        """
        将用户的头像选择保存到本地的 JSON 映射文件中。
        这是一个核心的"记忆"功能。
        """
        task_cat = "演员头像映射-保存"
        # --- 新增 ---
        ui_logger.debug(f"➡️ [调试-后端] 步骤8: 进入最终保存函数。接收到 tmdb_person_id: {tmdb_person_id}", task_category=task_cat)
        # --- 新增结束 ---
        if not tmdb_person_id:
            ui_logger.warning("⚠️ 缺少 TMDB Person ID，无法保存头像选择。", task_category=task_cat)
            return

        ui_logger.info(f"➡️ 准备为演员 (TMDB ID: {tmdb_person_id}) 保存头像选择...", task_category=task_cat)
        
        try:
            with FileLock(ACTOR_AVATAR_MAP_LOCK_FILE, timeout=10):
                if os.path.exists(ACTOR_AVATAR_MAP_FILE):
                    with open(ACTOR_AVATAR_MAP_FILE, 'r', encoding='utf-8') as f:
                        full_map = json.load(f)
                else:
                    full_map = {}
                
                # 更新或创建条目
                full_map[str(tmdb_person_id)] = {
                    "actor_name": image_info.get("actor_name", "未知演员"),
                    "source": image_info.get("source"),
                    "image_path": image_info.get("image_path"),
                    "last_updated": datetime.utcnow().isoformat() + "Z"
                }

                with open(ACTOR_AVATAR_MAP_FILE, 'w', encoding='utf-8') as f:
                    json.dump(full_map, f, ensure_ascii=False, indent=2)
                
                ui_logger.info(f"✅ 成功为演员 (TMDB ID: {tmdb_person_id}) 更新了头像映射。", task_category=task_cat)

        except Timeout:
            ui_logger.error("❌ 更新映射文件失败：获取文件锁超时，另一个进程可能正在访问该文件。", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"❌ 更新映射文件时发生未知错误: {e}", task_category=task_cat, exc_info=True)

    def _get_github_api_url(self) -> str:
        """根据配置生成指向 actor_avatar_database.json 的 GitHub API URL"""
        match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", self.github_config.repo_url)
        if not match:
            raise ValueError("无效的 GitHub 仓库 URL。")
        owner, repo = match.groups()
        repo = repo.replace('.git', '')
        return f"https://api.github.com/repos/{owner}/{repo}/contents/{GITHUB_AVATAR_MAP_PATH}"

    def _github_request(self, method: str, url: str, **kwargs) -> Any:
        """通用的 GitHub API 请求函数"""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {self.github_config.personal_access_token}"
        }
        proxies = self.proxy_manager.get_proxies(url)
        response = self.session.request(method, url, headers=headers, timeout=30, proxies=proxies, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None
    
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

    def upload_to_github_task(self, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "演员头像映射-上传"
        ui_logger.info("🎉 任务启动，开始上传演员头像映射表到 GitHub...", task_category=task_cat)

        if not self.github_config.repo_url or not self.github_config.personal_access_token:
            raise ValueError("未配置 GitHub 仓库 URL 或个人访问令牌 (PAT)。")

        if not os.path.exists(ACTOR_AVATAR_MAP_FILE):
            raise FileNotFoundError("本地演员头像映射表文件 actor_avatar_map.json 不存在。")

        try:
            ui_logger.info("➡️ [阶段1/3] 正在读取本地文件...", task_category=task_cat)
            with open(ACTOR_AVATAR_MAP_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
            
            content_b64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            api_url = self._get_github_api_url()

            ui_logger.info("➡️ [阶段2/3] 正在检查远程文件状态...", task_category=task_cat)
            sha = None
            try:
                remote_file = self._github_request("GET", api_url)
                if remote_file:
                    sha = remote_file.get('sha')
                    ui_logger.info("  - 检测到远程文件已存在，将执行覆盖操作。", task_category=task_cat)
            except Exception:
                ui_logger.info("  - 远程文件不存在，将执行创建操作。", task_category=task_cat)

            if cancellation_event.is_set(): return

            ui_logger.info("➡️ [阶段3/3] 正在上传文件...", task_category=task_cat)
            payload = {
                "message": f"feat: Update actor avatar map ({time.strftime('%Y-%m-%d %H:%M:%S')})",
                "content": content_b64,
                "branch": self.github_config.branch
            }
            if sha:
                payload["sha"] = sha
            
            # --- 核心修改：调用新的基于 curl 的上传方法 ---
            self._execute_github_write_request_with_retry("PUT", api_url, self.github_config.personal_access_token, payload, task_cat=task_cat)
            # --- 修改结束 ---
            
            ui_logger.info("✅ 上传成功！演员头像映射表已同步到 GitHub 仓库。", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 上传到 GitHub 失败: {e}", task_category=task_cat, exc_info=True)
            raise e

    def download_from_github_task(self, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "演员头像映射-下载"
        ui_logger.info("🎉 任务启动，开始从 GitHub 下载演员头像映射表...", task_category=task_cat)

        if not self.github_config.repo_url:
            raise ValueError("未配置 GitHub 仓库 URL。")

        try:
            api_url = self._get_github_api_url()
            ui_logger.info("➡️ [阶段1/2] 正在下载远程文件...", task_category=task_cat)
            
            remote_file = self._github_request("GET", api_url)
            if not remote_file or 'content' not in remote_file:
                raise ValueError("从 GitHub 获取文件内容失败或文件为空。")

            content = base64.b64decode(remote_file['content']).decode('utf-8')

            if cancellation_event.is_set(): return

            ui_logger.info("➡️ [阶段2/2] 正在写入本地文件...", task_category=task_cat)
            try:
                with FileLock(ACTOR_AVATAR_MAP_LOCK_FILE, timeout=10):
                    with open(ACTOR_AVATAR_MAP_FILE, 'w', encoding='utf-8') as f:
                        f.write(content)
            except Timeout:
                raise IOError("获取文件锁超时，另一个进程可能正在访问该文件。")

            ui_logger.info("✅ 下载成功！本地演员头像映射表已更新为 GitHub 版本。", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 从 GitHub 下载失败: {e}", task_category=task_cat, exc_info=True)
            raise e
        
    def restore_single_avatar_task(self, actor_info: Dict[str, Any], scope: ScheduledTasksTargetScope, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """
        根据指定的演员信息和范围，恢复单个演员的头像。
        """
        actor_name = actor_info.get("actor_name", "未知")
        tmdb_id_to_find = actor_info.get("tmdb_id")
        task_cat = f"演员头像映射-恢复-{actor_name}"

        ui_logger.info(f"🎉 任务启动，准备为演员【{actor_name}】(TMDB ID: {tmdb_id_to_find})恢复头像...", task_category=task_cat)

        # 1. 获取范围内的所有演员
        ui_logger.info("➡️ [阶段1/3] 正在根据范围获取媒体列表...", task_category=task_cat)
        selector = MediaSelector(self.config)
        media_ids_in_scope = selector.get_item_ids(scope)
        if not media_ids_in_scope:
            ui_logger.warning("⚠️ 在指定范围内未找到任何媒体项，无法找到该演员。", task_category=task_cat)
            return

        ui_logger.info(f"➡️ [阶段2/3] 已获取 {len(media_ids_in_scope)} 个媒体项，开始并发查找演员...", task_category=task_cat)
        
        emby_actor_to_update = None
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_id = {executor.submit(selector._get_emby_item_details, item_id, "People"): item_id for item_id in media_ids_in_scope}
            for future in as_completed(future_to_id):
                if cancellation_event.is_set() or emby_actor_to_update:
                    break
                try:
                    people = future.result().get("People", [])
                    for person in people:
                        if person.get('Type') == 'Actor':
                            # 为每个演员获取其 ProviderIds
                            person_details = selector._get_emby_item_details(person['Id'], "ProviderIds")
                            provider_ids = person_details.get("ProviderIds", {})
                            provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
                            person_tmdb_id = provider_ids_lower.get("tmdb")
                            if str(person_tmdb_id) == str(tmdb_id_to_find):
                                emby_actor_to_update = person_details
                                ui_logger.info(f"   - ✅ 在媒体项 {future_to_id[future]} 中找到了目标演员【{actor_name}】(Emby ID: {emby_actor_to_update['Id']})。", task_category=task_cat)
                                break
                except Exception as e:
                    logging.error(f"【调试】查找演员时出错: {e}")
        
        if cancellation_event.is_set():
            ui_logger.warning("⚠️ 任务在查找演员阶段被用户取消。", task_category=task_cat)
            return

        if not emby_actor_to_update:
            ui_logger.error(f"❌ 在指定范围内未能找到 TMDB ID 为 {tmdb_id_to_find} 的演员【{actor_name}】。", task_category=task_cat)
            return

        # 3. 执行恢复
        ui_logger.info("➡️ [阶段3/3] 演员已定位，开始执行恢复...", task_category=task_cat)
        from actor_gallery_logic import ActorGalleryLogic
        from tmdb_logic import TMDB_IMAGE_BASE_URL, TMDB_IMAGE_SIZES

        gallery_logic = ActorGalleryLogic(self.config)
        
        image_source = actor_info.get("source")
        image_path = actor_info.get("image_path")

        if image_source == 'tmdb':
            image_url = f"{TMDB_IMAGE_BASE_URL}{TMDB_IMAGE_SIZES['original']}{image_path}"
        else:
            image_url = image_path

        if gallery_logic.upload_image_from_url(emby_actor_to_update['Id'], image_url, source=image_source):
            ui_logger.info(f"🎉 成功为演员【{actor_name}】恢复了头像！", task_category=task_cat)
        else:
            ui_logger.error(f"❌ 为演员【{actor_name}】恢复头像失败。", task_category=task_cat)

    def restore_avatars_task(self, scope: ScheduledTasksTargetScope, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "演员头像映射-批量恢复"
        ui_logger.info(f"🎉 任务启动，范围: {scope.mode}，开始批量恢复演员头像...", task_category=task_cat)

        # 1. 加载本地映射表
        ui_logger.info("➡️ [阶段1/5] 正在加载本地头像映射表...", task_category=task_cat)
        if not os.path.exists(ACTOR_AVATAR_MAP_FILE):
            raise FileNotFoundError("本地演员头像映射表文件 actor_avatar_map.json 不存在。")
        
        with open(ACTOR_AVATAR_MAP_FILE, 'r', encoding='utf-8') as f:
            avatar_map = json.load(f)
        
        if not avatar_map:
            ui_logger.warning("⚠️ 本地头像映射表为空，任务中止。", task_category=task_cat)
            return

        # 2. 获取目标媒体项
        ui_logger.info("➡️ [阶段2/5] 正在根据范围获取媒体列表...", task_category=task_cat)
        selector = MediaSelector(self.config)
        media_ids_in_scope = selector.get_item_ids(scope)
        if not media_ids_in_scope:
            ui_logger.info("✅ 在指定范围内未找到任何媒体项，任务完成。", task_category=task_cat)
            return

        # 3. 获取所有媒体项下的所有演员
        ui_logger.info(f"➡️ [阶段3/5] 已获取 {len(media_ids_in_scope)} 个媒体项，开始并发获取所有演员信息...", task_category=task_cat)
        
        all_actors_to_check = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_id = {executor.submit(selector._get_emby_item_details, item_id, "People"): item_id for item_id in media_ids_in_scope}
            for future in as_completed(future_to_id):
                if cancellation_event.is_set(): return
                try:
                    people = future.result().get("People", [])
                    actors = [p for p in people if p.get('Type') == 'Actor']
                    all_actors_to_check.extend(actors)
                except Exception as e:
                    logging.error(f"【调试】获取媒体 {future_to_id[future]} 的演员列表失败: {e}")

        unique_actors_base_info = {actor['Id']: actor for actor in all_actors_to_check}.values()
        ui_logger.info(f"   - 演员信息获取完毕，共找到 {len(unique_actors_base_info)} 个不重复的演员需要检查。", task_category=task_cat)

        ui_logger.info(f"➡️ [阶段4/5] 开始为 {len(unique_actors_base_info)} 个独立演员并发获取详细信息 (ProviderIds)...", task_category=task_cat)
        unique_actors_with_details = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_actor = {executor.submit(selector._get_emby_item_details, actor['Id'], "ProviderIds,Name"): actor for actor in unique_actors_base_info}
            for future in as_completed(future_to_actor):
                if cancellation_event.is_set(): return
                try:
                    full_actor_details = future.result()
                    unique_actors_with_details.append(full_actor_details)
                except Exception as e:
                    actor_info = future_to_actor[future]
                    logging.error(f"【调试】获取演员【{actor_info.get('Name')}】(ID: {actor_info.get('Id')})的详情失败: {e}")
        
        ui_logger.info(f"   - 演员详细信息获取完毕，共成功获取 {len(unique_actors_with_details)} 位演员的详情。", task_category=task_cat)

        # 5. 匹配并执行恢复
        ui_logger.info("➡️ [阶段5/5] 开始匹配映射表并恢复头像...", task_category=task_cat)
        total_actors = len(unique_actors_with_details)
        task_manager.update_task_progress(task_id, 0, total_actors)
        
        from actor_gallery_logic import ActorGalleryLogic
        from tmdb_logic import TMDB_IMAGE_BASE_URL, TMDB_IMAGE_SIZES

        gallery_logic = ActorGalleryLogic(self.config)
        updated_count = 0

        for i, actor in enumerate(unique_actors_with_details):
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务在恢复阶段被用户取消。", task_category=task_cat)
                return

            try:
                provider_ids = actor.get("ProviderIds", {})
                provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
                tmdb_id = provider_ids_lower.get("tmdb")
                
                if not tmdb_id:
                    continue

                if str(tmdb_id) in avatar_map:
                    map_entry = avatar_map[str(tmdb_id)]
                    actor_name = actor.get("Name")
                    ui_logger.info(f"  - [命中] 演员【{actor_name}】(TMDB ID: {tmdb_id}) 在映射表中，准备恢复...", task_category=task_cat)

                    image_source = map_entry.get("source")
                    image_path = map_entry.get("image_path")
                    
                    if not image_source or not image_path:
                        ui_logger.warning(f"    - [跳过] 演员【{actor_name}】的映射信息不完整。", task_category=task_cat)
                        continue

                    if image_source == 'tmdb':
                        image_url = f"{TMDB_IMAGE_BASE_URL}{TMDB_IMAGE_SIZES['original']}{image_path}"
                    else: # douban
                        image_url = image_path
                    
                    if gallery_logic.upload_image_from_url(actor['Id'], image_url, source=image_source):
                        ui_logger.info(f"    - ✅ 成功为演员【{actor_name}】恢复头像。", task_category=task_cat)
                        updated_count += 1
                    else:
                        ui_logger.error(f"    - ❌ 为演员【{actor_name}】恢复头像失败。", task_category=task_cat)
            except Exception as e:
                ui_logger.error(f"  - ❌ 处理演员 {actor.get('Name')} (ID: {actor.get('Id')}) 时发生错误: {e}", task_category=task_cat, exc_info=True)
            finally:
                task_manager.update_task_progress(task_id, i + 1, total_actors)
        
        ui_logger.info(f"🎉 批量恢复演员头像任务执行完毕，共成功恢复了 {updated_count} 个演员的头像。", task_category=task_cat)