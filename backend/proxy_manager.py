# backend/proxy_manager.py (新文件)

import logging
from typing import Dict

from models import AppConfig

class ProxyManager:
    """
    一个中央代理管理器，用于根据用户配置决定是否为特定请求启用代理。
    """
    def __init__(self, app_config: AppConfig):
        self.proxy_config = app_config.proxy_config
        self.emby_config = app_config.server_config
        self.tmdb_config = app_config.tmdb_config

    def get_proxies(self, target_url: str) -> Dict:
        """
        根据目标URL和配置，返回适用于requests库的proxies字典。
        如果不需要代理，则返回空字典。
        """
        config = self.proxy_config
        if not config.enabled or not config.url:
            return {}

        # 检查目标URL属于哪个服务
        is_tmdb_target = "themoviedb.org" in target_url or (self.tmdb_config.custom_api_domain_enabled and self.tmdb_config.custom_api_domain in target_url)
        is_douban_target = "douban.com" in target_url or "doubanio.com" in target_url
        
        # 核心修复：使用 startswith 检查，避免因路径问题导致匹配失败
        is_emby_target = target_url.startswith(self.emby_config.server) if self.emby_config.server else False

        should_use_proxy = False
        if config.mode == 'blacklist':
            # 黑名单模式：默认走代理，勾选的为不走代理的例外
            should_use_proxy = True
            if is_tmdb_target and config.target_tmdb: should_use_proxy = False
            if is_douban_target and config.target_douban: should_use_proxy = False
            if is_emby_target and config.target_emby: should_use_proxy = False
        
        elif config.mode == 'whitelist':
            # 白名单模式：默认不走代理，勾选的为走代理的例外
            should_use_proxy = False
            if is_tmdb_target and config.target_tmdb: should_use_proxy = True
            if is_douban_target and config.target_douban: should_use_proxy = True
            if is_emby_target and config.target_emby: should_use_proxy = True

        if should_use_proxy:
            logging.debug(f"【动态代理-{config.mode}】为请求启用代理: {target_url}")
            return {'http': config.url, 'https': config.url}
        else:
            logging.debug(f"【动态代理-{config.mode}】为请求禁用代理: {target_url}")
            return {}