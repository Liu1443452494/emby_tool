# backend/actor_role_mapper_logic.py (新文件)

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

from log_manager import ui_logger
from models import AppConfig, ScheduledTasksTargetScope
from task_manager import TaskManager
from media_selector import MediaSelector
from proxy_manager import ProxyManager

ACTOR_ROLE_MAP_FILE = os.path.join('/app/data', 'actor_role_map.json')
ACTOR_ROLE_MAP_LOCK_FILE = ACTOR_ROLE_MAP_FILE + ".lock"
GITHUB_MAP_PATH = "database/actor_role_map.json"

class ActorRoleMapperLogic:
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

    def _get_emby_item_details(self, item_id: str, fields: str) -> Dict:
        url = f"{self.server_config.server}/Users/{self.server_config.user_id}/Items/{item_id}"
        params = {"api_key": self.server_config.api_key, "Fields": fields}
        proxies = self.proxy_manager.get_proxies(url)
        response = self.session.get(url, params=params, timeout=20, proxies=proxies)
        response.raise_for_status()
        return response.json()

    def generate_map_task(self, scope: ScheduledTasksTargetScope, actor_limit: int, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "演员角色映射-生成"
        ui_logger.info(f"🎉 任务启动，范围: {scope.mode}，演员上限: {actor_limit}", task_category=task_cat)

        try:
            ui_logger.info("➡️ [阶段1/5] 正在获取媒体列表...", task_category=task_cat)
            selector = MediaSelector(self.config)
            media_ids = selector.get_item_ids(scope)
            if not media_ids:
                ui_logger.info("✅ 在指定范围内未找到任何媒体项，任务完成。", task_category=task_cat)
                return

            total_items = len(media_ids)
            task_manager.update_task_progress(task_id, 0, total_items)
            ui_logger.info(f"🔍 已获取 {total_items} 个媒体项，开始并发处理...", task_category=task_cat)

            actor_role_map = {}
            processed_count = 0

            with ThreadPoolExecutor(max_workers=10) as executor:
                ui_logger.info("➡️ [阶段2/5] 正在并发获取每个媒体项的基础详情...", task_category=task_cat)
                future_to_id = {executor.submit(self._get_emby_item_details, item_id, "ProviderIds,People,Name"): item_id for item_id in media_ids}
                
                all_people_to_fetch_details = []
                media_details_map = {}

                for future in as_completed(future_to_id):
                    if cancellation_event.is_set(): return
                    item_id = future_to_id[future]
                    try:
                        details = future.result()
                        media_details_map[item_id] = details
                        
                        people = details.get("People", [])
                        if people:
                            actors = [p for p in people if p.get('Type') == 'Actor']
                            others = [p for p in people if p.get('Type') != 'Actor']
                            
                            limited_actors = actors[:actor_limit]
                            if len(actors) > len(limited_actors):
                                ui_logger.debug(f"  - [演员裁切] 媒体【{details.get('Name')}】演员总数: {len(actors)}，根据设置将处理前 {len(limited_actors)} 位。", task_category=task_cat)
                            
                            people_to_process = limited_actors + others
                            all_people_to_fetch_details.extend(people_to_process)

                    except Exception as e:
                        ui_logger.error(f"   - ❌ 获取媒体 {item_id} 基础详情时出错: {e}", task_category=task_cat)

                if cancellation_event.is_set(): return
                
                unique_people_ids = {person['Id'] for person in all_people_to_fetch_details if person.get('Id')}
                ui_logger.info(f"➡️ [阶段3/5] 媒体详情获取完毕，开始为 {len(unique_people_ids)} 个唯一演员并发获取 ProviderIds...", task_category=task_cat)
                
                person_details_map = {}
                future_to_person_id = {executor.submit(self._get_emby_item_details, person_id, "ProviderIds"): person_id for person_id in unique_people_ids}

                for future in as_completed(future_to_person_id):
                    if cancellation_event.is_set(): return
                    person_id = future_to_person_id[future]
                    try:
                        person_details_map[person_id] = future.result()
                    except Exception as e:
                        logging.debug(f"【调试】获取演员 {person_id} 的 ProviderIds 失败: {e}")

                if cancellation_event.is_set(): return

                ui_logger.info("➡️ [阶段4/5] 开始构建最终映射表...", task_category=task_cat)
                for item_id, details in media_details_map.items():
                    item_name = details.get("Name", f"ID {item_id}")
                    tmdb_id = details.get("ProviderIds", {}).get("Tmdb")
                    
                    people = details.get("People", [])
                    actors = [p for p in people if p.get('Type') == 'Actor']
                    others = [p for p in people if p.get('Type') != 'Actor']
                    people_to_process = actors[:actor_limit] + others

                    if not tmdb_id:
                        ui_logger.debug(f"  - [跳过] 媒体【{item_name}】缺少 TMDB ID。", task_category=task_cat)
                        continue
                    
                    if tmdb_id in actor_role_map:
                        if item_id not in actor_role_map[tmdb_id]["Emby_itemid"]:
                            actor_role_map[tmdb_id]["Emby_itemid"].append(item_id)
                        processed_count += 1
                        task_manager.update_task_progress(task_id, processed_count, total_items)
                        continue
                    
                    if not people_to_process:
                        continue

                    # --- 核心修改：将 work_map 改为 work_list (数组) ---
                    work_list = []
                    for person in people_to_process:
                        if person.get('Type') != 'Actor':
                            continue
                        
                        actor_name = person.get("Name")
                        if not actor_name:
                            continue

                        person_full_details = person_details_map.get(person.get("Id"))
                        person_tmdb_id = None
                        if person_full_details:
                            provider_ids = person_full_details.get("ProviderIds", {})
                            provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
                            person_tmdb_id = provider_ids_lower.get("tmdb")
                        
                        role = person.get("Role", "")
                        logging.debug(f"【调试-最终数据】演员: {actor_name}, 角色: {role}, TMDB ID: {person_tmdb_id}")

                        work_list.append({
                            "name": actor_name,
                            "tmdb_id": person_tmdb_id,
                            "role": role
                        })
                    
                    if work_list:
                        actor_role_map[tmdb_id] = {
                            "title": item_name,
                            "Emby_itemid": [item_id],
                            "map": work_list # 使用新的数组结构
                        }
                    # --- 修改结束 ---
                    
                    processed_count += 1
                    task_manager.update_task_progress(task_id, processed_count, total_items)

            ui_logger.info("➡️ [阶段5/5] 正在写入本地文件...", task_category=task_cat)
            try:
                with FileLock(ACTOR_ROLE_MAP_LOCK_FILE, timeout=10):
                    with open(ACTOR_ROLE_MAP_FILE, 'w', encoding='utf-8') as f:
                        json.dump(actor_role_map, f, ensure_ascii=False)
            except Timeout:
                raise IOError("获取文件锁超时，另一个进程可能正在访问该文件。")

            total_works = len(actor_role_map)
            total_actors = sum(len(work['map']) for work in actor_role_map.values())
            ui_logger.info(f"✅ 映射表生成完毕！共记录 {total_works} 部作品，{total_actors} 条演员角色关系。", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 生成映射表任务失败: {e}", task_category=task_cat, exc_info=True)
            raise e

    def _get_github_api_url(self) -> str:
        match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", self.github_config.repo_url)
        if not match:
            raise ValueError("无效的 GitHub 仓库 URL。")
        owner, repo = match.groups()
        repo = repo.replace('.git', '')
        return f"https://api.github.com/repos/{owner}/{repo}/contents/{GITHUB_MAP_PATH}"

    def _github_request(self, method: str, url: str, **kwargs) -> Any:
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
        task_cat = "演员角色映射-上传"
        ui_logger.info("🎉 任务启动，开始上传映射表到 GitHub...", task_category=task_cat)

        if not self.github_config.repo_url or not self.github_config.personal_access_token:
            raise ValueError("未配置 GitHub 仓库 URL 或个人访问令牌 (PAT)。")

        if not os.path.exists(ACTOR_ROLE_MAP_FILE):
            raise FileNotFoundError("本地映射表文件 actor_role_map.json 不存在，请先生成。")

        try:
            ui_logger.info("➡️ [阶段1/3] 正在读取本地文件...", task_category=task_cat)
            with open(ACTOR_ROLE_MAP_FILE, 'r', encoding='utf-8') as f:
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
                "message": f"feat: Update actor role map ({time.strftime('%Y-%m-%d %H:%M:%S')})",
                "content": content_b64,
                "branch": self.github_config.branch
            }
            if sha:
                payload["sha"] = sha
            
            # --- 核心修改：调用新的基于 curl 的上传方法 ---
            self._execute_github_write_request_with_retry("PUT", api_url, self.github_config.personal_access_token, payload, task_cat=task_cat)
            # --- 修改结束 ---
            
            ui_logger.info("✅ 上传成功！映射表已同步到 GitHub 仓库。", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 上传到 GitHub 失败: {e}", task_category=task_cat, exc_info=True)
            raise e

    def download_from_github_task(self, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "演员角色映射-下载"
        ui_logger.info("🎉 任务启动，开始从 GitHub 下载映射表...", task_category=task_cat)

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
                with FileLock(ACTOR_ROLE_MAP_LOCK_FILE, timeout=10):
                    with open(ACTOR_ROLE_MAP_FILE, 'w', encoding='utf-8') as f:
                        f.write(content)
            except Timeout:
                raise IOError("获取文件锁超时，另一个进程可能正在访问该文件。")

            ui_logger.info("✅ 下载成功！本地映射表已更新为 GitHub 版本。", task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 从 GitHub 下载失败: {e}", task_category=task_cat, exc_info=True)
            raise e
        
    def restore_single_map_task(self, single_map_data: Dict, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """
        根据单条映射关系，恢复指定 Emby 媒体项的演员角色名。
        新版逻辑：以映射表为驱动，ID优先，名称降级。
        """
        task_cat = "演员角色映射-单体恢复"
        
        item_ids = single_map_data.get("Emby_itemid", [])
        role_map = single_map_data.get("map", {})
        title = single_map_data.get("title", "未知作品")

        if not item_ids or not role_map:
            ui_logger.error(f"❌ 任务失败：传入的映射数据不完整。作品: {title}", task_category=task_cat)
            raise ValueError("映射数据不完整")

        total_items = len(item_ids)
        task_manager.update_task_progress(task_id, 0, total_items)
        ui_logger.info(f"🎉 任务启动，开始为作品《{title}》恢复演员角色，共涉及 {total_items} 个Emby媒体项。", task_category=task_cat)

        for i, item_id in enumerate(item_ids):
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务被用户取消。", task_category=task_cat)
                return

            try:
                ui_logger.info(f"  ➡️ 正在处理第 {i+1}/{total_items} 个媒体项 (ID: {item_id})...", task_category=task_cat)
                
                # 1. 获取并预处理 Emby 演员列表
                item_details = self._get_emby_item_details(item_id, "People")
                current_people = item_details.get("People", [])
                if not current_people:
                    ui_logger.info(f"     - [跳过] 媒体项 {item_id} 没有演职员信息。", task_category=task_cat)
                    continue

                emby_actors_by_id = {}
                emby_actors_by_name = {}
                for person in current_people:
                    if person.get("Type") == "Actor":
                        provider_ids_lower = {k.lower(): v for k, v in person.get("ProviderIds", {}).items()}
                        person_tmdb_id = provider_ids_lower.get("tmdb")
                        if person_tmdb_id:
                            emby_actors_by_id[str(person_tmdb_id)] = person
                        emby_actors_by_name[person.get("Name")] = person

                # 2. 遍历映射表，进行匹配和更新
                has_changes = False
                updated_logs = []
                for map_actor_name, map_actor_data in role_map.items():
                    map_tmdb_id = map_actor_data.get("tmdb_id")
                    target_emby_person = None

                    # a. ID 优先匹配
                    if map_tmdb_id and str(map_tmdb_id) != "null":
                        target_emby_person = emby_actors_by_id.get(str(map_tmdb_id))
                        if target_emby_person:
                            logging.debug(f"【调试】[ID匹配成功] 映射表演员 [{map_actor_name}] 通过 TMDB ID {map_tmdb_id} 关联到 Emby 演员 [{target_emby_person.get('Name')}]。")

                    # b. 名称降级匹配
                    if not target_emby_person:
                        target_emby_person = emby_actors_by_name.get(map_actor_name)
                        if target_emby_person:
                            logging.debug(f"【调试】[名称匹配成功] 映射表演员 [{map_actor_name}] 通过名称关联到 Emby 演员。")
                    
                    # c. 对比与更新
                    if target_emby_person:
                        current_role = target_emby_person.get("Role", "")
                        target_role = map_actor_data.get("role", "")
                        if current_role != target_role:
                            target_emby_person["Role"] = target_role
                            has_changes = True
                            updated_logs.append(f"     - ✅ 演员 [{target_emby_person.get('Name')}] 角色已更新: '{current_role}' → '{target_role}'")
                    else:
                        logging.debug(f"【调试】[匹配失败] 在 Emby 媒体项 {item_id} 中未找到演员 [{map_actor_name}]。")

                # 3. 如果有变更，则写回 Emby
                if has_changes:
                    ui_logger.info(f"     - 发现角色变更，正在写回 Emby...", task_category=task_cat)
                    item_details["People"] = current_people
                    
                    update_url = f"{self.server_config.server}/Items/{item_id}"
                    headers = {'Content-Type': 'application/json'}
                    params = {"api_key": self.server_config.api_key}
                    proxies = self.proxy_manager.get_proxies(update_url)
                    
                    response = self.session.post(update_url, params=params, json=item_details, headers=headers, timeout=30, proxies=proxies)
                    response.raise_for_status()
                    
                    for log_line in updated_logs:
                        ui_logger.info(log_line, task_category=task_cat)
                    ui_logger.info(f"     - ✅ 媒体项 (ID: {item_id}) 更新成功！", task_category=task_cat)
                else:
                    ui_logger.info(f"     - 角色名均与映射表一致，无需更新。", task_category=task_cat)

            except Exception as e:
                ui_logger.error(f"  - ❌ 处理媒体项 {item_id} 时发生错误: {e}", task_category=task_cat, exc_info=True)
            
            task_manager.update_task_progress(task_id, i + 1, total_items)
        
        ui_logger.info(f"🎉 作品《{title}》的角色恢复任务执行完毕。", task_category=task_cat)

    def update_single_map_file(self, single_map_data: Dict):
        """
        根据传入的单条映射数据，更新本地的 actor_role_map.json 文件。
        """
        task_cat = "演员角色映射-文件更新"
        tmdb_id = single_map_data.get("tmdb_id")
        if not tmdb_id:
            raise ValueError("传入的数据缺少 tmdb_id")

        ui_logger.info(f"➡️ 准备更新映射文件，目标作品 TMDB ID: {tmdb_id}", task_category=task_cat)
        
        try:
            with FileLock(ACTOR_ROLE_MAP_LOCK_FILE, timeout=10):
                # 1. 读取现有文件
                if os.path.exists(ACTOR_ROLE_MAP_FILE):
                    with open(ACTOR_ROLE_MAP_FILE, 'r', encoding='utf-8') as f:
                        full_map = json.load(f)
                else:
                    full_map = {}
                
                # 2. 更新指定条目
                full_map[tmdb_id] = {
                    "title": single_map_data.get("title", "未知作品"),
                    "Emby_itemid": single_map_data.get("Emby_itemid", []),
                    "map": single_map_data.get("map", {})
                }

                # 3. 写回文件
                with open(ACTOR_ROLE_MAP_FILE, 'w', encoding='utf-8') as f:
                    json.dump(full_map, f, ensure_ascii=False, indent=2)
                
                ui_logger.info(f"✅ 成功更新映射文件，作品: {single_map_data.get('title')}", task_category=task_cat)
                return {"status": "success", "message": "映射关系已成功保存到本地文件！"}

        except Timeout:
            ui_logger.error("❌ 更新文件失败：获取文件锁超时，另一个进程可能正在访问该文件。", task_category=task_cat)
            raise IOError("获取文件锁超时，另一个进程可能正在访问该文件。")
        except Exception as e:
            ui_logger.error(f"❌ 更新文件时发生未知错误: {e}", task_category=task_cat, exc_info=True)
            raise e
        
    def restore_roles_from_map_task(self, scope: ScheduledTasksTargetScope, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """
        根据通用范围和本地映射表，批量恢复演员角色名。
        新版逻辑：以映射表为驱动，ID优先，名称降级，兼容多版本。
        """
        task_cat = "演员角色映射-批量恢复"
        ui_logger.info(f"🎉 任务启动，范围: {scope.mode}", task_category=task_cat)

        # 1. 加载本地映射表
        ui_logger.info("➡️ [阶段1/4] 正在加载本地映射表...", task_category=task_cat)
        if not os.path.exists(ACTOR_ROLE_MAP_FILE):
            raise FileNotFoundError("本地映射表文件 actor_role_map.json 不存在，请先生成。")
        
        with open(ACTOR_ROLE_MAP_FILE, 'r', encoding='utf-8') as f:
            full_map = json.load(f)
        
        if not full_map:
            ui_logger.warning("⚠️ 本地映射表为空，任务中止。", task_category=task_cat)
            return

        # 2. 获取目标媒体项并构建反向映射
        ui_logger.info("➡️ [阶段2/4] 正在根据范围获取媒体列表并构建处理计划...", task_category=task_cat)
        selector = MediaSelector(self.config)
        media_ids_in_scope = selector.get_item_ids(scope)
        if not media_ids_in_scope:
            ui_logger.info("✅ 在指定范围内未找到任何媒体项，任务完成。", task_category=task_cat)
            return

        # 构建 TMDB ID -> [Emby Item IDs] 的反向映射
        tmdb_to_emby_map = {}
        for item_id in media_ids_in_scope:
            try:
                details = self._get_emby_item_details(item_id, "ProviderIds")
                tmdb_id = details.get("ProviderIds", {}).get("Tmdb")
                if tmdb_id:
                    tmdb_id_str = str(tmdb_id)
                    if tmdb_id_str not in tmdb_to_emby_map:
                        tmdb_to_emby_map[tmdb_id_str] = []
                    tmdb_to_emby_map[tmdb_id_str].append(item_id)
            except Exception as e:
                logging.error(f"【调试】获取媒体项 {item_id} 的TMDB ID时失败: {e}")

        # 3. 遍历本地映射表，执行恢复
        ui_logger.info("➡️ [阶段3/4] 开始根据处理计划，逐一恢复作品...", task_category=task_cat)
        total_works_to_process = len(full_map)
        task_manager.update_task_progress(task_id, 0, total_works_to_process)
        processed_works_count = 0

        for tmdb_id, map_data in full_map.items():
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务被用户取消。", task_category=task_cat)
                return
            
            processed_works_count += 1
            task_manager.update_task_progress(task_id, processed_works_count, total_works_to_process)

            # 检查此作品是否在处理范围内
            item_ids_to_process = tmdb_to_emby_map.get(tmdb_id)
            if not item_ids_to_process:
                continue

            title = map_data.get("title", f"TMDB ID {tmdb_id}")
            ui_logger.info(f"  ➡️ 开始处理作品《{title}》，涉及 {len(item_ids_to_process)} 个Emby版本。", task_category=task_cat)
            
            # 复用单体恢复的逻辑
            single_map_data = {
                "Emby_itemid": item_ids_to_process,
                "map": map_data.get("map", {}),
                "title": title
            }
            # 创建一个临时的子任务，但日志类别保持一致
            self.restore_single_map_task(single_map_data, cancellation_event, task_id, task_manager)

        ui_logger.info("➡️ [阶段4/4] 所有在范围内的作品均已处理完毕。", task_category=task_cat)
        ui_logger.info("🎉 批量恢复演员角色任务执行完毕。", task_category=task_cat)