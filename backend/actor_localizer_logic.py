# backend/actor_localizer_logic.py (完整修改版)

import logging
import threading
import time
import requests
import json
import re
import copy
import os
import hmac
import hashlib
from typing import List, Dict, Any, Generator, Optional, Iterable

try:
    import translators as ts
except ImportError:
    logging.warning("【演员中文化】'translators' 库未安装，相关功能将不可用。请运行 'pip install translators'。")
    ts = None

from models import AppConfig, ActorLocalizerConfig, TargetScope, TencentApiConfig, SiliconflowApiConfig
from task_manager import TaskManager
from douban_manager import DOUBAN_CACHE_FILE

class ActorLocalizerLogic:
    def __init__(self, app_config: AppConfig):
        self.server_config = app_config.server_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.douban_map = self._load_douban_data()

    def _load_douban_data(self) -> Dict:
        if not os.path.exists(DOUBAN_CACHE_FILE):
            logging.warning("【演员中文化】未找到豆瓣缓存文件，匹配功能将无法使用。")
            return {}
        try:
            with open(DOUBAN_CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logging.info(f"【演员中文化】成功加载 {len(data)} 条豆瓣缓存数据。")
            return data
        except Exception as e:
            logging.error(f"【演员中文化】加载豆瓣缓存文件失败: {e}")
            return {}

    def _contains_chinese(self, text: str) -> bool:
        if not text: return False
        return bool(re.search(r'[\u4e00-\u9fa5]', text))

    def _is_pure_english(self, text: str) -> bool:
        if not text: return False
        return bool(re.match(r'^[a-zA-Z0-9\s\.,\'\-!&\(\)]+$', text))

    def _clean_douban_character(self, character: str) -> str:
        if not character: return ""
        return re.sub(r'^(饰|饰演)\s*', '', character).strip()

    def _get_item_details(self, item_id: str, full_json: bool = False) -> Dict:
        try:
            url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
            params = {"api_key": self.api_key}
            if not full_json:
                params["Fields"] = "People,ProviderIds,Name"
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logging.error(f"【演员中文化】获取媒体详情 (ID: {item_id}) 失败: {e}")
            return None

    def _get_item_ids_for_scanning(self, target: TargetScope, cancellation_event: threading.Event) -> List[str]:
        if target.scope == "search" and target.item_ids:
            return target.item_ids

        all_item_ids = []
        item_types_to_fetch = ""
        parent_ids = []

        if target.scope == "media_type" and target.media_type:
            item_types_to_fetch = target.media_type
            parent_ids.append(None)
        elif target.scope == "library" and target.library_ids:
            item_types_to_fetch = "Movie,Series"
            parent_ids.extend(target.library_ids)
        elif target.scope == "all_libraries":
            item_types_to_fetch = "Movie,Series"
            parent_ids.append(None)
        else:
            return []

        blacklisted_ids = set()
        if target.scope == "all_libraries" and target.library_blacklist:
            views_url = f"{self.base_url}/Users/{self.user_id}/Views"
            views_resp = requests.get(views_url, params=self.params)
            views = views_resp.json().get("Items", [])
            blacklist_names = {name.strip() for name in target.library_blacklist.split(',') if name.strip()}
            blacklisted_ids = {view['Id'] for view in views if view['Name'] in blacklist_names}

        for p_id in parent_ids:
            if cancellation_event.is_set(): return []
            
            url = f"{self.base_url}/Items"
            params = {**self.params, "Recursive": "true", "IncludeItemTypes": item_types_to_fetch, "Fields": "Id,ParentId"}
            if p_id:
                params["ParentId"] = p_id

            start_index = 0
            limit = 500
            while not cancellation_event.is_set():
                params["StartIndex"] = start_index
                try:
                    response = requests.get(url, params=params, timeout=60)
                    response.raise_for_status()
                    page_items = response.json().get("Items", [])
                    if not page_items:
                        break
                    
                    for item in page_items:
                        if item.get("ParentId") not in blacklisted_ids:
                            all_item_ids.append(item["Id"])

                    start_index += len(page_items)
                except requests.RequestException as e:
                    logging.error(f"【演员中文化】在计数阶段发生网络错误: {e}")
                    break
        
        return all_item_ids

    def _update_item_on_server(self, item_id: str, item_json: Dict) -> bool:
        try:
            url = f"{self.base_url}/Items/{item_id}"
            headers = {'Content-Type': 'application/json'}
            resp = requests.post(url, params=self.params, json=item_json, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.status_code == 204
        except requests.RequestException as e:
            logging.error(f"【演员中文化】更新媒体项 (ID: {item_id}) 失败: {e}")
            return False

    def _translate_text(self, text: str, config: ActorLocalizerConfig, context_title: Optional[str] = None) -> str:
        if not text: return ""
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 只有在重试时（attempt > 0）才会 sleep
                if attempt > 0:
                    logging.warning(f"【翻译】第 {attempt + 1}/{max_retries} 次重试翻译: '{text}'")
                    # 注意：这里的冷却只针对重试，主冷却逻辑已移出
                    if config.api_cooldown_enabled and config.api_cooldown_time > 0:
                        time.sleep(config.api_cooldown_time)

                if config.translation_mode == 'translators':
                    if ts is None: raise ImportError("translators 库未安装")
                    logging.info(f"【翻译】[translators:{config.translator_engine}] 正在翻译: '{text}'")
                    return ts.translate_text(text, translator=config.translator_engine, to_language='zh')
                
                elif config.translation_mode == 'tencent':
                    logging.info(f"【翻译】[腾讯云API] 正在翻译: '{text}'")
                    return self.translate_with_tencent_api(text, config.tencent_config)

                elif config.translation_mode == 'siliconflow':
                    logging.info(f"【翻译】[SiliconFlow:{config.siliconflow_config.model_name}] 正在翻译: '{text}' (上下文: {context_title or '无'})")
                    return self.translate_with_siliconflow_api(text, config.siliconflow_config, context_title)
                
                return text

            except requests.exceptions.RequestException as e:
                logging.error(f"【翻译】翻译 '{text}' 时发生网络错误 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt + 1 >= max_retries:
                    logging.error(f"【翻译】已达到最大重试次数，放弃翻译 '{text}'。")
                    return text
            except Exception as e:
                logging.error(f"【翻译】翻译 '{text}' 时发生不可重试的错误: {e}")
                return text

        return text

    def _process_single_item_for_localization(self, item_id: str, config: ActorLocalizerConfig) -> bool:
        details = self._get_item_details(item_id)
        if not details: return False
        
        item_name = details.get('Name', '未知名称')
        logging.info(f"  -> 正在处理: [{item_name}] (ID: {item_id})")

        provider_ids = details.get('ProviderIds', {})
        douban_id = next((v for k, v in provider_ids.items() if k.lower() == 'douban'), None)
        
        if not douban_id:
            logging.debug(f"     -- 跳过，无豆瓣ID。")
            return False
        
        people = details.get('People', [])
        if not any(not self._contains_chinese(p.get('Role', '')) for p in people):
            logging.debug(f"     -- 跳过，角色名均已包含中文。")
            return False

        douban_item = self.douban_map.get(douban_id)
        if not douban_item:
            logging.warning(f"     -- 跳过，本地无豆瓣ID {douban_id} 的数据。")
            return False

        emby_actors_to_match = {p['Name']: p.get('Role', '') for p in people[:config.person_limit] if p.get('Type') == 'Actor' and not self._contains_chinese(p.get('Role', ''))}
        douban_standard_roles = {actor.get('name'): self._clean_douban_character(actor.get('character', '')) for actor in douban_item.get('actors', []) if self._clean_douban_character(actor.get('character', '')) and self._contains_chinese(self._clean_douban_character(actor.get('character', '')))}

        new_people_list = copy.deepcopy(people)
        has_changes = False

        for emby_actor_name, original_role in emby_actors_to_match.items():
            new_role = None
            source = None
            if emby_actor_name in douban_standard_roles:
                new_role = douban_standard_roles[emby_actor_name]
                source = "豆瓣"
                logging.info(f"     -- 更新: {emby_actor_name}: '{original_role}' -> '{new_role}' (来自{source})")
            elif config.translation_enabled:
                if translated_role and translated_role != original_role:
                    new_role = translated_role
                    source = "翻译"
                    logging.info(f"     -- 更新: {emby_actor_name}: '{original_role}' -> '{new_role}' (来自{source})")
            elif config.replace_english_role and self._is_pure_english(original_role):
                new_role = "演员"
                source = "替换"
                logging.info(f"     -- 更新: {emby_actor_name}: '{original_role}' -> '{new_role}' (来自{source})")
            
            if new_role:
                has_changes = True
                for person in new_people_list:
                    if person.get('Name') == emby_actor_name:
                        person['Role'] = new_role
                        break
        
        if has_changes:
            full_item_json = self._get_item_details(item_id, full_json=True)
            if full_item_json:
                full_item_json['People'] = new_people_list
                if self._update_item_on_server(item_id, full_item_json):
                    logging.info(f"     -- 成功应用更新到 Emby。")
                    return True
            logging.error(f"     -- 应用更新到 Emby 失败。")
        
        return False

    def run_localization_for_items(self, item_ids: Iterable[str], config: ActorLocalizerConfig, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        if not self.douban_map:
            logging.error("【演员中文化-任务】本地豆瓣数据库为空，任务中止。")
            return

        item_ids_list = list(item_ids)
        total_items = len(item_ids_list)
        logging.info(f"【演员中文化-任务】启动，共需处理 {total_items} 个媒体项。")
        task_manager.update_task_progress(task_id, 0, total_items)

        if total_items == 0:
            logging.info("【演员中文化-任务】没有需要处理的媒体项，任务结束。")
            return

        updated_count = 0
        for index, item_id in enumerate(item_ids_list):
            if cancellation_event.is_set():
                logging.warning("【演员中文化-任务】任务被用户取消。")
                break
            
            task_manager.update_task_progress(task_id, index + 1, total_items)
            
            if self._process_single_item_for_localization(item_id, config):
                updated_count += 1
        
        logging.info(f"【演员中文化-任务】执行完毕，共更新了 {updated_count} 个项目的演员角色。")
        return {"updated_count": updated_count}

    @staticmethod
    def translate_with_tencent_api(text: str, config: TencentApiConfig) -> str:
        service, host, endpoint = "tmt", "tmt.tencentcloudapi.com", "https://tmt.tencentcloudapi.com"
        version, action = "2018-03-21", "TextTranslate"
        payload = {"SourceText": text, "Source": "en", "Target": "zh", "ProjectId": 0}
        payload_str = json.dumps(payload)
        timestamp = int(time.time())
        date = time.strftime("%Y-%m-%d", time.gmtime(timestamp))
        
        http_request_method = "POST"
        canonical_uri = "/"
        canonical_querystring = ""
        canonical_headers = f"content-type:application/json\nhost:{host}\n"
        signed_headers = "content-type;host"
        hashed_request_payload = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        canonical_request = f"{http_request_method}\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{hashed_request_payload}"

        algorithm = "TC3-HMAC-SHA256"
        credential_scope = f"{date}/{service}/tc3_request"
        hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        string_to_sign = f"{algorithm}\n{str(timestamp)}\n{credential_scope}\n{hashed_canonical_request}"

        def sign(key, msg): return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
        secret_date = sign(("TC3" + config.secret_key).encode("utf-8"), date)
        secret_service = sign(secret_date, service)
        secret_signing = sign(secret_service, "tc3_request")
        signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        authorization = f"{algorithm} Credential={config.secret_id}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"
        
        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json",
            "Host": host,
            "X-TC-Action": action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": version,
            "X-TC-Region": config.region,
        }
        
        response = requests.post(endpoint, headers=headers, data=payload_str.encode("utf-8"), timeout=15)
        response.raise_for_status()
        result = response.json().get("Response", {})
        if "Error" in result:
            raise Exception(f"腾讯API错误: {result['Error']['Code']} - {result['Error']['Message']}")
        return result.get("TargetText", text)

    @staticmethod
    def translate_with_siliconflow_api(text: str, config: SiliconflowApiConfig, context_title: Optional[str] = None) -> str:
        url = "https://api.siliconflow.cn/v1/chat/completions"
        
        system_prompt = """你是一位专业的影视剧翻译专家，尤其擅长将英文或拼音格式的人名和角色名，翻译成符合中文影视圈习惯的、最常见的官方或通用译名。

你的任务是：
1.  **只返回翻译后的中文文本**。不要包含任何解释、标签或标点符号，例如不要说“翻译结果是：”或返回带引号的文本。
2.  **识别并翻译人名**：如果输入是 `Yoon Se-ri` 或 `Zhang San` 这样的拼音/罗马音，请尽力翻译成最通用的中文人名，例如“尹世理”或“张三”。
3.  **处理混合内容**：如果输入是 `Maj. Sophie E. Jean`，请翻译成“苏菲·E·让少校”，保留军衔等上下文。
4.  **保持原文**：如果输入的内容已经是中文，或者是一个你无法识别为有效人名/角色名的无意义词汇，请直接返回原文。
5.  **力求精准**：翻译结果必须追求“信、达、雅”，优先使用官方译名。
6.  **对于一些中国耳熟能详的如“MJ、DJ、M、Q”等超短大写英文名缩写，直接返回原文。"""

        if context_title:
            user_prompt = f"请根据影视作品《{context_title}》的上下文，翻译以下角色名：\n\n{text}"
        else:
            user_prompt = f"请翻译以下人名或角色名：\n\n{text}"

        payload = {
            "model": config.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "max_tokens": 100,
            "temperature": config.temperature,
            "top_p": config.top_p
        }
        headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
        
        response = requests.post(url, json=payload, headers=headers, timeout=config.timeout)
        response.raise_for_status()
        result = response.json()
        if result.get("choices") and len(result["choices"]) > 0:
            content = result["choices"][0].get("message", {}).get("content", "")
            return content.strip().strip('"\'')
        raise Exception(f"SiliconFlow API 响应格式不正确: {result}")

    def preview_actor_changes_task(self, target: TargetScope, config: ActorLocalizerConfig, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        logging.info("【演员中文化】预览任务启动...")
        if not self.douban_map:
            logging.error("【演员中文化】本地豆瓣数据库为空，任务中止。")
            task_manager.update_task_progress(task_id, 0, 0)
            return []

        logging.info("【演员中文化】阶段一：正在快速统计待处理的媒体项总数...")
        item_ids_to_process = self._get_item_ids_for_scanning(target, cancellation_event)
        
        if cancellation_event.is_set():
            logging.warning("【演员中文化】任务在计数阶段被取消。")
            return []

        total_items = len(item_ids_to_process)
        logging.info(f"【演员中文化】计数完成，共找到 {total_items} 个媒体项需要处理。")
        task_manager.update_task_progress(task_id, 0, total_items)

        if total_items == 0:
            logging.info("【演员中文化】没有需要处理的媒体项，任务结束。")
            return []

        logging.info("【演员中文化】阶段二：开始逐一处理媒体项...")
        items_to_update = []
        
        for index, item_id in enumerate(item_ids_to_process):
            if cancellation_event.is_set():
                break
            
            task_manager.update_task_progress(task_id, index + 1, total_items)

            details = self._get_item_details(item_id)
            if not details:
                continue
            
            item_name = details.get('Name', '未知名称')
            logging.info(f"【演员中文化】进度 {index + 1}/{total_items}: 正在处理 [{item_name}]")

            provider_ids = details.get('ProviderIds', {})
            douban_id = next((v for k, v in provider_ids.items() if k.lower() == 'douban'), None)

            if not douban_id:
                logging.debug(f"【演员中文化】跳过 [{item_name}]：缺少豆瓣ID。")
                continue
            
            people = details.get('People', [])
            if not any(not self._contains_chinese(p.get('Role', '')) for p in people):
                logging.debug(f"【演员中文化】跳过 [{item_name}]：所有角色名均已包含中文。")
                continue

            douban_item = self.douban_map.get(douban_id)
            if not douban_item:
                logging.warning(f"【演员中文化】处理 [{item_name}] 时，在本地找不到豆瓣ID {douban_id} 的数据。")
                continue

            emby_actors_to_match = {p['Name']: p.get('Role', '') for p in people[:config.person_limit] if p.get('Type') == 'Actor' and not self._contains_chinese(p.get('Role', ''))}
            
            douban_standard_roles = {actor.get('name'): self._clean_douban_character(actor.get('character', '')) for actor in douban_item.get('actors', []) if self._clean_douban_character(actor.get('character', '')) and self._contains_chinese(self._clean_douban_character(actor.get('character', '')))}

            new_people_list = copy.deepcopy(people)
            item_changes_log = {}
            unmatched_actors = []

            for emby_actor_name, original_role in emby_actors_to_match.items():
                if emby_actor_name in douban_standard_roles:
                    new_role = douban_standard_roles[emby_actor_name]
                    for person in new_people_list:
                        if person.get('Name') == emby_actor_name:
                            person['Role'] = new_role
                            break
                    item_changes_log[emby_actor_name] = {'old': original_role, 'new': new_role, 'source': 'douban'}
                    logging.info(f"     -- 预览更新: {emby_actor_name}: '{original_role}' -> '{new_role}' (来自豆瓣)")
                else:
                    unmatched_actors.append({'name': emby_actor_name, 'role': original_role})
            
            actors_to_process_further = unmatched_actors
            
            if config.translation_enabled:
                for actor_info in actors_to_process_further:
                    if cancellation_event.is_set(): break
                    
                    # --- 核心修改：将冷却逻辑放在这里 ---
                    if config.api_cooldown_enabled and config.api_cooldown_time > 0:
                        time.sleep(config.api_cooldown_time)
                    
                    translated_role = self._translate_text(actor_info['role'], config, context_title=item_name)
                    if translated_role and translated_role != actor_info['role']:
                        for person in new_people_list:
                            if person.get('Name') == actor_info['name']:
                                person['Role'] = translated_role
                                break
                        item_changes_log[actor_info['name']] = {'old': actor_info['role'], 'new': translated_role, 'source': 'translation'}
                        logging.info(f"     -- 预览更新: {actor_info['name']}: '{actor_info['role']}' -> '{translated_role}' (来自翻译)")
            
            elif config.replace_english_role:
                for actor_info in actors_to_process_further:
                    if self._is_pure_english(actor_info['role']):
                        new_role = "演员"
                        for person in new_people_list:
                            if person.get('Name') == actor_info['name']:
                                person['Role'] = new_role
                                break
                        item_changes_log[actor_info['name']] = {'old': actor_info['role'], 'new': new_role, 'source': 'replace'}
                        logging.info(f"     -- 预览更新: {actor_info['name']}: '{actor_info['role']}' -> '{new_role}' (来自替换)")

            if item_changes_log:
                change_detail = {'id': details['Id'], 'name': item_name, 'changes': item_changes_log, 'new_people': new_people_list}
                items_to_update.append(change_detail)
                task_manager.update_task_result(task_id, items_to_update)

        if cancellation_event.is_set():
            logging.warning("【演员中文化】预览任务被用户取消。")
        else:
            logging.info(f"【演员中文化】预览扫描完成，共处理 {total_items} 个项目，发现 {len(items_to_update)} 个可修改项。")
        
        return items_to_update

    def apply_actor_changes_task(self, items: List[Dict], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        total_items = len(items)
        task_manager.update_task_progress(task_id, 0, total_items)
        logging.info(f"【演员中文化】开始应用修改，共 {total_items} 个项目。")
        
        updated_count = 0
        for index, item_info in enumerate(items):
            if cancellation_event.is_set(): break
            
            item_id, item_name, new_people_list = item_info['id'], item_info['name'], item_info['new_people']
            task_manager.update_task_progress(task_id, index + 1, total_items)
            logging.info(f"【演员中文化】应用进度 {index + 1}/{total_items}: 正在更新 [{item_name}]")
            
            full_item_json = self._get_item_details(item_id, full_json=True)
            if not full_item_json:
                logging.error(f"【演员中文化】获取 '{item_name}' 完整信息失败，跳过更新。")
                continue
            
            full_item_json['People'] = new_people_list
            if self._update_item_on_server(item_id, full_item_json):
                logging.info(f"【演员中文化】成功更新 [{item_name}]，详情如下:")
                for actor, change in item_info.get('changes', {}).items():
                    source_map = {'douban': '(来自豆瓣)', 'replace': '(来自暴力替换)', 'translation': '(来自翻译引擎)'}
                    source_text = source_map.get(change.get('source'), '')
                    logging.info(f"    - {actor}: \"{change['old']}\" -> \"{change['new']}\" {source_text}")
                updated_count += 1
            else:
                 logging.error(f"【演员中文化】更新 '{item_name}' 失败。")

        if cancellation_event.is_set():
            logging.warning(f"【演员中文化】应用修改被用户取消。本次共更新 {updated_count} 个项目。")
        else:
            logging.info(f"【演员中文化】应用修改完成！共成功更新 {updated_count} 个项目。")
        
        return {"updated_count": updated_count}

    def apply_actor_changes_directly_task(self, config: ActorLocalizerConfig, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        logging.info("【演员中文化-自动任务】启动...")
        if not self.douban_map:
            logging.error("【演员中文化-自动任务】本地豆瓣数据库为空，任务中止。")
            return

        target = TargetScope(scope="all_libraries")
        item_ids_to_process = self._get_item_ids_for_scanning(target, cancellation_event)
        
        if cancellation_event.is_set(): return

        total_items = len(item_ids_to_process)
        logging.info(f"【演员中文化-自动任务】共找到 {total_items} 个媒体项需要处理。")
        task_manager.update_task_progress(task_id, 0, total_items)

        if total_items == 0:
            logging.info("【演员中文化-自动任务】没有需要处理的媒体项，任务结束。")
            return

        updated_count = 0
        for index, item_id in enumerate(item_ids_to_process):
            if cancellation_event.is_set(): break
            
            task_manager.update_task_progress(task_id, index + 1, total_items)

            details = self._get_item_details(item_id)
            if not details: continue
            
            item_name = details.get('Name', '未知名称')
            logging.debug(f"【演员中文化-自动任务】进度 {index + 1}/{total_items}: 正在处理 [{item_name}]")

            provider_ids = details.get('ProviderIds', {})
            douban_id = next((v for k, v in provider_ids.items() if k.lower() == 'douban'), None)
            
            if not douban_id: continue
            
            people = details.get('People', [])
            if not any(not self._contains_chinese(p.get('Role', '')) for p in people): continue

            douban_item = self.douban_map.get(douban_id)
            if not douban_item: continue

            emby_actors_to_match = {p['Name']: p.get('Role', '') for p in people[:config.person_limit] if p.get('Type') == 'Actor' and not self._contains_chinese(p.get('Role', ''))}
            douban_standard_roles = {actor.get('name'): self._clean_douban_character(actor.get('character', '')) for actor in douban_item.get('actors', []) if self._clean_douban_character(actor.get('character', '')) and self._contains_chinese(self._clean_douban_character(actor.get('character', '')))}

            new_people_list = copy.deepcopy(people)
            has_changes = False

            for emby_actor_name, original_role in emby_actors_to_match.items():
                new_role = None
                source = None
                if emby_actor_name in douban_standard_roles:
                    new_role = douban_standard_roles[emby_actor_name]
                    source = "豆瓣"
                elif config.translation_enabled:
                    # --- 核心修改：将冷却逻辑放在这里 ---
                    if config.api_cooldown_enabled and config.api_cooldown_time > 0:
                        time.sleep(config.api_cooldown_time)
                    translated_role = self._translate_text(original_role, config, context_title=item_name)
                    if translated_role and translated_role != original_role:
                        new_role = translated_role
                        source = "翻译"
                elif config.replace_english_role and self._is_pure_english(original_role):
                    new_role = "演员"
                    source = "替换"
                
                if new_role:
                    has_changes = True
                    for person in new_people_list:
                        if person.get('Name') == emby_actor_name:
                            person['Role'] = new_role
                            logging.info(f"  - 自动更新: [{item_name}] - {emby_actor_name}: '{original_role}' -> '{new_role}' (来自{source})")
                            break
            
            if has_changes:
                full_item_json = self._get_item_details(item_id, full_json=True)
                if full_item_json:
                    full_item_json['People'] = new_people_list
                    if self._update_item_on_server(item_id, full_item_json):
                        updated_count += 1
        
        logging.info(f"【演员中文化-自动任务】执行完毕，共更新了 {updated_count} 个项目的演员角色。")
        return {"updated_count": updated_count}