# backend/config.py (修改后)
import json
import os
import logging
from models import AppConfig

CONFIG_FILE = os.path.join('/app/data', 'config.json')

DEFAULT_GENRE_MAP = {
    "Action": "动作", "Adventure": "冒险", "Animation": "动画", "Comedy": "喜剧",
    "Crime": "犯罪", "Documentary": "纪录片", "Drama": "剧情", "Family": "家庭",
    "Fantasy": "奇幻", "History": "历史", "Horror": "恐怖", "Music": "音乐",
    "Mystery": "悬疑", "Romance": "爱情", "Science Fiction": "科幻",
    "Thriller": "惊悚", "War": "战争", "Western": "西部", "TV Movie": "电视电影",
    "Sci-Fi & Fantasy": "科幻奇幻", "Suspense": "惊悚", "Sport": "运动", "War & Politics": "战争政治"
}

DEFAULT_SF_MODEL_REMARKS = {
    "Qwen/Qwen2-7B-Instruct": "（推荐，免费）",
    "THUDM/glm-4-9b-chat": "（推荐，免费）",
    "internlm/internlm2_5-7b-chat": "（免费）",
    "Qwen/Qwen2.5-72B-Instruct": "（性能强，￥4.13/ M Tokens）",
    "Qwen/Qwen2.5-32B-Instruct": "（性能强，输入：￥1.26/ M Tokens）",
    "Qwen/Qwen2.5-14B-Instruct": "（输入：￥0.7/ M Tokens）",
    "Qwen/Qwen2.5-7B-Instruct": "（免费）",
    "Tongyi-Zhiwen/QwenLong-L1-32B": "（收费）",
    "Qwen/Qwen3-32B": "（收费）",
    "THUDM/GLM-4-32B-0414": "（收费 ￥1.89/ M Tokens）",
    "deepseek-ai/DeepSeek-V2.5": "（收费 输入：￥1.33/ M Tokens）"
}

# backend/config.py (修改 load_app_config 函数)

def load_app_config() -> AppConfig:
    config_dir = os.path.dirname(CONFIG_FILE)
    if not os.path.exists(config_dir):
        os.makedirs(config_dir, exist_ok=True)

    config_data = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                content = f.read()
                if content:
                    config_data = json.loads(content)
        except (json.JSONDecodeError, IOError):
            pass 

    if "proxy_config" not in config_data:
        config_data["proxy_config"] = {"enabled": False, "url": "", "exclude": ""}
    elif not isinstance(config_data["proxy_config"], dict):
        config_data["proxy_config"] = {"enabled": bool(config_data["proxy_config"]), "url": str(config_data["proxy_config"]), "exclude": ""}
    else:
        if "enabled" not in config_data["proxy_config"]:
            config_data["proxy_config"]["enabled"] = False
        if "exclude" not in config_data["proxy_config"]:
            config_data["proxy_config"]["exclude"] = ""

    if "tmdb_config" not in config_data:
        config_data["tmdb_config"] = {"api_key": "", "custom_api_domain_enabled": False, "custom_api_domain": "https://api.themoviedb.org"}
    else:
        if "custom_api_domain_enabled" not in config_data["tmdb_config"]:
            config_data["tmdb_config"]["custom_api_domain_enabled"] = False
        if "custom_api_domain" not in config_data["tmdb_config"]:
            config_data["tmdb_config"]["custom_api_domain"] = "https://api.themoviedb.org"

    if "download_config" not in config_data:
        config_data["download_config"] = {"download_directory": "", "download_behavior": "skip", "directory_naming_rule": "tmdb_id", "nfo_actor_limit": 20}
    else:
        if "directory_naming_rule" not in config_data["download_config"]:
            config_data["download_config"]["directory_naming_rule"] = "tmdb_id"
        if "nfo_actor_limit" not in config_data["download_config"]:
            config_data["download_config"]["nfo_actor_limit"] = 20

    if not config_data.get("genre_mapping"):
        config_data["genre_mapping"] = DEFAULT_GENRE_MAP
    
    if "douban_config" not in config_data:
        config_data["douban_config"] = {"directory": "", "refresh_cron": "", "extra_fields": []}
    elif "extra_fields" not in config_data["douban_config"]:
        config_data["douban_config"]["extra_fields"] = []

    # --- 核心修改：调整 actor_localizer_config 的加载和兼容性处理 ---
    if "actor_localizer_config" not in config_data:
        config_data["actor_localizer_config"] = {}
    
    actor_conf = config_data["actor_localizer_config"]
    
    if "siliconflow_config" not in actor_conf:
        actor_conf["siliconflow_config"] = {}
        
    sf_conf = actor_conf.get("siliconflow_config", {})

    if not sf_conf.get("model_remarks"):
        sf_conf["model_remarks"] = DEFAULT_SF_MODEL_REMARKS

    # 兼容性处理：如果存在旧的 timeout 字段，则进行迁移
    migration_needed = "timeout" in sf_conf
    if migration_needed:
        logging.info("【配置兼容】检测到旧的 'timeout' 配置，将自动迁移到新的 'timeout_single' 和 'timeout_batch'。")
        old_timeout = sf_conf.get("timeout", 20)
        
        # 只有在新字段不存在时才进行赋值，避免覆盖用户已有的设置
        if "timeout_single" not in sf_conf:
            sf_conf["timeout_single"] = old_timeout
        if "timeout_batch" not in sf_conf:
            sf_conf["timeout_batch"] = max(old_timeout + 25, 45)
            
        # 迁移完成后，删除旧的键
        del sf_conf["timeout"]

    if "apply_cron" not in actor_conf:
        actor_conf["apply_cron"] = ""
    # --- 结束修改 ---

    if "douban_fixer_config" not in config_data:
        config_data["douban_fixer_config"] = {"cookie": "", "api_cooldown": 2.0, "scan_cron": ""}
    
    if "scheduled_tasks_config" not in config_data:
        config_data["scheduled_tasks_config"] = {}
        
    if "douban_poster_updater_config" not in config_data:
        config_data["douban_poster_updater_config"] = {}

    if "webhook_config" not in config_data:
        config_data["webhook_config"] = {}
        
    # --- 新增：为新配置添加加载逻辑 ---
    if "episode_refresher_config" not in config_data:
        config_data["episode_refresher_config"] = {}
    # --- 结束新增 ---

    if "subtitle_processor_config" in config_data:
        del config_data["subtitle_processor_config"]

    temp_app_config = AppConfig(**config_data)
    
    default_tasks = temp_app_config.scheduled_tasks_config.model_dump()['tasks']
    
    current_tasks = config_data.get("scheduled_tasks_config", {}).get("tasks", [])
    
    if len(current_tasks) < len(default_tasks):
        current_task_ids = {task['id'] for task in current_tasks}
        for default_task in default_tasks:
            if default_task['id'] not in current_task_ids:
                current_tasks.append(default_task)
        
        if "scheduled_tasks_config" not in config_data:
            config_data["scheduled_tasks_config"] = {}
        config_data["scheduled_tasks_config"]["tasks"] = current_tasks

    # 检查是否需要重写配置文件（例如，因为我们删除了旧的timeout键）
    should_rewrite = not os.path.exists(CONFIG_FILE) or migration_needed

    if should_rewrite:
        final_config = AppConfig(**config_data).model_dump(mode='json')
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(final_config, f, ensure_ascii=False, indent=4)
        if migration_needed:
            logging.info("【配置兼容】配置文件已更新到最新结构。")

    return AppConfig(**config_data)

def save_app_config(app_config: AppConfig):
    config_dir = os.path.dirname(CONFIG_FILE)
    if not os.path.exists(config_dir):
        os.makedirs(config_dir, exist_ok=True)
        
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        dump_data = app_config.model_dump(mode='json')
        json.dump(dump_data, f, ensure_ascii=False, indent=4)