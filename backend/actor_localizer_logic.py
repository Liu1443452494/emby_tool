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
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import translators as ts
except ImportError:
    logging.warning("【演员中文化】'translators' 库未安装，基于此库的“第三方库”翻译模式将不可用。如需使用，请在 backend 目录下运行 'pip install translators' 并重启服务。")
    ts = None

from models import AppConfig, ActorLocalizerConfig, TargetScope, TencentApiConfig, SiliconflowApiConfig
from task_manager import TaskManager
from douban_manager import DOUBAN_CACHE_FILE
from log_manager import ui_logger
from actor_role_mapper_logic import ActorRoleMapperLogic

DEFAULT_ROLE_SUFFIX_MAP = {
    "(voice)": "配 ",
    "(配音)": "配 "
}

# backend/actor_localizer_logic.py (函数替换)

def _format_role_with_rules(role: str, final_rules: Dict[str, str]) -> str:
    """
    根据最终规则集，格式化角色名。
    新增了对全角括号的归一化处理。
    """
    if not role or not final_rules:
        return role

    # --- 新增/修改：在匹配前，先对角色名进行归一化处理 ---
    # 将全角括号替换为半角括号，并去除前后可能存在的空格
    normalized_role = role.strip().replace('（', '(').replace('）', ')')
    # --- 新增/修改结束 ---

    # 按后缀长度降序排序，优先匹配更长的后缀，避免 "(voice actor)" 被 "(voice)" 错误匹配
    sorted_rules = sorted(final_rules.items(), key=lambda item: len(item[0]), reverse=True)

    for suffix, prefix in sorted_rules:
        # --- 修改：使用归一化后的角色名进行匹配 ---
        if normalized_role.endswith(suffix):
            # 从原始role字符串中截取，以保留原始的大小写等信息
            base_role = role[:-len(suffix)].strip()
            # --- 修改结束 ---
            formatted_role = f"{prefix}{base_role}"
            logging.debug(f"【角色格式化】规则匹配: '{role}' -> '{formatted_role}' (规则: {suffix} -> {prefix})")
            return formatted_role
    
    return role

class ActorLocalizerLogic:
    def __init__(self, app_config: AppConfig):
        self.server_config = app_config.server_config
        self.base_url = self.server_config.server
        self.api_key = self.server_config.api_key
        self.user_id = self.server_config.user_id
        self.params = {"api_key": self.api_key}
        self.douban_map = self._load_douban_data()

    def _load_douban_data(self) -> Dict:
        task_cat = "演员中文化-初始化" # --- 统一任务类别 ---
        if not os.path.exists(DOUBAN_CACHE_FILE):
            ui_logger.warning("未找到豆瓣缓存文件，匹配功能将无法使用。", task_category=task_cat)
            return {}
        try:
            with open(DOUBAN_CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            ui_logger.info(f"成功加载 {len(data)} 条豆瓣缓存数据。", task_category=task_cat)
            return data
        except Exception as e:
            ui_logger.error(f"加载豆瓣缓存文件失败: {e}", task_category=task_cat)
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
        
    def _rename_person_item(self, person_id: str, old_name: str, new_name: str, task_category: str) -> bool:
        """
        通过独立的 API 请求，直接重命名一个演员（Person）Item。
        此函数逻辑参考了 actor_gallery_logic.py 中已验证的成功实现。
        """
        try:
            # 步骤 1: 获取演员的当前信息。注意：这里不使用 _get_item_details，而是直接请求。
            person_url = f"{self.base_url}/Users/{self.user_id}/Items/{person_id}"
            person_details_resp = requests.get(person_url, params=self.params, timeout=15)
            person_details_resp.raise_for_status()
            person_details = person_details_resp.json()

            # 检查是否需要更新
            if person_details.get("Name") == new_name:
                ui_logger.debug(f"     -- 跳过重命名，演员 '{old_name}' 的名称已经是 '{new_name}'。", task_category=task_category)
                return True # 认为操作成功，因为它已经达到了目标状态

            # 步骤 2: 修改名称并准备提交
            person_details['Name'] = new_name
            
            # 步骤 3: 使用 /Items/{Id} 端点提交完整的对象
            update_url = f"{self.base_url}/Items/{person_id}"
            headers = {'Content-Type': 'application/json'}
            
            resp = requests.post(update_url, params=self.params, json=person_details, headers=headers, timeout=30)
            resp.raise_for_status()
            
            if resp.status_code == 204:
                ui_logger.info(f"     -- ✅ 演员名修正: '{old_name}' -> '{new_name}' (已通过API独立更新)", task_category=task_category)
                return True
            else:
                ui_logger.warning(f"     -- ⚠️ 演员重命名请求已发送，但服务器返回状态码 {resp.status_code}，可能未成功。", task_category=task_category)
                return False

        except requests.RequestException as e:
            ui_logger.error(f"     -- ❌ 演员重命名API请求失败: {e}", task_category=task_category)
            return False
        except Exception as e:
            ui_logger.error(f"     -- ❌ 演员重命名时发生未知错误: {e}", task_category=task_category, exc_info=True)
            return False

    def _translate_text_with_retry(self, text: str, config: ActorLocalizerConfig, context_info: Optional[Dict[str, Any]] = None) -> str:
        task_cat = f"翻译引擎({config.translation_mode})" # --- 定义任务类别 ---
        if not text: return ""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    ui_logger.warning(f"第 {attempt + 1}/{max_retries} 次重试翻译: '{text}'", task_category=task_cat)
                if config.translation_mode == 'translators':
                    if ts is None: raise ImportError("translators 库未安装")
                    ui_logger.debug(f"[translators:{config.translator_engine}] 正在翻译: '{text}'", task_category=task_cat)
                    return ts.translate_text(text, translator=config.translator_engine, to_language='zh')
                elif config.translation_mode == 'tencent':
                    ui_logger.debug(f"[腾讯云API] 正在翻译: '{text}'", task_category=task_cat)
                    return self.translate_with_tencent_api(text, config.tencent_config)
                elif config.translation_mode == 'siliconflow':
                    # --- 修改：传递更丰富的上下文 ---
                    context_log = context_info.get('title', '无') if context_info else '无'
                    ui_logger.debug(f"[SiliconFlow:{config.siliconflow_config.model_name}] 正在翻译: '{text}' (上下文: {context_log})", task_category=task_cat)
                    return self.translate_with_siliconflow_api(text, config.siliconflow_config, context_info)
                    # --- 修改结束 ---
                return text
            except requests.exceptions.RequestException as e:
                ui_logger.error(f"翻译 '{text}' 时发生网络错误 (尝试 {attempt + 1}/{max_retries}): {e}", task_category=task_cat)
                if attempt + 1 >= max_retries:
                    ui_logger.error(f"已达到最大重试次数，放弃翻译 '{text}'。", task_category=task_cat)
                    return text
            except Exception as e:
                ui_logger.error(f"翻译 '{text}' 时发生不可重试的错误: {e}", task_category=task_cat)
                return text
        return text

    def _translate_batch_with_retry(self, texts: List[str], config: ActorLocalizerConfig, context_info: Optional[Dict[str, Any]] = None) -> Optional[List[str]]:
        task_cat = f"翻译引擎({config.translation_mode})" # --- 定义任务类别 ---
        if not texts: return []
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    ui_logger.warning(f"第 {attempt + 1}/{max_retries} 次重试批量翻译 (共 {len(texts)} 项)...", task_category=task_cat)
                if config.translation_mode == 'siliconflow':
                    # --- 修改：传递更丰富的上下文 ---
                    context_log = context_info.get('title', '无') if context_info else '无'
                    ui_logger.debug(f"[SiliconFlow:{config.siliconflow_config.model_name}] 正在批量翻译 {len(texts)} 个角色名 (上下文: {context_log})", task_category=task_cat)
                    logging.debug(f"【翻译-批量】请求内容: {texts}") # 保留底层详细日志
                    translated_texts = self.translate_with_siliconflow_api_batch(texts, config.siliconflow_config, context_info)
                    # --- 修改结束 ---
                    logging.debug(f"【翻译-批量】返回内容: {translated_texts}") # 保留底层详细日志
                    if len(translated_texts) != len(texts):
                        ui_logger.error(f"严重错误：API返回结果数量 ({len(translated_texts)}) 与请求数量 ({len(texts)}) 不匹配！", task_category=task_cat)
                        raise ValueError("Batch translation result count mismatch.")
                    ui_logger.info(f"批量翻译成功，返回 {len(translated_texts)} 个结果。", task_category=task_cat)
                    return translated_texts
                else:
                    ui_logger.warning(f"当前翻译模式 '{config.translation_mode}' 不支持批量翻译，将自动降级。", task_category=task_cat)
                    return None
            except Exception as e:
                ui_logger.error(f"批量翻译时发生错误 (尝试 {attempt + 1}/{max_retries}): {e}", task_category=task_cat)
                if attempt + 1 >= max_retries:
                    ui_logger.error(f"已达到最大重试次数，批量翻译失败。", task_category=task_cat)
                    return None
        return None
    

    # backend/actor_localizer_logic.py (函数替换)

    def _process_single_item_for_localization(self, item_id: str, config: ActorLocalizerConfig, task_category: str, preview_mode: bool = False) -> Dict[str, Any]:
        details = self._get_item_details(item_id)
        if not details: return {"has_changes": False}
        
        item_name = details.get('Name', '未知名称')
        if not preview_mode:
            ui_logger.info(f"  -> 正在处理: [{item_name}] (ID: {item_id})", task_category=task_category)

        provider_ids = details.get('ProviderIds', {})
        douban_id = next((v for k, v in provider_ids.items() if k.lower() == 'douban'), None)
        
        if not douban_id:
            if not preview_mode: ui_logger.debug(f"     -- 跳过，无豆瓣ID。", task_category=task_category)
            return {"has_changes": False}
        
        people = details.get('People', [])
        if not people:
            if not preview_mode: ui_logger.debug(f"     -- 跳过，无演职员信息。", task_category=task_category)
            return {"has_changes": False}

        douban_item = self.douban_map.get(douban_id)
        if not douban_item:
            if not preview_mode: ui_logger.warning(f"     -- 跳过，本地无豆瓣ID {douban_id} 的数据。", task_category=task_category)
            return {"has_changes": False}

        douban_actor_map = {}
        for actor in douban_item.get('actors', []):
            chinese_name = actor.get('name')
            latin_name = actor.get('latin_name')
            role = self._clean_douban_character(actor.get('character', ''))
            
            info_package = {"name": chinese_name, "role": role}
            
            if chinese_name:
                douban_actor_map[chinese_name] = info_package
            
            if latin_name:
                latin_name_lower = latin_name.lower()
                douban_actor_map[latin_name_lower] = info_package
                
                parts = latin_name.split()
                if len(parts) == 2:
                    reversed_latin_name_lower = f"{parts[1]} {parts[0]}".lower()
                    douban_actor_map[reversed_latin_name_lower] = info_package

        all_actors = [p for p in people if p.get('Type') == 'Actor']
        
        actors_to_process = all_actors[:config.person_limit]
        if len(all_actors) > config.person_limit and not preview_mode:
            ui_logger.debug(f"     -- [演员裁切] 演员总数: {len(all_actors)}，根据设置将处理前 {config.person_limit} 位。", task_category=task_category)
        
        new_people_list = copy.deepcopy(actors_to_process)

        has_changes = False
        actors_to_translate = []
        item_changes_log = {}
        
        actor_source_map = {}

        for person in new_people_list:
            if person.get('Type') != 'Actor':
                continue

            emby_actor_name = person.get('Name')
            original_role = person.get('Role', '')
            current_role = original_role
            source_text = ""

            matched_douban_actor = douban_actor_map.get(emby_actor_name)
            if not matched_douban_actor:
                matched_douban_actor = douban_actor_map.get(emby_actor_name.lower())

            if matched_douban_actor:
                correct_chinese_name = matched_douban_actor.get('name')
                if correct_chinese_name and emby_actor_name != correct_chinese_name:
                    person_id = person.get('Id')
                    if person_id:
                        has_changes = True
                        person['Name'] = correct_chinese_name
                        actor_source_map[correct_chinese_name] = "(来自豆瓣)"
                        if preview_mode:
                            item_changes_log[emby_actor_name] = {'old_name': emby_actor_name, 'new_name': correct_chinese_name, 'source': '(来自豆瓣)'}
                        else:
                            ui_logger.info(f"     -- 演员名待修正: '{emby_actor_name}' -> '{correct_chinese_name}' (来自豆瓣)", task_category=task_category)
                    elif not preview_mode:
                        ui_logger.warning(f"     -- ⚠️ 演员 '{emby_actor_name}' 需要重命名，但无法获取其在Emby中的ID，跳过重命名。", task_category=task_category)
            
            current_actor_name_for_log = person.get('Name', emby_actor_name)
            douban_role = matched_douban_actor.get('role') if matched_douban_actor else None

            is_voice_special_case = self._contains_chinese(current_role) and current_role.endswith("(voice)")
            
            if not self._contains_chinese(current_role) or is_voice_special_case:
                is_valid_douban_chinese_role = douban_role and self._contains_chinese(douban_role)
                if is_valid_douban_chinese_role:
                    if config.ignore_generic_douban_roles and douban_role.strip() in config.generic_role_blacklist:
                        if not preview_mode: ui_logger.debug(f"     -- 忽略豆瓣通用角色名: {current_actor_name_for_log}: '{douban_role}' (在黑名单中)", task_category=task_category)
                    else:
                        current_role = douban_role
                        source_text = "(来自豆瓣)"
                
                if not source_text and config.enhance_english_role_with_douban and douban_role and not self._contains_chinese(douban_role):
                    clean_douban_role = douban_role.strip()
                    clean_original_role = original_role.strip()

                    if clean_douban_role != clean_original_role:
                        # 核心判断：只有当豆瓣角色名更长时才进行替换
                        if len(clean_douban_role) > len(clean_original_role):
                            current_role = douban_role  # 使用原始的 douban_role 以保留可能存在的内部空格
                            source_text = "(来自豆瓣英文优化)"
                            logging.debug(f"     -- [英文优化] 采纳豆瓣角色: '{douban_role}' (长度 {len(clean_douban_role)}) > '{original_role}' (长度 {len(clean_original_role)})")
                        else:
                            logging.debug(f"     -- [英文优化] 放弃豆瓣角色: '{douban_role}' (长度 {len(clean_douban_role)}) <= '{original_role}' (长度 {len(clean_original_role)})")

            if source_text != "(来自豆瓣)" and self._contains_chinese(current_role):
                SUFFIX_MAP = {"(voice)": "配 "}
                for suffix, prefix in SUFFIX_MAP.items():
                    if current_role.endswith(suffix):
                        current_role = prefix + current_role[:-len(suffix)].strip()
                        if not source_text:
                            source_text = "(来自后缀格式化)"
                        break
            
            if not self._contains_chinese(current_role):
                if config.translation_enabled and current_role:
                    actors_to_translate.append({'name': current_actor_name_for_log, 'role': current_role})
                elif config.replace_english_role and self._is_pure_english(current_role):
                    current_role = "演员"
                    source_text = "(来自暴力替换)"
            
            if original_role.strip() != current_role.strip():
                if not preview_mode: ui_logger.info(f"     -- 角色名更新: {current_actor_name_for_log}: '{original_role}' -> '{current_role}' {source_text}", task_category=task_category)
                person['Role'] = current_role
                has_changes = True
                # --- 核心修正：预览时也存入完整的日志字符串 ---
                item_changes_log[current_actor_name_for_log] = {'old': original_role, 'new': current_role, 'source': source_text}
                actor_source_map[current_actor_name_for_log] = source_text

        if config.translation_enabled and actors_to_translate:
            if not preview_mode: ui_logger.info(f"【翻译】为媒体《{item_name}》收集到 {len(actors_to_translate)} 个待翻译角色。", task_category=task_category)
            
            provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
            context_info = {
                "title": item_name,
                "year": details.get("ProductionYear"),
                "type": "电视剧" if details.get("Type") == "Series" else "电影",
                "tmdb_id": provider_ids_lower.get("tmdb")
            }

            use_batch = (config.translation_mode == 'siliconflow' and config.siliconflow_config.batch_translation_enabled)
            
            if use_batch:
                if not preview_mode and config.api_cooldown_enabled and config.api_cooldown_time > 0:
                    ui_logger.debug(f"【翻译】API冷却 (批量模式)，等待 {config.api_cooldown_time} 秒...", task_category=task_category)
                    time.sleep(config.api_cooldown_time)

                if not preview_mode: ui_logger.info("【翻译】检测到批量翻译已开启，开始尝试批量处理...", task_category=task_category)
                
                unique_roles_to_translate = sorted(list(set([actor['role'] for actor in actors_to_translate])))
                translated_roles_map = {}
                
                translated_unique_roles = self._translate_batch_with_retry(unique_roles_to_translate, config, context_info)
                
                if translated_unique_roles and len(translated_unique_roles) == len(unique_roles_to_translate):
                    if not preview_mode: ui_logger.info("【翻译】批量翻译成功，开始构建映射并应用结果。", task_category=task_category)
                    translated_roles_map = {unique_roles_to_translate[i]: translated_unique_roles[i] for i in range(len(unique_roles_to_translate))}
                    
                    for person in new_people_list:
                        original_role_for_person = next((a['role'] for a in actors_to_translate if a['name'] == person.get('Name') and a['role'] == person.get('Role')), None)
                        if original_role_for_person and original_role_for_person in translated_roles_map:
                            new_role = translated_roles_map[original_role_for_person]
                            if new_role and new_role != original_role_for_person:
                                has_changes = True
                                if not preview_mode: ui_logger.info(f"     -- 更新: {person.get('Name')}: '{original_role_for_person}' -> '{new_role}' (来自批量翻译)", task_category=task_category)
                                person['Role'] = new_role
                                item_changes_log[person.get('Name')] = {'old': original_role_for_person, 'new': new_role, 'source': '(来自翻译引擎)'}
                                actor_source_map[person.get('Name')] = '(来自翻译引擎)'
                            elif not preview_mode:
                                ui_logger.debug(f"     -- 跳过: {person.get('Name')}: '{original_role_for_person}' -> '{new_role}' (无变化)", task_category=task_category)
                else:
                    if not preview_mode: ui_logger.warning(f"【翻译降级】批量翻译失败，将为媒体《{item_name}》逐个尝试翻译...", task_category=task_category)
                    use_batch = False

            if not use_batch:
                for actor_info in actors_to_translate:
                    if not preview_mode and config.api_cooldown_enabled and config.api_cooldown_time > 0:
                        ui_logger.debug(f"【翻译】API冷却 (单个模式)，等待 {config.api_cooldown_time} 秒...", task_category=task_category)
                        time.sleep(config.api_cooldown_time)

                    new_role = self._translate_text_with_retry(actor_info['role'], config, context_info)
                    if new_role and new_role != actor_info['role']:
                        has_changes = True
                        for person in new_people_list:
                            if person.get('Name') == actor_info['name'] and person.get('Role') == actor_info['role']:
                                person['Role'] = new_role
                                if not preview_mode: ui_logger.info(f"     -- 更新: {actor_info['name']}: '{actor_info['role']}' -> '{new_role}' (来自单个翻译)", task_category=task_category)
                                item_changes_log[actor_info['name']] = {'old': actor_info['role'], 'new': new_role, 'source': '(来自翻译引擎)'}
                                actor_source_map[actor_info['name']] = '(来自翻译引擎)'
                                break
                    elif not preview_mode:
                        ui_logger.debug(f"     -- 跳过: {actor_info['name']}: '{actor_info['role']}' -> '{new_role}' (无变化)", task_category=task_category)

        final_suffix_map = DEFAULT_ROLE_SUFFIX_MAP.copy()
        if config.custom_role_suffix_map:
            final_suffix_map.update(config.custom_role_suffix_map)

        if any(final_suffix_map): # 仅当有规则时才执行
            if not preview_mode:
                ui_logger.info("     --  aplicando regras de formatação final...", task_category=task_category)
            
            for person in new_people_list:
                actor_name_for_log = person.get('Name')
                original_role_before_format = person.get('Role', '')
                formatted_role = _format_role_with_rules(original_role_before_format, final_suffix_map)

                if formatted_role != original_role_before_format:
                    person['Role'] = formatted_role
                    
                    # 同步更新状态和日志
                    if not has_changes: has_changes = True

                    # 如果之前已有变更日志，则更新 new 值；否则创建新的日志条目
                    if actor_name_for_log in item_changes_log:
                        # 记录格式化前的角色名，以便日志更清晰
                        role_before_format_in_log = item_changes_log[actor_name_for_log]['new']
                        item_changes_log[actor_name_for_log]['new'] = formatted_role
                        if not preview_mode:
                             ui_logger.info(f"       - [格式化] {actor_name_for_log}: '{role_before_format_in_log}' -> '{formatted_role}'")
                    else:
                        # 这种情况发生在原始角色名本身就匹配了格式化规则
                        original_role_from_emby = next((p.get('Role', '') for p in actors_to_process if p.get('Id') == person.get('Id')), '')
                        item_changes_log[actor_name_for_log] = {'old': original_role_from_emby, 'new': formatted_role, 'source': '(来自后缀格式化)'}
                        if not preview_mode:
                            ui_logger.info(f"     -- 角色名更新: {actor_name_for_log}: '{original_role_from_emby}' -> '{formatted_role}' (来自后缀格式化)", task_category=task_category)

                    # 更新来源信息
                    actor_source_map[actor_name_for_log] = '(来自后缀格式化)'


        if preview_mode:
            return {
                "has_changes": has_changes,
                "details": details,
                "item_changes_log": item_changes_log,
                "new_people_list": new_people_list
            }

        if has_changes:
            ui_logger.info(f"     -- 🔍 检测到变更，开始构建内存映射并调用恢复逻辑...", task_category=task_category)
            
            provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
            tmdb_id = provider_ids_lower.get("tmdb")
            item_type = details.get("Type")

            if not tmdb_id or not item_type:
                ui_logger.error(f"     -- ❌ 无法构建映射，媒体【{item_name}】缺少 TMDB ID 或媒体类型，跳过应用。", task_category=task_category)
                return {"has_changes": False}

            work_map = {}
            person_ids_to_fetch = [p.get("Id") for p in new_people_list if p.get("Id")]
            person_details_map = {}

            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_person_id = {executor.submit(self._get_item_details, person_id, full_json=True): person_id for person_id in person_ids_to_fetch}
                for future in as_completed(future_to_person_id):
                    person_id = future_to_person_id[future]
                    try:
                        person_details_map[person_id] = future.result()
                    except Exception as e:
                        logging.debug(f"【演员中文化-获取TMDBID】获取演员 {person_id} 详情失败: {e}")

            for person in new_people_list:
                actor_name = person.get("Name")
                if not actor_name: continue

                person_tmdb_id = None
                person_full_details = person_details_map.get(person.get("Id"))
                if person_full_details:
                    p_ids = person_full_details.get("ProviderIds", {})
                    p_ids_lower = {k.lower(): v for k, v in p_ids.items()}
                    person_tmdb_id = p_ids_lower.get("tmdb")
                
                work_map[actor_name] = {
                    "tmdb_id": person_tmdb_id,
                    "role": person.get("Role", ""),
                    "source": actor_source_map.get(actor_name)
                }
            
            if work_map:
                try:
                    full_app_config = AppConfig(server_config=self.server_config)
                    role_mapper_logic = ActorRoleMapperLogic(full_app_config)
                    
                    role_mapper_logic.restore_single_map_task(
                        item_ids=[item_id],
                        role_map=work_map,
                        title=item_name,
                        cancellation_event=threading.Event(),
                        task_id=None,
                        task_manager=None,
                        task_category=task_category
                    )
                    return {"has_changes": True}
                except Exception as e:
                    ui_logger.error(f"     -- ❌ 调用角色恢复逻辑时发生错误: {e}", task_category=task_category, exc_info=True)
                    return {"has_changes": False}
            else:
                ui_logger.warning("     -- 映射构建为空，跳过应用。", task_category=task_category)

        else:
            ui_logger.info(f"     -- 处理完成，无任何变更。", task_category=task_category)

        return {"has_changes": False}

    def run_localization_for_items(self, item_ids: Iterable[str], config: ActorLocalizerConfig, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager, task_category: str):
        if not self.douban_map:
            ui_logger.error("【演员中文化】本地豆瓣数据库为空，任务中止。", task_category=task_category)
            return
        item_ids_list = list(item_ids)
        total_items = len(item_ids_list)
        ui_logger.info(f"【步骤 1/2】任务启动，共需处理 {total_items} 个媒体项。", task_category=task_category)
        task_manager.update_task_progress(task_id, 0, total_items)
        if total_items == 0:
            ui_logger.info("没有需要处理的媒体项，任务结束。", task_category=task_category)
            return
        updated_count = 0
        for index, item_id in enumerate(item_ids_list):
            if cancellation_event.is_set():
                ui_logger.warning("任务被用户取消。", task_category=task_category)
                break
            task_manager.update_task_progress(task_id, index + 1, total_items)
            # --- 修改 ---
            result = self._process_single_item_for_localization(item_id, config, task_category)
            if result.get("has_changes"):
            # --- 修改结束 ---
                updated_count += 1
        ui_logger.info(f"【步骤 2/2】任务执行完毕，共更新了 {updated_count} 个项目的演员角色。", task_category=task_category)
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
    def translate_with_siliconflow_api(text: str, config: SiliconflowApiConfig, context_info: Optional[Dict[str, Any]] = None) -> str:
        url = "https://api.siliconflow.cn/v1/chat/completions"
        system_prompt = """你是一位专业的影视剧翻译专家，尤其擅长将英文或拼音格式的人名和角色名，翻译成符合中文影视圈习惯的、最常见的官方或通用译名。

你的任务是：
1.  **只返回翻译后的中文文本**。不要包含任何解释、标签或标点符号，例如不要说“翻译结果是：”或返回带引号的文本。
2.  **识别并翻译人名**：如果输入是 `Yoon Se-ri` 或 `Zhang San` 这样的拼音/罗马音，请尽力翻译成最通用的中文人名，例如“尹世理”或“张三”。
3.  **处理混合内容**：如果输入是 `Maj. Sophie E. Jean`，请翻译成“苏菲·E·让少校”，保留军衔等上下文。
4.  **保持原文**：如果输入的内容已经是中文，或者是一个你无法识别为有效人名/角色名的无意义词汇，请直接返回原文。
5.  **力求精准**：翻译结果必须追求“信、达、雅”，优先使用官方译名。
6.  **对于一些中国耳熟能详的如“MJ、DJ、M、Q”等超短大写英文名缩写，直接返回原文。
7.  **上下文优先原则 (重要)**：
    *   你必须**优先利用**我提供给你的影视作品上下文来决定译名。如果该作品有公认的官方或通用译名，你必须使用它。
    *   **示例**：在电影《极乐空间》的上下文中，角色代号 `Spider` 的通用译名是 `蜘蛛`（意译），你必须返回此结果，而不是音译“斯派德”。"""

        
        # --- 新增：构建更丰富的上下文描述 ---
        if context_info and context_info.get('title'):
            title = context_info['title']
            year = context_info.get('year')
            media_type = context_info.get('type', '影视作品')
            tmdb_id = context_info.get('tmdb_id')
            
            context_parts = [f"一部于 {year} 年上映的{media_type}"] if year else [f"一部{media_type}"]
            context_parts.append(f"《{title}》")
            if tmdb_id:
                context_parts.append(f"(TMDB ID: {tmdb_id})")
            
            context_description = "，".join(context_parts)
            user_prompt = f"请在以下影视作品的上下文中进行翻译：{context_description}。请翻译以下角色名：\n\n{text}"
        else:
            user_prompt = f"请翻译以下人名或角色名：\n\n{text}"

        logging.info(f"【翻译-单次】最终生成的 User Prompt:\n{user_prompt}")
        # --- 新增结束 ---

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
    def translate_with_siliconflow_api_batch(texts: List[str], config: SiliconflowApiConfig, context_info: Optional[Dict[str, Any]] = None) -> List[str]:
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
6.  **核心名称一致性原则 (重要)**：
    *   在处理整个列表时，你必须识别出指向同一人物的不同角色名变体（例如 "Max", "Young Max"）。
    *   你必须确保这些变体中的核心人物名称（"Max"）在整个输出数组中拥有完全相同的中文译名。
    *   你可以翻译前缀或后缀等描述性词语，但核心名称的翻译绝不能改变。
    *   **正确示例**：输入 `["Max", "Young Max"]`，正确的输出是 `["麦克斯", "年轻的麦克斯"]` 或 `["麦克斯", "少年麦克斯"]`。
    *   **错误示例**：输出 `["麦克斯", "小马克斯"]` 是错误的，因为核心名称 "Max" 的翻译不一致 ("麦克斯" vs "马克斯")。
7.  **上下文优先原则 (重要)**：
    *   你必须**优先利用**我提供给你的影视作品上下文来决定译名。如果该作品有公认的官方或通用译名，你必须使用它。
    *   **示例**：在电影《极乐空间》的上下文中，角色代号 `Spider` 的通用译名是 `蜘蛛`（意译），你必须返回此结果，而不是音译“斯派德”。
8.  **结构化角色名处理规则**：
    *   对于包含数字和符号的角色名（如 `Henchman #2`），请翻译文本部分并**完整保留**数字和符号，输出 `打手2号`。
    *   对于包含缩写的角色名（如 `S.W.A.T. Officer`），请翻译非缩写部分，并**保留英文缩写**，输出 `S.W.A.T. 警官`。
9.  **东亚人名处理偏好**：
    *   当遇到疑似东亚（特别是中、日、韩）的罗马音拼写时，请优先查找并使用最通行的汉字写法，而不是纯粹的音译。
    *   **示例**：对于 `Yoon Se-ri`，`尹世理` 是比 `允瑟瑞` 更好的翻译。
10. **示例**：
    *   如果输入是：`["Yoon Se-ri", "The President", "DJ"]`
    *   你的输出必须是：`["尹世理", "总统", "DJ"]`

**错误输出示例（你绝不能这样返回）：**
*   `翻译结果如下：["尹世理", "总统", "DJ"]`  (包含多余文本)
*   `["尹世理", "总统"]` (数量不匹配)
*   `["总统", "尹世理", "DJ"]` (顺序不匹配)
*   `"尹世理", "总统", "DJ"` (不是合法的JSON数组格式)"""
        roles_json_array = json.dumps(texts, ensure_ascii=False)
        
        # --- 新增：构建更丰富的上下文描述 ---
        if context_info and context_info.get('title'):
            title = context_info['title']
            year = context_info.get('year')
            media_type = context_info.get('type', '影视作品')
            tmdb_id = context_info.get('tmdb_id')
            
            context_parts = [f"一部于 {year} 年上映的{media_type}"] if year else [f"一部{media_type}"]
            context_parts.append(f"《{title}》")
            if tmdb_id:
                context_parts.append(f"(TMDB ID: {tmdb_id})")
            
            context_description = "，".join(context_parts)
            user_prompt = f"请在以下影视作品的上下文中进行翻译：{context_description}。请严格按照系统指令的要求，翻译以下JSON数组中的所有角色名：\n\n{roles_json_array}"
        else:
            user_prompt = f"请严格按照系统指令的要求，翻译以下JSON数组中的所有角色名：\n\n{roles_json_array}"
        # --- 新增结束 ---

        logging.info(f"【翻译-批量】最终生成的 User Prompt:\n{user_prompt}")

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
        task_cat = f"演员中文化预览({target.scope})"
        ui_logger.info("【步骤 1/3】预览任务启动...", task_category=task_cat)
        if not self.douban_map:
            ui_logger.error("本地豆瓣数据库为空，任务中止。", task_category=task_cat)
            task_manager.update_task_progress(task_id, 0, 0)
            return []
        
        ui_logger.info("【步骤 2/3】正在扫描并统计待处理的媒体项总数...", task_category=task_cat)
        item_ids_to_process = self._get_item_ids_for_scanning(target, cancellation_event)
        if cancellation_event.is_set():
            ui_logger.warning("任务在计数阶段被取消。", task_category=task_cat)
            return []
        
        total_items = len(item_ids_to_process)
        ui_logger.info(f"【步骤 2/3】计数完成，共找到 {total_items} 个媒体项需要处理。", task_category=task_cat)
        task_manager.update_task_progress(task_id, 0, total_items)
        if total_items == 0:
            ui_logger.info("没有需要处理的媒体项，任务结束。", task_category=task_cat)
            return []
        
        ui_logger.info("【步骤 3/3】开始逐一分析媒体项...", task_category=task_cat)
        items_to_update = []
        for index, item_id in enumerate(item_ids_to_process):
            if cancellation_event.is_set(): break
            task_manager.update_task_progress(task_id, index + 1, total_items)
            
            # --- 核心重构：调用统一的逻辑函数 ---
            result = self._process_single_item_for_localization(item_id, config, task_cat, preview_mode=True)
            # --- 重构结束 ---

            if result.get("has_changes"):
                details = result["details"]
                item_name = details.get('Name', '未知名称')
                ui_logger.info(f"     -> 发现可修改项: [{item_name}]", task_category=task_cat)
                
                change_detail = {
                    'id': details['Id'], 
                    'name': item_name, 
                    'changes': result["item_changes_log"], 
                    'new_people': result["new_people_list"]
                }
                items_to_update.append(change_detail)
                task_manager.update_task_result(task_id, items_to_update)

        if cancellation_event.is_set():
            ui_logger.warning("预览任务被用户取消。", task_category=task_cat)
        else:
            ui_logger.info(f"【步骤 3/3】预览扫描完成，共处理 {total_items} 个项目，发现 {len(items_to_update)} 个可修改项。", task_category=task_cat)
        
        return items_to_update

    # backend/actor_localizer_logic.py (函数替换)

    def apply_actor_changes_task(self, items: List[Dict], cancellation_event: threading.Event, task_id: str, task_manager: TaskManager):
        task_cat = "演员中文化应用"
        total_items = len(items)
        task_manager.update_task_progress(task_id, 0, total_items)
        ui_logger.info(f"【步骤 1/2】开始应用修改，共 {total_items} 个项目。", task_category=task_cat)
        updated_count = 0
        
        full_app_config = AppConfig(server_config=self.server_config)
        role_mapper_logic = ActorRoleMapperLogic(full_app_config)

        for index, item_info in enumerate(items):
            if cancellation_event.is_set(): break
            
            item_id = item_info['id']
            item_name = item_info['name']
            new_people_list = item_info['new_people']
            changes_log = item_info.get('changes', {})
            
            task_manager.update_task_progress(task_id, index + 1, total_items)
            ui_logger.info(f"应用进度 {index + 1}/{total_items}: 正在处理 [{item_name}]", task_category=task_cat)

            item_details = self._get_item_details(item_id)
            if not item_details:
                ui_logger.error(f"  -> 获取 '{item_name}' 基础信息失败，跳过更新。", task_category=task_cat)
                continue

            provider_ids = item_details.get('ProviderIds', {})
            provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
            tmdb_id = provider_ids_lower.get("tmdb")
            item_type = item_details.get("Type")

            if not tmdb_id or not item_type:
                ui_logger.error(f"  -> 无法构建映射，媒体【{item_name}】缺少 TMDB ID 或媒体类型，跳过应用。", task_category=task_cat)
                continue

            work_map = {}
            for person in new_people_list:
                actor_name = person.get("Name")
                if not actor_name: continue
                
                # --- 核心修正：直接从 changes_log 中获取 source ---
                source_text = None
                
                change_info_by_new_name = next((v for k, v in changes_log.items() if v.get('new_name') == actor_name), None)
                change_info_by_old_name = changes_log.get(actor_name)
                change_info = change_info_by_new_name or change_info_by_old_name

                if change_info:
                    source_text = change_info.get('source')
                # --- 修正结束 ---

                work_map[actor_name] = {
                    "tmdb_id": None,
                    "role": person.get("Role", ""),
                    "source": source_text
                }

            try:
                role_mapper_logic.restore_single_map_task(
                    item_ids=[item_id],
                    role_map=work_map,
                    title=item_name,
                    cancellation_event=cancellation_event,
                    task_id=task_id,
                    task_manager=task_manager,
                    task_category=task_cat
                )
                updated_count += 1
            except Exception as e:
                ui_logger.error(f"  -> 应用 '{item_name}' 的修改时发生错误: {e}", task_category=task_cat, exc_info=True)

        if cancellation_event.is_set():
            ui_logger.warning(f"应用修改被用户取消。本次共更新 {updated_count} 个项目。", task_category=task_cat)
        else:
            ui_logger.info(f"【步骤 2/2】应用修改完成！共成功更新 {updated_count} 个项目。", task_category=task_cat)
        return {"updated_count": updated_count}
    
    def apply_actor_changes_directly_task(self, config: ActorLocalizerConfig, cancellation_event: threading.Event, task_id: str, task_manager: TaskManager, task_category: str):
        ui_logger.info("【步骤 1/2】自动应用任务启动...", task_category=task_category)
        if not self.douban_map:
            ui_logger.error("本地豆瓣数据库为空，任务中止。", task_category=task_category)
            return
        target = TargetScope(scope="all_libraries")
        item_ids_to_process = self._get_item_ids_for_scanning(target, cancellation_event)
        if cancellation_event.is_set(): return
        total_items = len(item_ids_to_process)
        ui_logger.info(f"共找到 {total_items} 个媒体项需要处理。", task_category=task_category)
        task_manager.update_task_progress(task_id, 0, total_items)
        if total_items == 0:
            ui_logger.info("没有需要处理的媒体项，任务结束。", task_category=task_category)
            return
        updated_count = 0
        for index, item_id in enumerate(item_ids_to_process):
            if cancellation_event.is_set(): break
            task_manager.update_task_progress(task_id, index + 1, total_items)
            # --- 修改 ---
            result = self._process_single_item_for_localization(item_id, config, task_category)
            if result.get("has_changes"):
            # --- 修改结束 ---
                updated_count += 1
        ui_logger.info(f"【步骤 2/2】自动应用任务执行完毕，共更新了 {updated_count} 个项目的演员角色。", task_category=task_category)
        return {"updated_count": updated_count}
    
    def get_people_for_item(self, item_id: str) -> List[Dict]:
        """获取指定媒体项的演职员列表"""
        task_cat = "手动校正-获取演员"
        try:
            ui_logger.info(f"➡️ 正在获取媒体项 (ID: {item_id}) 的演职员列表...", task_category=task_cat)
            details = self._get_item_details(item_id, full_json=True)
            if not details:
                raise Exception("未能获取到媒体详情。")
            
            people = details.get('People', [])
            ui_logger.info(f"✅ 成功获取到 {len(people)} 位演职员信息。", task_category=task_cat)
            return people
        except Exception as e:
            ui_logger.error(f"❌ 获取演职员列表失败: {e}", task_category=task_cat)
            raise e
        
    def suggest_roles_with_ai(self, item_id: str, actor_names: List[str], config: ActorLocalizerConfig) -> Dict[str, str]:
        """使用AI为给定的演员列表建议角色名"""
        task_cat = "手动校正-AI建议"
        ui_logger.info(f"➡️ 收到为媒体 (ID: {item_id}) 的 {len(actor_names)} 位演员请求AI角色建议的任务...", task_category=task_cat)
        
        try:
            details = self._get_item_details(item_id)
            if not details:
                raise Exception("未能获取媒体上下文信息。")

            item_name = details.get('Name', '未知标题')
            provider_ids = details.get('ProviderIds', {})
            provider_ids_lower = {k.lower(): v for k, v in provider_ids.items()}
            
            context_info = {
                "title": item_name,
                "year": details.get("ProductionYear"),
                "type": "电视剧" if details.get("Type") == "Series" else "电影",
                "tmdb_id": provider_ids_lower.get("tmdb")
            }
            
            system_prompt = """你是一位顶级的影视数据库专家，专门负责根据影视作品信息和演员名单，精准地提供角色名。

**你的核心任务与规则如下：**

1.  **输入格式：** 我将以JSON字符串数组的格式为你提供演员列表。
2.  **精确匹配：** 你必须根据我提供的电影或电视剧的上下文（标题、年份、TMDB ID），找出每位演员在该作品中饰演的核心角色。
3.  **输出格式严格：** 你的回答必须是纯文本格式。每一行代表一位演员，格式严格遵守 `演员名: 角色名`。分隔符是英文冒号和紧随其后的一个空格 `": "`。
4.  **输入复现：** 每一行开头的 `演员名` 必须与我提供给你的JSON数组中的演员名完全一致。
5.  **别名规范：** 如果角色有广为人知的别名或代号（例如“钢铁侠”），请使用正斜杠 `/` 将其与本名隔开，格式为 `本名 / 别名`。如果没有别名，则只返回本名。
6.  **知之为知之：** 如果对于某位演员，你无法在指定的作品中找到确切的角色名，或者不确定，请**直接忽略该演员，不要在你的回答中包含这一行**。宁缺毋滥。
7.  **绝对简洁：** 你的回答中【绝对不能】包含任何除了 `演员名: 角色名` 列表之外的文字，例如“好的，这是您要的角色列表：”、序号、空行或任何解释。

**黄金示例：**
假设我提供了电影《复仇者联盟》的上下文，以及演员列表 `["小罗伯特·唐尼", "克里斯·埃文斯", "一位不存在的演员", "斯嘉丽·约翰逊"]`。
你的**唯一且完整**的回答应该是：
小罗伯特·唐尼: 托尼·斯塔克 / 钢铁侠
克里斯·埃文斯: 史蒂夫·罗杰斯 / 美国队长
斯嘉丽·约翰逊: 娜タ莎·罗曼诺夫 / 黑寡妇
*（在这个示例中，你正确地复现了演员名，为部分角色添加了别名，并且忽略了无法找到的“一位不存在的演员”。）*
"""

            actors_json_array = json.dumps(actor_names, ensure_ascii=False)
            
            context_parts = [f"一部于 {context_info['year']} 年上映的{context_info['type']}"] if context_info.get('year') else [f"一部{context_info['type']}"]
            context_parts.append(f"《{context_info['title']}》")
            if context_info.get('tmdb_id'):
                context_parts.append(f"(TMDB ID: {context_info['tmdb_id']})")
            
            context_description = "，".join(context_parts)
            user_prompt = f"在以下影视作品的上下文中：{context_description}。\n\n请为下列JSON数组中的每一位演员提供他们对应的角色名：\n\n{actors_json_array}"

            logging.info(f"【AI建议】最终生成的 User Prompt:\n{user_prompt}")

            sf_config = config.siliconflow_config
            url = "https://api.siliconflow.cn/v1/chat/completions"
            payload = {
                "model": sf_config.model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "stream": False,
                "max_tokens": 1500,
                "temperature": sf_config.temperature,
                "top_p": sf_config.top_p
            }
            headers = {"Authorization": f"Bearer {sf_config.api_key}", "Content-Type": "application/json"}
            
            ui_logger.info(f"🔍 正在向AI模型请求角色建议...", task_category=task_cat)
            response = requests.post(url, json=payload, headers=headers, timeout=sf_config.timeout_batch)
            response.raise_for_status()
            result = response.json()

            if not (result.get("choices") and len(result["choices"]) > 0):
                raise Exception(f"AI API 响应格式不正确: {result}")

            content = result["choices"][0].get("message", {}).get("content", "").strip()
            logging.debug(f"【AI建议】收到原始响应: \n{content}")

            role_map = {}
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            for line in lines:
                parts = line.split(': ', 1)
                if len(parts) == 2:
                    actor_name = parts[0].strip()
                    role_name = parts[1].strip()
                    role_map[actor_name] = role_name
            
            ui_logger.info(f"✅ AI成功返回了 {len(role_map)} 条角色建议。", task_category=task_cat)
            return role_map

        except Exception as e:
            ui_logger.error(f"❌ 请求AI角色建议失败: {e}", task_category=task_cat, exc_info=True)
            raise e