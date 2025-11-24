# backend/actor_role_mapper_logic.py (新文件)

import logging
import os
import json
import threading
import time
import re
import hmac
import hashlib
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


def _contains_chinese(text: str) -> bool:
    """检查字符串是否包含中文字符"""
    if not text: return False
    return bool(re.search(r'[\u4e00-\u9fa5]', text))



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

    # backend/actor_role_mapper_logic.py (新增代码块)

    def _search_persons_by_name(self, name: str) -> List[Dict]:
        """在 Emby 中按姓名搜索所有 Person Item"""
        try:
            url = f"{self.server_config.server}/Items"
            params = {
                "api_key": self.server_config.api_key,
                "IncludeItemTypes": "Person",
                "Recursive": "true",
                "SearchTerm": name,
                "Fields": "ProviderIds" 
            }
            proxies = self.proxy_manager.get_proxies(url)
            response = self.session.get(url, params=params, timeout=20, proxies=proxies)
            response.raise_for_status()
            items = response.json().get("Items", [])
            # 精确匹配，防止返回 "张赫" 时也返回 "张赫一"
            return [p for p in items if p.get("Name") == name]
        except Exception as e:
            logging.error(f"【调试】按姓名 '{name}' 搜索演员时失败: {e}")
            return []

    def _rename_person_by_id(self, person_id: str, new_name: str, task_category: str) -> bool:
        """通过 Person ID 重命名一个演员，包含重试逻辑"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                person_details = self._get_emby_item_details(person_id, "ProviderIds")
                if person_details.get("Name") == new_name:
                    return True # 已经是目标名称，无需修改
                
                person_details['Name'] = new_name
                
                update_url = f"{self.server_config.server}/Items/{person_id}"
                headers = {'Content-Type': 'application/json'}
                params = {"api_key": self.server_config.api_key}
                proxies = self.proxy_manager.get_proxies(update_url)

                resp = self.session.post(update_url, params=params, json=person_details, headers=headers, timeout=30, proxies=proxies)
                resp.raise_for_status()
                
                if resp.status_code == 204:
                    return True
                else:
                    # 记录警告但继续尝试
                    ui_logger.warning(f"       - ⚠️ 演员重命名请求返回状态码 {resp.status_code} (尝试 {attempt + 1}/{max_retries})", task_category=task_category)

            except Exception as e:
                ui_logger.error(f"       - ❌ 演员重命名API请求失败 (尝试 {attempt + 1}/{max_retries}): {e}", task_category=task_category)
            
            time.sleep(2) # 每次失败后等待2秒
        
        return False

    

    def generate_map_task(self, scope: ScheduledTasksTargetScope, generation_mode: str, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "演员角色映射-生成"
        actor_limit = self.config.actor_role_mapper_config.actor_limit
        
        mode_map = {
            'overwrite': '覆盖模式',
            'incremental': '增量模式',
            'update_selected': '更新指定模式'
        }
        mode_text = mode_map.get(generation_mode, '未知模式')

        ui_logger.info(f"🎉 任务启动 ({mode_text})，范围: {scope.mode}，演员上限: {actor_limit}", task_category=task_cat)

        try:
            actor_role_map = {}
            if generation_mode in ['incremental', 'update_selected']:
                ui_logger.info(f"➡️ [阶段1/6] {mode_text}：正在加载现有映射表...", task_category=task_cat)
                if os.path.exists(ACTOR_ROLE_MAP_FILE):
                    try:
                        with open(ACTOR_ROLE_MAP_FILE, 'r', encoding='utf-8') as f:
                            actor_role_map = json.load(f)
                        ui_logger.info(f"  - ✅ 已成功加载 {len(actor_role_map)} 条现有记录。", task_category=task_cat)
                    except (json.JSONDecodeError, IOError) as e:
                        ui_logger.warning(f"  - ⚠️ 加载现有映射表失败，将作为首次生成处理。错误: {e}", task_category=task_cat)
                else:
                    ui_logger.info("  - 本地映射表不存在，将作为首次生成处理。", task_category=task_cat)

            ui_logger.info("➡️ [阶段2/6] 正在获取媒体列表...", task_category=task_cat)
            selector = MediaSelector(self.config)
            media_ids = selector.get_item_ids(scope)
            if not media_ids:
                ui_logger.info("✅ 在指定范围内未找到任何媒体项，任务完成。", task_category=task_cat)
                return
            
            ui_logger.info(f"🔍 已获取 {len(media_ids)} 个媒体项，开始预处理...", task_category=task_cat)

            media_ids_to_process = []
            # --- 修改 1: 重命名 map，使其更清晰 ---
            tmdb_key_to_item_id_map = {}
            skipped_count = 0
            
            ui_logger.info("➡️ [阶段3/6] 正在并发获取所有媒体的 TMDB ID 及类型并进行预过滤...", task_category=task_cat)
            with ThreadPoolExecutor(max_workers=10) as executor:
                # --- 修改 2: 请求的字段中增加 Type ---
                future_to_id = {executor.submit(self._get_emby_item_details, item_id, "ProviderIds,Type"): item_id for item_id in media_ids}
                for future in as_completed(future_to_id):
                    if cancellation_event.is_set(): return
                    item_id = future_to_id[future]
                    try:
                        details = future.result()
                        provider_ids_lower = {k.lower(): v for k, v in details.get("ProviderIds", {}).items()}
                        tmdb_id = provider_ids_lower.get("tmdb")
                        item_type = details.get("Type") # "Movie" or "Series"
                        
                        if not tmdb_id or not item_type:
                            continue
                        
                        # --- 修改 3: 构建带前缀的 map_key ---
                        type_prefix = 'tv' if item_type == 'Series' else 'movie'
                        map_key = f"{type_prefix}-{tmdb_id}"
                        
                        if generation_mode == 'incremental' and map_key in actor_role_map:
                            skipped_count += 1
                            continue
                        
                        media_ids_to_process.append(item_id)
                        tmdb_key_to_item_id_map[item_id] = map_key
                    except Exception as e:
                        logging.error(f"【调试】预处理媒体 {item_id} 时出错: {e}")

            if not media_ids_to_process:
                if generation_mode == 'incremental':
                    ui_logger.info(f"✅ 预处理完成，所有 {len(media_ids)} 个媒体项均已存在于映射表中，任务结束。", task_category=task_cat)
                else:
                    ui_logger.info(f"✅ 在指定范围内未找到需要处理的媒体项，任务结束。", task_category=task_cat)
                return
            
            ui_logger.info(f"  - 预处理完成，需要新增/更新 {len(media_ids_to_process)} 个媒体项 (已跳过 {skipped_count} 个)。", task_category=task_cat)

            total_items = len(media_ids_to_process)
            task_manager.update_task_progress(task_id, 0, total_items)
            
            processed_count = 0

            with ThreadPoolExecutor(max_workers=10) as executor:
                ui_logger.info("➡️ [阶段4/6] 正在并发获取待处理媒体项的基础详情并裁切演员...", task_category=task_cat)
                future_to_id = {executor.submit(self._get_emby_item_details, item_id, "People,Name"): item_id for item_id in media_ids_to_process}
                
                all_actors_to_fetch_details = []
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
                            limited_actors = actors[:actor_limit]
                            
                            if len(actors) > len(limited_actors):
                                ui_logger.debug(f"  - [演员裁切] 媒体【{details.get('Name')}】演员总数: {len(actors)}，根据设置将处理前 {len(limited_actors)} 位。", task_category=task_cat)
                            
                            all_actors_to_fetch_details.extend(limited_actors)

                    except Exception as e:
                        ui_logger.error(f"   - ❌ 获取媒体 {item_id} 基础详情时出错: {e}", task_category=task_cat)

                if cancellation_event.is_set(): return
                
                unique_actors_to_fetch_details = {actor['Id']: actor for actor in all_actors_to_fetch_details}.values()
                ui_logger.info(f"➡️ [阶段5/6] 媒体详情获取完毕，开始为 {len(unique_actors_to_fetch_details)} 个唯一演员并发获取 ProviderIds...", task_category=task_cat)
                
                person_details_map = {}
                future_to_person_id = {executor.submit(self._get_emby_item_details, person['Id'], "ProviderIds"): person for person in unique_actors_to_fetch_details}

                for future in as_completed(future_to_person_id):
                    if cancellation_event.is_set(): return
                    person = future_to_person_id[future]
                    try:
                        person_details_map[person['Id']] = future.result()
                    except Exception as e:
                        logging.debug(f"【调试】获取演员 {person.get('Name')} (ID: {person.get('Id')}) 的 ProviderIds 失败: {e}")

                if cancellation_event.is_set(): return

                ui_logger.info("➡️ [阶段6/6] 开始构建最终映射表...", task_category=task_cat)
                for item_id, details in media_details_map.items():
                    item_name = details.get("Name", f"ID {item_id}")
                    # --- 修改 4: 使用新的 map 获取带前缀的 key ---
                    map_key = tmdb_key_to_item_id_map.get(item_id)
                    
                    people = details.get("People", [])
                    actors = [p for p in people if p.get('Type') == 'Actor']
                    people_to_process = actors[:actor_limit]
                    
                    if not people_to_process:
                        processed_count += 1
                        task_manager.update_task_progress(task_id, processed_count, total_items)
                        continue

                    work_map = {}
                    for person in people_to_process:
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

                        work_map[actor_name] = {
                            "tmdb_id": person_tmdb_id,
                            "role": role
                        }
                    
                    if work_map and map_key:
                        actor_role_map[map_key] = {
                            "title": item_name,
                            "map": work_map
                        }
                    
                    processed_count += 1
                    task_manager.update_task_progress(task_id, processed_count, total_items)

            ui_logger.info("➡️ [阶段7/7] 正在写入本地文件...", task_category=task_cat)
            try:
                with FileLock(ACTOR_ROLE_MAP_LOCK_FILE, timeout=10):
                    with open(ACTOR_ROLE_MAP_FILE, 'w', encoding='utf-8') as f:
                        json.dump(actor_role_map, f, ensure_ascii=False, indent=2)
            except Timeout:
                raise IOError("获取文件锁超时，另一个进程可能正在访问该文件。")

            total_works = len(actor_role_map)
            total_actors = sum(len(work['map']) for work in actor_role_map.values())
            
            final_log_message = f"✅ 映射表生成完毕！共记录 {total_works} 部作品，{total_actors} 条演员角色关系。"
            if generation_mode == 'incremental' and skipped_count > 0:
                final_log_message += f" (跳过 {skipped_count} 个已存在的作品)"
            ui_logger.info(final_log_message, task_category=task_cat)

        except Exception as e:
            ui_logger.error(f"❌ 生成映射表任务失败: {e}", task_category=task_cat, exc_info=True)
            raise e
        

    # backend/actor_role_mapper_logic.py (函数替换)

    def generate_map_for_single_item(self, item_id: str, task_category: str, overwrite: bool = False):
        """为单个媒体项生成角色映射，并以增量模式更新到本地文件。"""
        ui_logger.info(f"➡️ [单体模式] 开始为媒体 (ID: {item_id}) 生成角色映射...", task_category=task_category)
        
        try:
            item_details = self._get_emby_item_details(item_id, "ProviderIds,Name,People,Type")
            item_name = item_details.get("Name", f"ID {item_id}")
            provider_ids_lower = {k.lower(): v for k, v in item_details.get("ProviderIds", {}).items()}
            tmdb_id = provider_ids_lower.get("tmdb")
            item_type = item_details.get("Type")

            if not tmdb_id or not item_type:
                ui_logger.warning(f"   - ⚠️ 媒体【{item_name}】缺少 TMDB ID 或媒体类型，无法生成映射。", task_category=task_category)
                return

            type_prefix = 'tv' if item_type == 'Series' else 'movie'
            map_key = f"{type_prefix}-{tmdb_id}"

            with FileLock(ACTOR_ROLE_MAP_LOCK_FILE, timeout=10):
                actor_role_map = {}
                if os.path.exists(ACTOR_ROLE_MAP_FILE):
                    try:
                        with open(ACTOR_ROLE_MAP_FILE, 'r', encoding='utf-8') as f:
                            actor_role_map = json.load(f)
                    except (json.JSONDecodeError, IOError):
                        pass

                # 计算新的 work_map
                actor_limit = self.config.actor_role_mapper_config.actor_limit
                people = item_details.get("People", [])
                actors = [p for p in people if p.get('Type') == 'Actor']
                people_to_process = actors[:actor_limit]

                if not people_to_process:
                    ui_logger.info(f"   - [跳过] 媒体【{item_name}】没有演员信息，无法生成映射。", task_category=task_category)
                    return

                new_work_map = {}
                with ThreadPoolExecutor(max_workers=5) as executor:
                    future_to_person = {executor.submit(self._get_emby_item_details, p['Id'], "ProviderIds"): p for p in people_to_process}
                    for future in as_completed(future_to_person):
                        person = future_to_person[future]
                        actor_name = person.get("Name")
                        if not actor_name: continue
                        
                        person_tmdb_id = None
                        try:
                            person_details = future.result()
                            if person_details:
                                p_ids = person_details.get("ProviderIds", {})
                                p_ids_lower = {k.lower(): v for k, v in p_ids.items()}
                                person_tmdb_id = p_ids_lower.get("tmdb")
                        except Exception:
                            pass

                        new_work_map[actor_name] = {
                            "tmdb_id": person_tmdb_id,
                            "role": person.get("Role", "")
                        }

                # 核心判断逻辑
                if map_key in actor_role_map:
                    if not overwrite:
                        ui_logger.info(f"   - ✅ 媒体【{item_name}】的映射已存在于本地文件中，跳过本次生成。", task_category=task_category)
                        return
                    else:
                        old_work_map = actor_role_map[map_key].get('map', {})
                        if old_work_map == new_work_map:
                            ui_logger.info(f"   - [跳过写入] 媒体【{item_name}】的新角色数据与现有映射一致，无需更新文件。", task_category=task_cat)
                            return
                        ui_logger.info(f"   - 🔄 媒体【{item_name}】的映射已存在且内容有变化，将执行覆盖更新。", task_category=task_cat)
                
                if new_work_map:
                    actor_role_map[map_key] = {
                        "title": item_name,
                        "map": new_work_map
                    }
                    ui_logger.info(f"   - 🔍 已为【{item_name}】成功生成 {len(new_work_map)} 条演员角色映射。", task_category=task_cat)
                
                with open(ACTOR_ROLE_MAP_FILE, 'w', encoding='utf-8') as f:
                    json.dump(actor_role_map, f, ensure_ascii=False, indent=2)
                
                ui_logger.info(f"   - ✅ 成功将新映射追加或更新到本地文件。", task_category=task_cat)

        except Timeout:
            ui_logger.error(f"   - ❌ 获取文件锁超时，另一个进程可能正在访问该文件。", task_category=task_cat)
        except Exception as e:
            ui_logger.error(f"   - ❌ 为媒体 {item_id} 生成单体映射时发生错误: {e}", task_category=task_category, exc_info=True)

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

    # backend/actor_role_mapper_logic.py (函数替换)

    def download_from_github_task(self, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "演员角色映射-下载"
        ui_logger.info("🎉 任务启动，开始从 GitHub 下载映射表...", task_category=task_cat)

        if not self.github_config.repo_url:
            raise ValueError("未配置 GitHub 仓库 URL。")

        try:
            api_url = self._get_github_api_url()
            ui_logger.info("➡️ [阶段1/2] 正在请求远程文件元数据...", task_category=task_cat)
            
            # 第一次请求，获取文件元数据
            remote_file_meta = self._github_request("GET", api_url)
            if not remote_file_meta:
                raise ValueError("从 GitHub 获取文件元数据失败。")

            content = ""
            # --- 核心修改：判断文件大小，选择不同下载策略 ---
            if 'content' in remote_file_meta and remote_file_meta['content']:
                # 文件小于1MB，直接从元数据中解码
                ui_logger.info("   - 文件小于 1MB，直接解码内容...", task_category=task_cat)
                content = base64.b64decode(remote_file_meta['content']).decode('utf-8')
            elif 'download_url' in remote_file_meta and remote_file_meta['download_url']:
                # 文件大于1MB，需要通过 download_url 再次请求
                download_url = remote_file_meta['download_url']
                file_size_mb = remote_file_meta.get('size', 0) / (1024 * 1024)
                ui_logger.info(f"   - 文件大小为 {file_size_mb:.2f} MB (>1MB)，将通过下载链接获取...", task_category=task_cat)
                
                proxies = self.proxy_manager.get_proxies(download_url)
                response = self.session.get(download_url, timeout=60, proxies=proxies) # 增加大文件下载超时
                response.raise_for_status()
                content = response.text
            else:
                raise ValueError("GitHub API 响应中既无 'content' 也无 'download_url'，无法下载文件。")
            # --- 修改结束 ---

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
        
    # backend/actor_role_mapper_logic.py (函数替换)

    def restore_single_map_task(self, item_ids: List[str], role_map: Dict, title: str, cancellation_event: threading.Event, task_id: str, task_manager: Optional[TaskManager] = None, task_category: Optional[str] = None):
        """
        根据映射关系，恢复指定 Emby 媒体项列表的演员角色名。
        采用【反向锁定】策略，融合【演员名修正】逻辑，并使用最终优化的日志风格。
        """
        task_cat = task_category if task_category else "演员角色映射-恢复"
        
        if not item_ids or not role_map:
            ui_logger.error(f"❌ 任务失败：传入的映射数据不完整。作品: {title}", task_category=task_cat)
            raise ValueError("映射数据不完整")

        total_items = len(item_ids)
        if task_manager:
            pass
        ui_logger.info(f"  ➡️ 开始为作品《{title}》恢复演员角色，共涉及 {total_items} 个Emby媒体项。", task_category=task_cat)

        for i, item_id in enumerate(item_ids):
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务被用户取消。", task_category=task_cat)
                return

            isolated_persons = {} 
            
            try:
                ui_logger.info(f"     - 正在处理第 {i+1}/{total_items} 个媒体项 (ID: {item_id})...", task_category=task_cat)
                
                item_details_base = self._get_emby_item_details(item_id, "People")
                current_people_base = item_details_base.get("People", [])
                if not current_people_base:
                    ui_logger.info(f"       - [跳过] 媒体项 {item_id} 没有演职员信息。", task_category=task_cat)
                    continue
                
                emby_actors_base = [p for p in current_people_base if p.get("Type") == "Actor"]
                emby_actors_by_id = {}
                emby_actors_by_name = {}
                
                with ThreadPoolExecutor(max_workers=10) as executor:
                    future_to_person = {executor.submit(self._get_emby_item_details, p['Id'], "ProviderIds"): p for p in emby_actors_base}
                    for future in as_completed(future_to_person):
                        original_person = future_to_person[future]
                        try:
                            full_person_details = future.result()
                            original_person.update(full_person_details)
                            provider_ids_lower = {k.lower(): v for k, v in full_person_details.get("ProviderIds", {}).items()}
                            person_tmdb_id = provider_ids_lower.get("tmdb")
                            if person_tmdb_id:
                                emby_actors_by_id[str(person_tmdb_id)] = original_person
                            emby_actors_by_name[original_person.get("Name")] = original_person
                        except Exception:
                            emby_actors_by_name[original_person.get("Name")] = original_person

                actors_to_update_map = {}
                for map_actor_name, map_actor_data in role_map.items():
                    map_tmdb_id = map_actor_data.get("tmdb_id")
                    target_emby_person = None
                    match_source = ""
                    if map_tmdb_id and str(map_tmdb_id) != "null":
                        target_emby_person = emby_actors_by_id.get(str(map_tmdb_id))
                        if target_emby_person: match_source = "ID"
                    if not target_emby_person:
                        target_emby_person = emby_actors_by_name.get(map_actor_name)
                        if target_emby_person: match_source = "名称"
                    
                    if target_emby_person:
                        current_role = target_emby_person.get("Role", "")
                        target_role = map_actor_data.get("role", "")
                        current_name = target_emby_person.get("Name")
                        target_name = map_actor_name

                        if current_role != target_role or (current_name != target_name and _contains_chinese(target_name)):
                            actors_to_update_map[target_emby_person.get("Id")] = {
                                'target_role': target_role, 'current_role': current_role,
                                'target_name': target_name, 'current_name': current_name,
                                'match_source': match_source,
                                'source': map_actor_data.get('source')
                            }

                if not actors_to_update_map:
                    ui_logger.info(f"       - 角色名与演员名均与映射表一致，无需更新。", task_category=task_cat)
                    continue

                ui_logger.info(f"       - 🔍 扫描发现 {len(actors_to_update_map)} 位演员信息需要更新。", task_category=task_cat)
                
                ui_logger.info(f"       - [隔离] 正在为 {len(actors_to_update_map)} 个待更新演员进行临时改名...", task_category=task_cat)
                for person_id, update_info in actors_to_update_map.items():
                    current_name = update_info['current_name']
                    unique_name = f"{current_name}_embytoolkit_update_{person_id}"
                    
                    logging.debug(f"【调试】隔离: {current_name} (ID: {person_id}) -> {unique_name}")
                    if self._rename_person_by_id(person_id, unique_name, task_cat):
                        isolated_persons[person_id] = (current_name, update_info['target_name'])
                        person_in_list = next((p for p in current_people_base if p.get("Id") == person_id), None)
                        if person_in_list:
                            person_in_list["Name"] = unique_name
                    else:
                        raise Exception(f"隔离演员 {current_name} (ID: {person_id}) 失败，中止操作。")

                ui_logger.info(f"       - [更新] 隔离完成，开始将变更写入 Emby...", task_category=task_cat)
                for person in current_people_base:
                    person_id = person.get("Id")
                    if person_id in actors_to_update_map:
                        person["Role"] = actors_to_update_map[person_id]['target_role']
                
                item_details_base["People"] = current_people_base
                update_url = f"{self.server_config.server}/Items/{item_id}"
                headers = {'Content-Type': 'application/json'}
                params = {"api_key": self.server_config.api_key}
                proxies = self.proxy_manager.get_proxies(update_url)
                response = self.session.post(update_url, params=params, json=item_details_base, headers=headers, timeout=30, proxies=proxies)
                response.raise_for_status()
                ui_logger.info(f"       - ✅ 媒体项 (ID: {item_id}) 更新成功！", task_category=task_cat)

                ui_logger.info(f"     - 🔄 [变更详情]", task_category=task_cat)
                for update_info in actors_to_update_map.values():
                    current_name, target_name = update_info['current_name'], update_info['target_name']
                    current_role, target_role = update_info['current_role'], update_info['target_role']
                    
                    # --- 核心修正：直接使用 source，否则回退 ---
                    source_text = update_info.get('source') or f"(通过{update_info['match_source']}匹配)"

                    if current_name != target_name and _contains_chinese(target_name):
                        ui_logger.info(f"       - ✅ 演员名修正: '{current_name}' -> '{target_name}' {source_text}", task_category=task_cat)
                    
                    if current_role != target_role:
                        actor_display_name = target_name if current_name == target_name else f"[{target_name}]"
                        # 如果演员名也被修正了，角色日志就不再重复显示来源
                        if current_name != target_name and _contains_chinese(target_name):
                            ui_logger.info(f"       - ✅ 角色名更新: {actor_display_name} '{current_role}' -> '{target_role}'", task_category=task_cat)
                        else:
                            ui_logger.info(f"       - ✅ 角色名更新: {actor_display_name} '{current_role}' -> '{target_role}' {source_text}", task_category=task_cat)

            except Exception as e:
                ui_logger.error(f"  - ❌ 处理媒体项 {item_id} 时发生错误: {e}", task_category=task_cat, exc_info=True)
            
            finally:
                if isolated_persons:
                    ui_logger.info(f"       - [恢复] 开始将 {len(isolated_persons)} 个演员恢复到目标名称...", task_category=task_cat)
                    for person_id, (original_name, target_name) in isolated_persons.items():
                        log_msg = f"         - 🔓 恢复: (ID: {person_id}) -> {target_name}"
                        if original_name != target_name:
                            log_msg += f" (原名: '{original_name}')"
                        logging.debug(log_msg)
                        
                        if not self._rename_person_by_id(person_id, target_name, task_cat):
                            ui_logger.error(f"         - ❌ 恢复演员 (ID: {person_id}) 名称失败！请手动将其名称修改为 `{target_name}`。", task_category=task_cat)
                
                ui_logger.info(f"     - 🎉 作品《{title}》处理完毕。", task_category=task_cat)

    def update_single_map_file(self, single_map_data: Dict):
        """
        根据传入的单条映射数据，更新本地的 actor_role_map.json 文件。
        """
        task_cat = "演员角色映射-文件更新"
        # --- 修改 1: 字段名从 tmdb_id 改为 map_key，更准确 ---
        map_key = single_map_data.get("map_key")
        if not map_key:
            raise ValueError("传入的数据缺少 map_key")

        ui_logger.info(f"➡️ 准备更新映射文件，目标作品 Key: {map_key}", task_category=task_cat)
        
        try:
            with FileLock(ACTOR_ROLE_MAP_LOCK_FILE, timeout=10):
                if os.path.exists(ACTOR_ROLE_MAP_FILE):
                    with open(ACTOR_ROLE_MAP_FILE, 'r', encoding='utf-8') as f:
                        full_map = json.load(f)
                else:
                    full_map = {}
                
                # --- 修改 2: 使用新的 map_key 作为主键 ---
                full_map[map_key] = {
                    "title": single_map_data.get("title", "未知作品"),
                    "map": single_map_data.get("map", {})
                }

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
        
    # backend/actor_role_mapper_logic.py (函数替换)

    def restore_roles_from_map_task(self, scope: ScheduledTasksTargetScope, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        """
        根据通用范围和本地映射表，批量恢复演员角色名。
        新版逻辑：以映射表为驱动，通过 id_map.json 查找 ItemId。
        """
        task_cat = "演员角色映射-批量恢复"
        ui_logger.info(f"🎉 任务启动，范围: {scope.mode}", task_category=task_cat)

        ui_logger.info("➡️ [阶段1/4] 正在加载本地角色映射表...", task_category=task_cat)
        if not os.path.exists(ACTOR_ROLE_MAP_FILE):
            raise FileNotFoundError("本地角色映射表文件 actor_role_map.json 不存在，请先生成。")
        
        with open(ACTOR_ROLE_MAP_FILE, 'r', encoding='utf-8') as f:
            role_map = json.load(f)
        
        if not role_map:
            ui_logger.warning("⚠️ 本地角色映射表为空，任务中止。", task_category=task_cat)
            return

        ui_logger.info("➡️ [阶段2/4] 正在加载 TMDB-Emby ID 映射表...", task_category=task_cat)
        id_map_file = os.path.join('/app/data', 'id_map.json')
        if not os.path.exists(id_map_file):
            ui_logger.error("❌ 关键文件 id_map.json 不存在！请先在“定时任务”页面生成该映射表。", task_category=task_cat)
            raise FileNotFoundError("ID映射表 (id_map.json) 不存在。")
        with open(id_map_file, 'r', encoding='utf-8') as f:
            id_map = json.load(f)
        ui_logger.info("   - ❗ 提示：恢复操作将基于您上一次生成的 `id_map.json`。为确保结果准确，建议在恢复前重新生成ID映射表。", task_category=task_cat)

        ui_logger.info("➡️ [阶段3/4] 正在根据范围获取媒体列表...", task_category=task_cat)
        selector = MediaSelector(self.config)
        media_ids_in_scope = set(selector.get_item_ids(scope))
        if not media_ids_in_scope:
            ui_logger.info("✅ 在指定范围内未找到任何媒体项，任务完成。", task_category=task_cat)
            return

        ui_logger.info("➡️ [阶段4/4] 开始根据处理计划，逐一恢复作品...", task_category=task_cat)
        total_works_to_process = len(role_map)
        task_manager.update_task_progress(task_id, 0, total_works_to_process)
        processed_works_count = 0

        # --- 核心修改 1: 变量名从 tmdb_id 改为 map_key，并直接使用它查询 id_map ---
        for map_key, map_data in role_map.items():
            if cancellation_event.is_set():
                ui_logger.warning("⚠️ 任务被用户取消。", task_category=task_cat)
                return
            
            processed_works_count += 1
            task_manager.update_task_progress(task_id, processed_works_count, total_works_to_process)

            emby_ids_from_map = id_map.get(map_key, [])
            item_ids_to_process = list(media_ids_in_scope.intersection(emby_ids_from_map))
            
            if not item_ids_to_process:
                continue

            title = map_data.get("title", f"Map Key {map_key}")
            
            self.restore_single_map_task(
                item_ids=item_ids_to_process,
                role_map=map_data.get("map", {}),
                title=title,
                cancellation_event=cancellation_event,
                task_id=task_id,
                task_manager=task_manager
            )

        ui_logger.info("🎉 批量恢复演员角色任务执行完毕。", task_category=task_cat)