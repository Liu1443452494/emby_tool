
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

ACTOR_AVATAR_MAP_FILE = os.path.join('/app/data', 'actor_avatar_map.json')
ACTOR_AVATAR_MAP_LOCK_FILE = ACTOR_AVATAR_MAP_FILE + ".lock"
GITHUB_AVATAR_MAP_PATH = "database/actor_avatar_map.json"

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


    def save_avatar_choice_to_map(self, tmdb_person_id: int, image_info: Dict[str, Any]):
        """
        将用户的头像选择保存到本地的 JSON 映射文件中。
        这是一个核心的"记忆"功能。
        """
        task_cat = "演员头像映射-保存"
        ui_logger.debug(f"➡️ [调试-后端] 步骤8: 进入最终保存函数。接收到 tmdb_person_id: {tmdb_person_id}", task_category=task_cat)
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
        retry_delay = 5
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
            
            self._execute_github_write_request_with_retry("PUT", api_url, self.github_config.personal_access_token, payload, task_cat=task_cat)
            
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
        
    def restore_single_avatar_task(self, actor_info: Dict[str, Any], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """
        恢复单个演员的头像。
        优化版：利用 Emby 的 AnyProviderIdEquals 参数进行精准查找，无需扫描范围。
        """
        actor_name = actor_info.get("actor_name", "未知")
        tmdb_id_to_find = actor_info.get("tmdb_id")
        task_cat = f"演员头像映射-恢复-{actor_name}"

        if not tmdb_id_to_find:
            ui_logger.error(f"❌ 无法恢复演员【{actor_name}】，因为缺少 TMDB ID。", task_category=task_cat)
            return

        ui_logger.info(f"🎉 任务启动，准备为演员【{actor_name}】(TMDB ID: {tmdb_id_to_find})恢复头像...", task_category=task_cat)

        # 1. 精准查找 Emby 演员实体
        ui_logger.info("➡️ [阶段1/2] 正在向 Emby 查询该演员...", task_category=task_cat)
        try:
            url = f"{self.server_config.server}/Items"
            params = {
                "api_key": self.server_config.api_key,
                "Recursive": "true",
                "IncludeItemTypes": "Person",
                "AnyProviderIdEquals": f"tmdb.{tmdb_id_to_find}",
                "Fields": "Id,Name"
            }
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            items = data.get("Items", [])
            
            if not items:
                ui_logger.warning(f"⚠️ 在 Emby 中未找到 TMDB ID 为 {tmdb_id_to_find} 的演员，无法恢复。", task_category=task_cat)
                return
            
            emby_actor = items[0]
            emby_id = emby_actor['Id']
            ui_logger.info(f"   - ✅ 找到演员实体：{emby_actor.get('Name')} (Emby ID: {emby_id})", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 查询 Emby 失败: {e}", task_category=task_cat)
            return

        if cancellation_event.is_set(): return

        # 2. 执行恢复
        ui_logger.info("➡️ [阶段2/2] 开始上传图片...", task_category=task_cat)
        from actor_gallery_logic import ActorGalleryLogic
        from tmdb_logic import TMDB_IMAGE_BASE_URL, TMDB_IMAGE_SIZES

        gallery_logic = ActorGalleryLogic(self.config)
        
        image_source = actor_info.get("source")
        image_path = actor_info.get("image_path")

        if image_source == 'tmdb':
            image_url = f"{TMDB_IMAGE_BASE_URL}{TMDB_IMAGE_SIZES['original']}{image_path}"
        else:
            image_url = image_path

        if gallery_logic.upload_image_from_url(emby_id, image_url, source=image_source):
            ui_logger.info(f"🎉 成功为演员【{actor_name}】恢复了头像！", task_category=task_cat)
        else:
            ui_logger.error(f"❌ 为演员【{actor_name}】恢复头像失败。", task_category=task_cat)

    def restore_avatars_task(self, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager, cooldown: float = 0.0):
        """
        批量恢复演员头像。
        优化版：先一次性拉取 Emby 全量演员数据构建内存索引，再进行匹配恢复。
        """
        task_cat = "演员头像映射-批量恢复"
        ui_logger.info(f"🎉 任务启动，开始批量恢复演员头像 (极速模式)...", task_category=task_cat)
        if cooldown > 0:
            ui_logger.info(f"ℹ️ 已启用任务冷却，每个请求间隔 {cooldown} 秒。", task_category=task_cat)

        # 1. 加载本地映射表
        ui_logger.info("➡️ [阶段1/4] 正在加载本地头像映射表...", task_category=task_cat)
        if not os.path.exists(ACTOR_AVATAR_MAP_FILE):
            raise FileNotFoundError("本地演员头像映射表文件 actor_avatar_map.json 不存在。")
        
        with open(ACTOR_AVATAR_MAP_FILE, 'r', encoding='utf-8') as f:
            avatar_map = json.load(f)
        
        if not avatar_map:
            ui_logger.warning("⚠️ 本地头像映射表为空，任务中止。", task_category=task_cat)
            return
        
        ui_logger.info(f"   - 本地映射表共包含 {len(avatar_map)} 条记录。", task_category=task_cat)

        # 2. 构建内存索引
        ui_logger.info("➡️ [阶段2/4] 正在从 Emby 拉取全量演员数据以构建索引...", task_category=task_cat)
        tmdb_to_emby_map = {}
        try:
            start_time = time.time()
            url = f"{self.server_config.server}/Items"
            params = {
                "api_key": self.server_config.api_key,
                "Recursive": "true",
                "IncludeItemTypes": "Person",
                "Fields": "ProviderIds"
            }
            response = self.session.get(url, params=params, timeout=120) # 增加超时时间以应对大数据量
            response.raise_for_status()
            items = response.json().get("Items", [])
            
            for item in items:
                provider_ids = item.get("ProviderIds", {})
                # 查找 tmdb id (忽略大小写)
                tmdb_id = None
                for k, v in provider_ids.items():
                    if k.lower() == 'tmdb':
                        tmdb_id = str(v)
                        break
                
                if tmdb_id:
                    tmdb_to_emby_map[tmdb_id] = item['Id']
            
            duration = time.time() - start_time
            ui_logger.info(f"   - ✅ 索引构建完成！耗时 {duration:.2f} 秒。共获取 {len(items)} 个演员，其中 {len(tmdb_to_emby_map)} 个包含 TMDB ID。", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 拉取 Emby 数据失败: {e}", task_category=task_cat)
            return

        if cancellation_event.is_set(): return

        # 3. 匹配与恢复
        ui_logger.info("➡️ [阶段3/4] 开始匹配并恢复头像...", task_category=task_cat)
        
        from actor_gallery_logic import ActorGalleryLogic
        from tmdb_logic import TMDB_IMAGE_BASE_URL, TMDB_IMAGE_SIZES
        gallery_logic = ActorGalleryLogic(self.config)

        total_tasks = len(avatar_map)
        task_manager.update_task_progress(task_id, 0, total_tasks)
        
        success_count = 0
        skip_count = 0
        fail_count = 0
        processed_count = 0

        for tmdb_id, map_entry in avatar_map.items():
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务被用户取消。", task_category=task_cat)
                break

            processed_count += 1
            actor_name = map_entry.get("actor_name", "未知")

            # 检查该演员是否在当前 Emby 库中
            if tmdb_id not in tmdb_to_emby_map:
                # ui_logger.debug(f"   - [跳过] 演员【{actor_name}】(TMDB: {tmdb_id}) 不在当前 Emby 库中。", task_category=task_cat)
                skip_count += 1
                task_manager.update_task_progress(task_id, processed_count, total_tasks)
                continue

            emby_id = tmdb_to_emby_map[tmdb_id]
            image_source = map_entry.get("source")
            image_path = map_entry.get("image_path")

            if not image_source or not image_path:
                skip_count += 1
                continue

            if image_source == 'tmdb':
                image_url = f"{TMDB_IMAGE_BASE_URL}{TMDB_IMAGE_SIZES['original']}{image_path}"
            else:
                image_url = image_path
            
            try:
                if gallery_logic.upload_image_from_url(emby_id, image_url, source=image_source):
                    ui_logger.info(f"   - ✅ 恢复成功：{actor_name}", task_category=task_cat)
                    success_count += 1
                else:
                    ui_logger.error(f"   - ❌ 恢复失败：{actor_name}", task_category=task_cat)
                    fail_count += 1
                
                # 执行冷却
                if cooldown > 0:
                    time.sleep(cooldown)

            except Exception as e:
                ui_logger.error(f"   - ❌ 处理演员 {actor_name} 时出错: {e}", task_category=task_cat)
                fail_count += 1
            
            task_manager.update_task_progress(task_id, processed_count, total_tasks)

        ui_logger.info(f"🎉 批量恢复完成！成功: {success_count}, 跳过(不在库中): {skip_count}, 失败: {fail_count}。", task_category=task_cat)