# backend/notification_manager.py (完整文件覆盖)

import requests
import re
from typing import Dict

from models import TelegramConfig, AppConfig
from log_manager import ui_logger
from proxy_manager import ProxyManager

def escape_markdown(text: str) -> str:
    """
    转义 Telegram MarkdownV2 所需的特殊字符。
    """
    escape_chars = r'([_*\[\]()~`>#\+\-=|{}.!])'
    return re.sub(escape_chars, r'\\\1', text)

class NotificationManager:
    """
    中央通知管理器，用于处理向不同渠道发送消息。
    """
    
    def send_telegram_message(self, message: str, app_config: AppConfig) -> Dict:
        """
        发送消息到 Telegram。
        """
        task_cat = "通知-Telegram"
        config = app_config.telegram_config
        
        if not all([config.enabled, config.bot_token, config.chat_id]):
            ui_logger.debug("   - [调试] Telegram通知未启用或配置不完整，跳过发送。", task_category=task_cat)
            return {"success": False, "message": "通知未启用或配置不完整"}

        api_url = f"https://api.telegram.org/bot{config.bot_token}/sendMessage"
        payload = {
            'chat_id': config.chat_id,
            'text': message,
            'parse_mode': 'MarkdownV2'
        }
        
        # --- 核心修改：集成 ProxyManager ---
        proxy_manager = ProxyManager(app_config)
        proxies = proxy_manager.get_proxies(api_url)
        
        if proxies:
            ui_logger.info(f"➡️ 正在尝试通过代理 {proxies.get('http')} 发送Telegram通知...", task_category=task_cat)
        else:
            ui_logger.info(f"➡️ 正在尝试直接连接并发送Telegram通知...", task_category=task_cat)
        # --- 修改结束 ---
        
        try:
            # --- 核心修改：在请求中加入 proxies 参数 ---
            response = requests.post(api_url, json=payload, timeout=15, proxies=proxies)
            response.raise_for_status()
            
            result = response.json()
            if result.get("ok"):
                ui_logger.info("✅ Telegram通知发送成功！", task_category=task_cat)
                return {"success": True, "message": "通知发送成功"}
            else:
                error_msg = result.get("description", "未知错误")
                ui_logger.error(f"❌ Telegram API返回错误: {error_msg}", task_category=task_cat)
                return {"success": False, "message": f"API错误: {error_msg}"}

        except requests.exceptions.RequestException as e:
            error_details = f"网络错误: {e}"
            if e.response is not None:
                try:
                    error_body = e.response.json()
                    error_details = f"API请求失败: {error_body.get('description', e.response.text)}"
                except Exception:
                    error_details = f"API请求失败: HTTP {e.response.status_code}, {e.response.text}"

            ui_logger.error(f"❌ 发送Telegram通知时出错: {error_details}", task_category=task_cat, exc_info=True)
            return {"success": False, "message": error_details}
        except Exception as e:
            ui_logger.error(f"❌ 发送Telegram通知时发生未知异常: {e}", task_category=task_cat, exc_info=True)
            return {"success": False, "message": f"未知异常: {e}"}

# 创建一个单例
notification_manager = NotificationManager()