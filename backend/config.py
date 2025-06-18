# backend/config.py (修改后)
import json
import os
from models import AppConfig

# --- 核心修改：将配置文件路径指向容器内的 /app/data 目录 ---
# 这样可以通过 Docker Volume 将主机上的 ./data/config.json 映射进来
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

# backend/config.py

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

    # 所有的兼容性处理和补全逻辑都可以简化或移除，
    # 因为 Pydantic 在加载时会自动应用默认值。
    # 前端在保存时会提交完整的结构，覆盖旧的。
    
    # 我们可以保留一些基础的，以防万一
    if "proxy_config" not in config_data:
        config_data["proxy_config"] = {}
    if "tmdb_config" not in config_data:
        config_data["tmdb_config"] = {}
    if "download_config" not in config_data:
        config_data["download_config"] = {}
    if "douban_config" not in config_data:
        config_data["douban_config"] = {}
    if "actor_localizer_config" not in config_data:
        config_data["actor_localizer_config"] = {}
    if "douban_fixer_config" not in config_data:
        config_data["douban_fixer_config"] = {}
    if "scheduled_tasks_config" not in config_data:
        config_data["scheduled_tasks_config"] = {}
    if "douban_poster_updater_config" not in config_data:
        config_data["douban_poster_updater_config"] = {}
        
    # 移除 "subtitle_processor_config" (如果存在)
    if "subtitle_processor_config" in config_data:
        del config_data["subtitle_processor_config"]

    # Pydantic 会处理剩下的所有事情，包括使用 default_factory
    return AppConfig(**config_data)

def save_app_config(app_config: AppConfig):
    config_dir = os.path.dirname(CONFIG_FILE)
    if not os.path.exists(config_dir):
        os.makedirs(config_dir, exist_ok=True)
        
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        # 使用 model_dump() 替代 dict()
        dump_data = app_config.model_dump(mode='json')
        json.dump(dump_data, f, ensure_ascii=False, indent=4)