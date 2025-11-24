import requests
import json
import time
import os

CONFIG_FILE = '/app/data/config.json'

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ 配置文件 {CONFIG_FILE} 不存在。")
        return None
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ 读取配置文件失败: {e}")
        return None

def test_fetch():
    config = load_config()
    if not config: return

    server_conf = config.get('server_config', {})
    server_url = server_conf.get('server')
    api_key = server_conf.get('api_key')
    user_id = server_conf.get('user_id')

    if not all([server_url, api_key, user_id]):
        print("❌ Emby 配置不完整，请检查 config.json")
        return

    print(f"➡️ 准备连接 Emby 服务器: {server_url}")
    print("➡️ 开始请求全量演员数据 (IncludeItemTypes=Person)...")

    start_time = time.time()

    try:
        # 构造请求：只获取 Person 类型，且只请求必要的字段 (Id, Name, ProviderIds) 以减少数据量
        url = f"{server_url}/Items"
        params = {
            "api_key": api_key,
            "Recursive": "true",
            "IncludeItemTypes": "Person",
            "Fields": "ProviderIds",
            # "Limit": 1000 # 如果想测试分页，可以取消注释
        }
        
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        
        data = response.json()
        items = data.get("Items", [])
        
        end_time = time.time()
        duration = end_time - start_time

        total_count = len(items)
        tmdb_count = 0
        
        # 简单的统计
        for item in items:
            provider_ids = item.get("ProviderIds", {})
            # 检查是否有 tmdb id (不区分大小写)
            if any(k.lower() == 'tmdb' for k in provider_ids.keys()):
                tmdb_count += 1

        print("-" * 30)
        print(f"✅ 请求成功！")
        print(f"⏱️ 耗时: {duration:.4f} 秒")
        print(f"📊 获取到的演员总数: {total_count}")
        print(f"🎯 包含 TMDB ID 的演员数: {tmdb_count}")
        print("-" * 30)
        
        if items:
            print("🔍 前 5 个演员数据示例:")
            for item in items[:5]:
                print(json.dumps(item, ensure_ascii=False))
        else:
            print("⚠️ 未获取到任何演员数据。")

    except Exception as e:
        print(f"❌ 请求失败: {e}")

if __name__ == "__main__":
    test_fetch()