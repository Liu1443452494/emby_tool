

import logging
import requests
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List, Dict
from bs4 import BeautifulSoup
import re


from log_manager import ui_logger
from models import AppConfig
from douban_fixer_logic import DoubanFixerLogic
from task_manager import task_manager
import config as app_config

router = APIRouter()

def get_logic(temp_config: AppConfig = None) -> DoubanFixerLogic:
    config_to_use = temp_config if temp_config else app_config.load_app_config()
    
    if not all([config_to_use.server_config.server, config_to_use.server_config.api_key, config_to_use.server_config.user_id]):
        raise HTTPException(status_code=400, detail="Emby 服务器未配置，请先在配置页面完成设置。")
    if not config_to_use.douban_fixer_config.cookie:

        logging.warning("【豆瓣修复器】豆瓣 Cookie 未配置，功能可能受限。")
    return DoubanFixerLogic(config_to_use)

@router.post("/test-cookie")
def test_douban_cookie(payload: Dict):
    task_cat = "API-豆瓣修复器"
    cookie = payload.get("cookie")
    if not cookie:
        raise HTTPException(status_code=400, detail="Cookie 不能为空")

    try:
        test_url = "https://movie.douban.com/mine?status=collect"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
            'Cookie': cookie
        }
        response = requests.get(test_url, headers=headers, timeout=15, allow_redirects=False)
        response.raise_for_status()

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            user_menu_link = soup.select_one('div.user-info a.bn-more, div.global-nav-items a.nav-user-account')
            if user_menu_link and ('的帐号' in user_menu_link.text or '帐号管理' in user_menu_link.get('title', '')):
                user_name_match = re.search(r'(.+?)的帐号', user_menu_link.text)
                user_name = user_name_match.group(1).strip() if user_name_match else "未知用户"
                ui_logger.info(f"【Cookie测试】【策略1】成功，识别到用户: {user_name}。Cookie有效。", task_category=task_cat)
                return {"status": "success", "message": f"Cookie 有效，识别到用户: {user_name}"}

            all_links = soup.find_all('a', href=re.compile(r"https://www.douban.com/people/.+/"))
            for link in all_links:
                if 'status' in link.get('href', '') or 'privacy' in link.get('href', ''):
                    continue
                
                user_name = link.get_text(strip=True)
                if user_name:
                    ui_logger.info(f"【Cookie测试】【策略2】成功，识别到用户: {user_name}。Cookie有效。", task_category=task_cat)
                    return {"status": "success", "message": f"Cookie 有效，识别到用户: {user_name}"}

            ui_logger.warning(f"【Cookie测试】访问成功但所有策略均未找到有效的用户信息，可能Cookie已失效。", task_category=task_cat)
            raise HTTPException(status_code=401, detail="Cookie 无效或已过期，无法识别用户信息。")
        else:
            ui_logger.warning(f"【Cookie测试】访问豆瓣个人页面失败，状态码: {response.status_code}。", task_category=task_cat)
            raise HTTPException(status_code=response.status_code, detail=f"访问豆瓣失败，状态码: {response.status_code}")

    except requests.RequestException as e:
        ui_logger.error(f"【Cookie测试】请求豆瓣时发生网络错误: {e}", task_category=task_cat)
        raise HTTPException(status_code=500, detail=f"连接豆瓣失败，请检查网络或代理设置。错误: {e}")


@router.post("/scan-all")
def start_full_scan(payload: Dict):
    logic = get_logic()
    for task in task_manager.get_all_tasks():
        if task['name'].startswith("豆瓣ID修复"):
            raise HTTPException(status_code=409, detail=f"已有豆瓣ID修复任务(ID: {task['id']})正在运行，请勿重复启动。")
            
    scan_scope = payload.get("scope", "all")
    media_type = payload.get("media_type")
    library_ids = payload.get("library_ids")
    
    task_name = f"豆瓣ID修复-{scan_scope}"
    task_id = task_manager.register_task(logic.scan_and_match_task, task_name, scan_scope, media_type, library_ids)
    return {"status": "success", "message": "扫描任务已启动，请在“运行任务”页面查看进度。", "task_id": task_id}

@router.get("/cache")
def get_failed_cache() -> List[Dict]:
    logic = get_logic()
    cache_data = logic._load_cache()
    return list(cache_data.values())

@router.delete("/cache")
def clear_failed_cache():
    logic = get_logic()
    logic._save_cache({})
    return {"status": "success", "message": "失败缓存已清空。"}

@router.post("/manual-search")
def manual_search_douban(payload: Dict):
    task_cat = "API-豆瓣修复器"
    item_name = payload.get("name")
    if not item_name:
        raise HTTPException(status_code=400, detail="缺少搜索名称 'name'")
    
    logic = get_logic()
    search_results = logic._search_douban(item_name, task_cat)
    
    if search_results is None:
        raise HTTPException(status_code=503, detail="搜索豆瓣失败，请检查网络或Cookie配置。")
    
    return search_results

@router.post("/manual-update")
def manual_update_douban_id(payload: Dict):
    task_cat = "API-豆瓣修复器"
    emby_item_id = payload.get("emby_item_id")
    douban_id = payload.get("douban_id")
    
    if not emby_item_id or not douban_id:
        raise HTTPException(status_code=400, detail="请求必须包含 'emby_item_id' 和 'douban_id'")
        
    logic = get_logic()
    success = logic._update_emby_item_douban_id(emby_item_id, douban_id, task_cat)
    
    if success:
        logic.remove_from_cache(emby_item_id, task_cat)
        return {"status": "success", "message": "豆瓣ID更新成功，并已从缓存移除。"}
    else:
        raise HTTPException(status_code=500, detail="更新Emby媒体项失败，请检查后端日志。")