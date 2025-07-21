# backend/signin_modules/hdhive_signin.py (新文件)

import time
import requests
import re
import json
from datetime import datetime
from typing import Tuple, Dict, Any

import jwt
import cloudscraper

from log_manager import ui_logger
from models import HdhiveSigninConfig

class HdhiveSignInModule:
    """
    影巢(HDHive)签到模块
    """
    # 模块元数据
    module_id = "hdhive"
    module_name = "影巢签到"
    
    def __init__(self, config: HdhiveSigninConfig, signin_data: Dict[str, Any]):
        self.config = config
        self.data = signin_data
        self.scraper = cloudscraper.create_scraper(delay=10)
        self._signin_api = "https://hdhive.online/api/customer/user/checkin"
        self.task_category = "签到-影巢"

    def get_summary(self) -> Dict[str, Any]:
        """获取用于在主卡片上展示的摘要信息"""
        return {
            "last_signin_time": self.data.get("last_signin_time"),
            "consecutive_days": self.data.get("consecutive_days", 0),
        }

    def sign(self, retry_count=0, proxies=None) -> Dict[str, Any]:
        """
        执行签到核心逻辑。
        返回一个包含签到结果的字典。
        """
        ui_logger.info(f"➡️ 开始执行签到...", task_category=self.task_category)
        
        if not self.config.cookie:
            ui_logger.error("❌ 未配置Cookie，任务中止。", task_category=self.task_category)
            return self._create_record("签到失败", "未配置Cookie")

        try:
            # --- 核心修改：传递 proxies ---
            state, message = self._signin_base(proxies=proxies)
            
            if state:
                ui_logger.info(f"✅ API返回消息: {message}", task_category=self.task_category)
                sign_status = "已签到" if "签到过" in message else "签到成功"
                
                today_str = datetime.now().strftime('%Y-%m-%d')
                last_date_str = self.data.get('last_success_date')
                consecutive_days = self.data.get('consecutive_days', 0)

                if last_date_str != today_str:
                    from datetime import timedelta
                    yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
                    if last_date_str == yesterday_str:
                        consecutive_days += 1
                    else:
                        consecutive_days = 1
                    self.data['consecutive_days'] = consecutive_days
                    self.data['last_success_date'] = today_str

                points_match = re.search(r'获得 (\d+) 积分', message)
                points = int(points_match.group(1)) if points_match else "—"

                return self._create_record(sign_status, message, points, consecutive_days)

            else: # 签到失败
                ui_logger.error(f"❌ 签到失败: {message}", task_category=self.task_category)
                if retry_count < self.config.max_retries:
                    ui_logger.warning(f"🔄 将在 {self.config.retry_interval} 秒后进行第 {retry_count + 1} 次重试...", task_category=self.task_category)
                    time.sleep(self.config.retry_interval)
                    # --- 核心修改：在重试时也传递 proxies ---
                    return self.sign(retry_count + 1, proxies=proxies)
                else:
                    ui_logger.error("❗ 所有重试均已失败。", task_category=self.task_category)
                    return self._create_record("签到失败", f"{message} (已达最大重试次数)")

        except Exception as e:
            ui_logger.error(f"❗ 签到过程中发生未知异常: {e}", task_category=self.task_category, exc_info=True)
            return self._create_record("签到失败", f"未知异常: {e}")

    def _signin_base(self, proxies=None) -> Tuple[bool, str]:
        """实际的HTTP请求逻辑"""
        cookies = {item.split('=')[0]: item.split('=')[1] for item in self.config.cookie.split('; ') if '=' in item}
        token = cookies.get('token')
        csrf_token = cookies.get('csrf_access_token')

        if not token:
            return False, "Cookie中缺少'token'"

        referer = "https://hdhive.online/"
        try:
            decoded_token = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
            user_id = decoded_token.get('sub')
            if user_id:
                referer = f"https://hdhive.online/user/{user_id}"
        except Exception as e:
            ui_logger.warning(f"⚠️ 从Token中解析用户ID失败: {e}", task_category=self.task_category)

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Origin': 'https://hdhive.online',
            'Referer': referer,
            'Authorization': f'Bearer {token}',
        }
        if csrf_token:
            headers['x-csrf-token'] = csrf_token

        try:
            # --- 核心修改：增加 proxies 参数 ---
            res = self.scraper.post(url=self._signin_api, headers=headers, cookies=cookies, timeout=60, proxies=proxies)
            ui_logger.debug(f"   - [调试] 请求完成，HTTP状态码: {res.status_code}", task_category=self.task_category)
            
            if res.status_code not in [200, 400]:
                ui_logger.warning(f"   - [调试] 响应内容 (前500字符): {res.text[:500]}", task_category=self.task_category)
                if 'Just a moment...' in res.text or 'Checking your browser' in res.text:
                    return False, f'Cloudflare 质询失败，HTTP状态码: {res.status_code}'
                return False, f'HTTP状态码: {res.status_code}, 响应: {res.text[:200]}'

            result = res.json()
            message = result.get('message', '无明确消息')
            
            if result.get('success') or "签到过" in message:
                return True, message
            
            return False, message
        except Exception as e:
            ui_logger.error(f"❗ Cloudscraper 请求时发生错误: {e}", task_category=self.task_category, exc_info=True)
            return False, f"网络请求错误: {e}"

    def _create_record(self, status: str, message: str, points: Any = "—", days: Any = "—") -> Dict[str, Any]:
        """创建一个标准的签到记录字典"""
        return {
            "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "status": status,
            "message": message,
            "points": points,
            "days": days
        }