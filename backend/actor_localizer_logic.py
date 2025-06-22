# backend/actor_localizer_logic.py (修正后)

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
    # ... (除了 _process_single_item_for_localization 和 preview_actor_changes_task 之外的所有函数保持不变) ...
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

    def _translate_text_with_retry(self, text: str, config: ActorLocalizerConfig, context_title: Optional[str] = None) -> str:
        if not text: return ""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logging.warning(f"【翻译-单个】第 {attempt + 1}/{max_retries} 次重试翻译: '{text}'")
                if config.translation_mode == 'translators':
                    if ts is None: raise ImportError("translators 库未安装")
                    logging.info(f"【翻译-单个】[translators:{config.translator_engine}] 正在翻译: '{text}'")
                    return ts.translate_text(text, translator=config.translator_engine, to_language='zh')
                elif config.translation_mode == 'tencent':
                    logging.info(f"【翻译-单个】[腾讯云API] 正在翻译: '{text}'")
                    return self.translate_with_tencent_api(text, config.tencent_config)
                elif config.translation_mode == 'siliconflow':
                    logging.info(f"【翻译-单个】[SiliconFlow:{config.siliconflow_config.model_name}] 正在翻译: '{text}' (上下文: {context_title or '无'})")
                    return self.translate_with_siliconflow_api(text, config.siliconflow_config, context_title)
                return text
            except requests.exceptions.RequestException as e:
                logging.error(f"【翻译-单个】翻译 '{text}' 时发生网络错误 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt + 1 >= max_retries:
                    logging.error(f"【翻译-单个】已达到最大重试次数，放弃翻译 '{text}'。")
                    return text
            except Exception as e:
                logging.error(f"【翻译-单个】翻译 '{text}' 时发生不可重试的错误: {e}")
                return text
        return text

    def _translate_batch_with_retry(self, texts: List[str], config: ActorLocalizerConfig, context_title: Optional[str] = None) -> Optional[List[str]]:
        if not texts: return []
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logging.warning(f"【翻译-批量】第 {attempt + 1}/{max_retries} 次重试批量翻译 (共 {len(texts)} 项)...")
                if config.translation_mode == 'siliconflow':
                    logging.info(f"【翻译-批量】[SiliconFlow:{config.siliconflow_config.model_name}] 正在批量翻译 {len(texts)} 个角色名 (上下文: {context_title or '无'})")
                    logging.debug(f"【翻译-批量】请求内容: {texts}")
                    translated_texts = self.translate_with_siliconflow_api_batch(texts, config.siliconflow_config, context_title)
                    logging.debug(f"【翻译-批量】返回内容: {translated_texts}")
                    if len(translated_texts) != len(texts):
                        logging.error(f"【翻译-批量】严重错误：API返回结果数量 ({len(translated_texts)}) 与请求数量 ({len(texts)}) 不匹配！")
                        raise ValueError("Batch translation result count mismatch.")
                    logging.info(f"【翻译-批量】成功完成，返回 {len(translated_texts)} 个结果。")
                    return translated_texts
                else:
                    logging.warning(f"【翻译-批量】当前翻译模式 '{config.translation_mode}' 不支持批量翻译，将自动降级。")
                    return None
            except Exception as e:
                logging.error(f"【翻译-批量】批量翻译时发生错误 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt + 1 >= max_retries:
                    logging.error(f"【翻译-批量】已达到最大重试次数，批量翻译失败。")
                    return None
        return None

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
        actors_with_roles = [p for p in people if p.get('Type') == 'Actor' and p.get('Role')]
        if not any(not self._contains_chinese(p.get('Role', '')) for p in actors_with_roles):
            logging.debug(f"     -- 跳过，所有角色名均已包含中文或为空。")
            return False

        douban_item = self.douban_map.get(douban_id)
        if not douban_item:
            logging.warning(f"     -- 跳过，本地无豆瓣ID {douban_id} 的数据。")
            return False

        emby_actors_to_match = {p['Name']: p.get('Role', '') for p in people[:config.person_limit] if p.get('Type') == 'Actor' and p.get('Role') and not self._contains_chinese(p.get('Role', ''))}
        douban_standard_roles = {actor.get('name'): self._clean_douban_character(actor.get('character', '')) for actor in douban_item.get('actors', []) if self._clean_douban_character(actor.get('character', '')) and self._contains_chinese(self._clean_douban_character(actor.get('character', '')))}

        new_people_list = copy.deepcopy(people)
        has_changes = False
        
        actors_to_translate = []

        for emby_actor_name, original_role in emby_actors_to_match.items():
            new_role = None
            source = "豆瓣"
            if emby_actor_name in douban_standard_roles:
                new_role = douban_standard_roles[emby_actor_name]
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
            elif config.translation_enabled:
                actors_to_translate.append({'name': emby_actor_name, 'role': original_role})

        if config.translation_enabled and actors_to_translate:
            logging.info(f"【翻译】为媒体《{item_name}》收集到 {len(actors_to_translate)} 个待翻译角色。")
            
            use_batch = (config.translation_mode == 'siliconflow' and config.siliconflow_config.batch_translation_enabled)
            
            if use_batch:
                # 批量模式下，冷却一次
                if config.api_cooldown_enabled and config.api_cooldown_time > 0:
                    logging.info(f"【翻译】API冷却 (批量模式)，等待 {config.api_cooldown_time} 秒...")
                    time.sleep(config.api_cooldown_time)

                logging.info("【翻译】检测到批量翻译已开启，开始尝试批量处理...")
                original_roles = [actor['role'] for actor in actors_to_translate]
                translated_roles = self._translate_batch_with_retry(original_roles, config, item_name)
                
                if translated_roles:
                    logging.info("【翻译】批量翻译成功，开始应用结果。")
                    for i, actor_info in enumerate(actors_to_translate):
                        new_role = translated_roles[i]
                        if new_role and new_role != actor_info['role']:
                            has_changes = True
                            for person in new_people_list:
                                if person.get('Name') == actor_info['name']:
                                    person['Role'] = new_role
                                    break
                            logging.info(f"     -- 更新: {actor_info['name']}: '{actor_info['role']}' -> '{new_role}' (来自批量翻译)")
                        else:
                            logging.info(f"     -- 跳过: {actor_info['name']}: '{actor_info['role']}' -> '{new_role}' (无变化)")
                else:
                    logging.warning(f"【翻译降级】批量翻译失败，将为媒体《{item_name}》逐个尝试翻译...")
                    use_batch = False

            if not use_batch:
                for actor_info in actors_to_translate:
                    # --- 核心修改：将冷却逻辑移入单个翻译的循环内 ---
                    if config.api_cooldown_enabled and config.api_cooldown_time > 0:
                        logging.info(f"【翻译】API冷却 (单个模式)，等待 {config.api_cooldown_time} 秒...")
                        time.sleep(config.api_cooldown_time)
                    # --- 结束修改 ---

                    new_role = self._translate_text_with_retry(actor_info['role'], config, item_name)
                    if new_role and new_role != actor_info['role']:
                        has_changes = True
                        for person in new_people_list:
                            if person.get('Name') == actor_info['name']:
                                person['Role'] = new_role
                                break
                        logging.info(f"     -- 更新: {actor_info['name']}: '{actor_info['role']}' -> '{new_role}' (来自单个翻译)")
                    else:
                        logging.info(f"     -- 跳过: {actor_info['name']}: '{actor_info['role']}' -> '{new_role}' (无变化)")

        if has_changes:
            full_item_json = self._get_item_details(item_id, full_json=True)
            if full_item_json:
                full_item_json['People'] = new_people_list
                if self._update_item_on_server(item_id, full_item_json):
                    logging.info(f"     -- 成功应用更新到 Emby。")
                    return True
            logging.error(f"     -- 应用更新到 Emby 失败。")
        else:
            logging.info(f"     -- 处理完成，无任何变更。")
        
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
        response = requests.post(url, json=payload, headers=headers, timeout=config.timeout_single)
        response.raise_for_status()
        result = response.json()
        if result.get("choices") and len(result["choices"]) > 0:
            content = result["choices"][0].get("message", {}).get("content", "")
            return content.strip().strip('"\'')
        raise Exception(f"SiliconFlow API 响应格式不正确: {result}")

    @staticmethod
    def translate_with_siliconflow_api_batch(texts: List[str], config: SiliconflowApiConfig, context_title: Optional[str] = None) -> List[str]:
        url = "https://api.siliconflow.cn/v1/chat/completions"
        system_prompt = """你是一个严格遵守指令的、用于程序化调用的翻译API。你的核心任务是将一个包含多个角色名的JSON数组，翻译成一个包含对应中文译名的、新的JSON数组。

**严格遵守以下规则：**

1.  **输入格式**：你将收到的用户输入是一个JSON字符串数组，例如 `["Role A", "Role B", "Role C"]`。
2.  **输出格式**：你的回答【必须】是且【仅是】一个合法的、与输入数组一一对应的JSON字符串数组。绝对不能包含任何解释、代码块标记（如 ```json ... ```）、或其他任何非JSON数组内容的文本。
3.  **等长原则**：输出数组的元素数量【必须】严格等于输入数组的元素数量。
4.  **顺序原则**：输出数组中元素的顺序【必须】严格对应输入数组中元素的顺序。第 `i` 个输出是第 `i` 个输入的翻译结果。
5.  **翻译核心**：
    *   **精准翻译**：将英文或拼音格式的人名和角色名，翻译成符合中文影视圈习惯的、最常见的官方或通用译名。
    *   **保留上下文**：如果输入是 `Maj. Sophie E. Jean`，请翻译成“苏菲·E·让少校”。
    *   **保持原文**：如果输入已经是中文、无法识别为人名/角色名、或者是常见的英文缩写（如 MJ, DJ, CEO），请在输出数组的对应位置直接返回原始文本。
6.  **示例**：
    *   如果输入是：`["Yoon Se-ri", "The President", "DJ"]`
    *   你的输出必须是：`["尹世理", "总统", "DJ"]`

**错误输出示例（你绝不能这样返回）：**
*   `翻译结果如下：["尹世理", "总统", "DJ"]`  (包含多余文本)
*   `["尹世理", "总统"]` (数量不匹配)
*   `["总统", "尹世理", "DJ"]` (顺序不匹配)
*   `"尹世理", "总统", "DJ"` (不是合法的JSON数组格式)"""
        roles_json_array = json.dumps(texts, ensure_ascii=False)
        if context_title:
            user_prompt = f"请根据影视作品《{context_title}》的上下文，严格按照系统指令的要求，翻译以下JSON数组中的所有角色名：\n\n{roles_json_array}"
        else:
            user_prompt = f"请严格按照系统指令的要求，翻译以下JSON数组中的所有角色名：\n\n{roles_json_array}"
        payload = {
            "model": config.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "max_tokens": len(roles_json_array) * 2 + 500,
            "temperature": config.temperature,
            "top_p": config.top_p
        }
        headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
        response = requests.post(url, json=payload, headers=headers, timeout=config.timeout_batch)
        response.raise_for_status()
        result = response.json()
        if result.get("choices") and len(result["choices"]) > 0:
            content = result["choices"][0].get("message", {}).get("content", "")
            try:
                translated_list = json.loads(content)
                if isinstance(translated_list, list):
                    return translated_list
                else:
                    raise ValueError("API返回的不是一个列表。")
            except (json.JSONDecodeError, ValueError) as e:
                logging.error(f"【翻译-批量】解析API返回的JSON数组失败: {e}。返回内容: {content}")
                raise ValueError(f"Failed to parse batch translation response: {content}") from e
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
            if cancellation_event.is_set(): break
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
            if not any(not self._contains_chinese(p.get('Role', '')) for p in people if p.get('Role')):
                logging.debug(f"【演员中文化】跳过 [{item_name}]：所有角色名均已包含中文或为空。")
                continue
            douban_item = self.douban_map.get(douban_id)
            if not douban_item:
                logging.warning(f"【演员中文化】处理 [{item_name}] 时，在本地找不到豆瓣ID {douban_id} 的数据。")
                continue
            emby_actors_to_match = {p['Name']: p.get('Role', '') for p in people[:config.person_limit] if p.get('Type') == 'Actor' and p.get('Role') and not self._contains_chinese(p.get('Role', ''))}
            douban_standard_roles = {actor.get('name'): self._clean_douban_character(actor.get('character', '')) for actor in douban_item.get('actors', []) if self._clean_douban_character(actor.get('character', '')) and self._contains_chinese(self._clean_douban_character(actor.get('character', '')))}
            new_people_list = copy.deepcopy(people)
            item_changes_log = {}
            actors_to_process_further = []
            for emby_actor_name, original_role in emby_actors_to_match.items():
                if emby_actor_name in douban_standard_roles:
                    new_role = douban_standard_roles[emby_actor_name]
                    item_changes_log[emby_actor_name] = {'old': original_role, 'new': new_role, 'source': 'douban'}
                    logging.info(f"     -- 预览更新: {emby_actor_name}: '{original_role}' -> '{new_role}' (来自豆瓣)")
                else:
                    actors_to_process_further.append({'name': emby_actor_name, 'role': original_role})
            if config.replace_english_role:
                for actor_info in actors_to_process_further:
                    if self._is_pure_english(actor_info['role']):
                        new_role = "演员"
                        item_changes_log[actor_info['name']] = {'old': actor_info['role'], 'new': new_role, 'source': 'replace'}
                        logging.info(f"     -- 预览更新: {actor_info['name']}: '{actor_info['role']}' -> '{new_role}' (来自替换)")
            elif config.translation_enabled and actors_to_process_further:
                use_batch = (config.translation_mode == 'siliconflow' and config.siliconflow_config.batch_translation_enabled)
                if use_batch:
                    if config.api_cooldown_enabled and config.api_cooldown_time > 0:
                        logging.info(f"【翻译】API冷却 (批量模式)，等待 {config.api_cooldown_time} 秒...")
                        time.sleep(config.api_cooldown_time)
                    original_roles = [actor['role'] for actor in actors_to_process_further]
                    translated_roles = self._translate_batch_with_retry(original_roles, config, item_name)
                    if translated_roles:
                        for i, actor_info in enumerate(actors_to_process_further):
                            new_role = translated_roles[i]
                            if new_role and new_role != actor_info['role']:
                                item_changes_log[actor_info['name']] = {'old': actor_info['role'], 'new': new_role, 'source': 'translation'}
                                logging.info(f"     -- 预览更新: {actor_info['name']}: '{actor_info['role']}' -> '{new_role}' (来自批量翻译)")
                            else:
                                logging.info(f"     -- 预览跳过: {actor_info['name']}: '{actor_info['role']}' -> '{new_role}' (无变化)")
                    else:
                        use_batch = False
                if not use_batch:
                    for actor_info in actors_to_process_further:
                        if cancellation_event.is_set(): break
                        if config.api_cooldown_enabled and config.api_cooldown_time > 0:
                            logging.info(f"【翻译】API冷却 (单个模式)，等待 {config.api_cooldown_time} 秒...")
                            time.sleep(config.api_cooldown_time)
                        new_role = self._translate_text_with_retry(actor_info['role'], config, context_title=item_name)
                        if new_role and new_role != actor_info['role']:
                            item_changes_log[actor_info['name']] = {'old': actor_info['role'], 'new': new_role, 'source': 'translation'}
                            logging.info(f"     -- 预览更新: {actor_info['name']}: '{actor_info['role']}' -> '{new_role}' (来自单个翻译)")
                        else:
                            logging.info(f"     -- 预览跳过: {actor_info['name']}: '{actor_info['role']}' -> '{new_role}' (无变化)")
            if item_changes_log:
                for person in new_people_list:
                    if person.get('Name') in item_changes_log:
                        person['Role'] = item_changes_log[person['Name']]['new']
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
            if self._process_single_item_for_localization(item_id, config):
                updated_count += 1
        logging.info(f"【演员中文化-自动任务】执行完毕，共更新了 {updated_count} 个项目的演员角色。")
        return {"updated_count": updated_count}