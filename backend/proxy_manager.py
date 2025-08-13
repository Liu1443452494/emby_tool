# backend/proxy_manager.py (完整文件覆盖 - 最小化改动版)

import logging
from typing import Dict, Optional
import httpx
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
        匹配顺序: 自定义规则 -> 内置规则 -> 全局排除
        """
        config = self.proxy_config
        if not config.enabled or not config.url:
            return {}

        # 1. 检查自定义规则 (支持'|'分隔的多关键词，并忽略前后空格)
        for rule in config.custom_rules:
            if rule.enabled and rule.keyword:
                # 核心修改：对每个分割后的关键词使用 .strip()
                keywords = [k.strip() for k in rule.keyword.split('|') if k.strip()]
                # 检查是否有任何一个关键词匹配成功
                if any(k in target_url for k in keywords):
                    # 命中自定义规则，立即决策
                    if config.mode == 'whitelist':
                        logging.debug(f"【动态代理-白名单】命中自定义规则 '{rule.remark}' (关键词: {rule.keyword})，启用代理: {target_url}")
                        return {'http': config.url, 'https': config.url}
                    else: # blacklist
                        logging.debug(f"【动态代理-黑名单】命中自定义规则 '{rule.remark}' (关键词: {rule.keyword})，禁用代理: {target_url}")
                        return {}

        # 2. 检查内置规则
        is_tmdb_target = "themoviedb.org" in target_url or (self.tmdb_config.custom_api_domain_enabled and self.tmdb_config.custom_api_domain in target_url)
        is_douban_target = "douban.com" in target_url or "doubanio.com" in target_url
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

        # 3. 如果决定要走代理，最后检查全局排除列表
        if should_use_proxy and config.exclude:
            try:
                # 全局排除列表仍然使用逗号分隔
                excluded_domains = [d.strip() for d in config.exclude.split(',') if d.strip()]
                if any(domain in target_url for domain in excluded_domains):
                    logging.debug(f"【动态代理】请求 '{target_url}' 命中全局排除列表，最终禁用代理。")
                    should_use_proxy = False
            except Exception as e:
                logging.warning(f"【动态代理】解析全局排除列表时出错: {e}")

        if should_use_proxy:
            logging.debug(f"【动态代理-{config.mode}】为请求启用代理: {target_url}")
            return {'http': config.url, 'https': config.url}
        else:
            logging.debug(f"【动态代理-{config.mode}】为请求禁用代理: {target_url}")
            return {}

    def get_proxies_for_httpx(self, target_url: str) -> Optional[Dict[str, httpx.AsyncHTTPTransport]]:
        """
        获取适用于 httpx 客户端的代理配置。
        此方法返回 mounts 参数所需的对象格式，以实现最佳兼容性。
        """
      

        requests_proxies = self.get_proxies(target_url)
        
        if requests_proxies:
            proxy_url = requests_proxies.get('https') or requests_proxies.get('http')
            if proxy_url:
                # 使用 httpx.AsyncHTTPTransport 来配置代理，这是最稳妥的方式
                transport = httpx.AsyncHTTPTransport(proxy=httpx.Proxy(url=proxy_url))
                return {'all://': transport}
        
        return None