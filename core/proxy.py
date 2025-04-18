"""
代理管理模块 - 负责代理配置的加载、选择和轮询
"""

import threading
import time
import asyncio
from typing import Dict, Optional, Any

class ProxyManager:
    """代理管理器类，处理代理选择和轮询"""
    
    def __init__(self, proxy_config: Dict[str, Any] = None, logger=None):
        """
        初始化代理管理器
        
        Args:
            proxy_config: 代理配置字典，包含api、yta和groups配置
            logger: 日志记录器
        """
        self.proxy_config = proxy_config or {}
        self.logger = logger
        self.api_counters = {}  # 每个组的API代理计数器
        self.yta_counters = {}  # 每个组的YTA代理计数器
        self.lock = threading.Lock()  # 用于线程安全的锁
        
        # 禁用代理相关的属性
        self.disabled_proxies = {}
        self.disable_duration = 3600
        self.test_tasks = {}
        
        # 测试用的YouTube频道ID
        self.test_channel_id = "UC7Vl0YiY0rDlovqcCFN4yTA"
        
        if self.logger:
            self.logger.info("代理管理器初始化完成")
    
    def set_config(self, proxy_config: Dict[str, Any]) -> None:
        """
        设置或更新代理配置
        
        Args:
            proxy_config: 新的代理配置
        """
        self.proxy_config = proxy_config
        # 重置计数器
        self.api_counters = {}
        self.yta_counters = {}
        
        if self.logger:
            self.logger.info("代理配置已更新")
            if 'groups' in proxy_config:
                for group_name, proxies in proxy_config.get('groups', {}).items():
                    proxy_names = []
                    for p in proxies:
                        if isinstance(p, dict):
                            proxy_names.append(next(iter(p.keys())))
                        else:
                            proxy_names.append(str(p))
                    self.logger.info(f"代理组 '{group_name}' 包含 {len(proxies)} 个代理: {', '.join(proxy_names)}")
    
    def get_api_proxy(self, group_name: Optional[str] = None) -> Optional[str]:
        """
        获取API代理
        
        Args:
            group_name: 指定的代理组名，如果为None则使用配置中默认的api代理组
            
        Returns:
            选择的代理URL或None（表示不使用代理）
        """
        if not self.proxy_config:
            return None
            
        # 如果没有指定组名，使用配置中的默认值
        if group_name is None:
            config_api = self.proxy_config.get('api')
            
            # 如果配置中的值看起来像URL（包含://)，直接返回
            if isinstance(config_api, str) and "://" in config_api:
                # 检查该代理是否被禁用
                if config_api in self.disabled_proxies:
                    if self.logger:
                        self.logger.warning(f"直接配置的API代理 {config_api} 已被禁用，将不使用代理")
                    return None
                    
                if self.logger:
                    self.logger.debug(f"使用配置的直接API代理URL: {config_api}")
                return config_api
                
            group_name = config_api
        
        # 如果组名是空字符串，返回None（不使用代理）
        if not group_name:
            if self.logger:
                self.logger.debug("API代理组名为空，不使用代理")
            return None
            
        # 从组中选择代理
        proxy = self._select_proxy_from_group(group_name, is_api=True)
        if self.logger:
            self.logger.debug(f"为API请求选择代理: {proxy or '无代理'} (来自组 '{group_name}')")
        return proxy
    
    def get_yta_proxy(self, group_name: Optional[str] = None) -> Optional[str]:
        """
        获取YTA代理
        
        Args:
            group_name: 指定的代理组名，如果为None则使用配置中默认的yta代理组
            
        Returns:
            选择的代理URL或None（表示不使用代理）
        """
        if not self.proxy_config:
            return None
            
        # 如果没有指定组名，使用配置中的默认值
        if group_name is None:
            config_yta = self.proxy_config.get('yta')
            
            # 如果配置中的值看起来像URL（包含://)，直接返回
            if isinstance(config_yta, str) and "://" in config_yta:
                # 检查该代理是否被禁用
                if config_yta in self.disabled_proxies:
                    if self.logger:
                        self.logger.warning(f"直接配置的YTA代理 {config_yta} 已被禁用，将不使用代理")
                    return None
                    
                if self.logger:
                    self.logger.debug(f"使用配置的直接YTA代理URL: {config_yta}")
                return config_yta
                
            group_name = config_yta
        
        # 如果组名是空字符串，返回None（不使用代理）
        if not group_name:
            if self.logger:
                self.logger.debug("YTA代理组名为空，不使用代理")
            return None
            
        # 从组中选择代理
        proxy = self._select_proxy_from_group(group_name, is_api=False)
        if self.logger:
            self.logger.debug(f"为YTA请求选择代理: {proxy or '无代理'} (来自组 '{group_name}')")
        return proxy
    
    def _select_proxy_from_group(self, group_name: str, is_api: bool = True) -> Optional[str]:
        """
        从指定的代理组中选择一个代理，会跳过被禁用的代理
        
        Args:
            group_name: 代理组名
            is_api: 是否为API代理（影响使用哪个计数器）
            
        Returns:
            选择的代理URL或None
        """
        if not group_name or not self.proxy_config:
            return None
            
        groups = self.proxy_config.get('groups', {})
        proxy_group = groups.get(group_name, [])
        
        if not proxy_group:
            return None
            
        # 获取所有可用的代理（排除被禁用的）
        available_proxies = []
        disabled_proxies = []
        
        for idx, proxy_item in enumerate(proxy_group):
            proxy_url = self._extract_proxy_url(proxy_item)
            if proxy_url:
                if proxy_url in self.disabled_proxies:
                    # 检查是否已经过了禁用期
                    disable_time = self.disabled_proxies[proxy_url]
                    if time.time() - disable_time >= self.disable_duration:
                        # 禁用期已过，开始测试该代理
                        if self.logger:
                            self.logger.info(f"代理 {proxy_url} 禁用期已过，将进行测试")
                        self._schedule_proxy_test(proxy_url)
                        # 仍然记为禁用状态，直到测试通过
                        disabled_proxies.append((idx, proxy_url))
                    else:
                        disabled_proxies.append((idx, proxy_url))
                else:
                    available_proxies.append((idx, proxy_url))
        
        # 如果没有可用代理，且有禁用代理，记录警告并返回None
        if not available_proxies:
            if disabled_proxies:
                if self.logger:
                    self.logger.warning(f"代理组 '{group_name}' 中所有代理({len(disabled_proxies)}个)都被禁用，无法提供代理")
            return None
            
        # 选择计数器
        counters = self.api_counters if is_api else self.yta_counters
        
        # 线程安全地获取和更新计数器
        with self.lock:
            # 初始化计数器（如果不存在）
            if group_name not in counters:
                counters[group_name] = 0
                
            # 获取当前计数并递增
            current_counter = counters[group_name]
            
            # 在可用代理中找到合适的代理
            proxy_idx = None
            proxy_url = None
            
            # 尝试找到一个当前计数之后的可用代理
            for idx, url in available_proxies:
                if idx >= current_counter:
                    proxy_idx = idx
                    proxy_url = url
                    break
            
            # 如果没找到，取第一个可用代理
            if proxy_idx is None and available_proxies:
                proxy_idx, proxy_url = available_proxies[0]
            
            # 更新计数器
            if proxy_idx is not None:
                counters[group_name] = (proxy_idx + 1) % len(proxy_group)
            
        return proxy_url
    
    def _extract_proxy_url(self, proxy_item: Any) -> Optional[str]:
        """
        从代理项中提取代理URL
        
        Args:
            proxy_item: 代理项，可能是字符串或字典
            
        Returns:
            代理URL或None
        """
        if isinstance(proxy_item, dict):
            # 格式为 {"代理名称": "代理URL"}
            if len(proxy_item) == 1:
                # 获取第一个（也是唯一的）值
                proxy = next(iter(proxy_item.values()))
            else:
                # 如果有多个键值对，记录警告并使用第一个
                if self.logger:
                    self.logger.warning(f"代理项 {proxy_item} 包含多个键值对，将使用第一个")
                proxy = next(iter(proxy_item.values()))
        else:
            # 如果是字符串格式，直接使用
            proxy = proxy_item
        
        # 如果代理是空字符串，返回None
        if proxy == "":
            return None
            
        return proxy
    
    def mark_proxy_failed(self, proxy_url: str, error_message: str = "") -> None:
        """
        标记代理为失败状态，禁用该代理一段时间
        
        Args:
            proxy_url: 失败的代理URL
            error_message: 错误信息
        """
        if not proxy_url:
            return
            
        with self.lock:
            current_time = time.time()
            self.disabled_proxies[proxy_url] = current_time
        
        if self.logger:
            disable_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(current_time))
            expiry_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(current_time + self.disable_duration))
            error_info = f" ({error_message})" if error_message else ""
            self.logger.warning(f"代理 {proxy_url} 已标记为失败{error_info}，禁用至 {expiry_time}")
    
    def _schedule_proxy_test(self, proxy_url: str) -> None:
        """
        安排一个异步任务来测试代理
        
        Args:
            proxy_url: 要测试的代理URL
        """
        # 如果已经有测试任务在运行，不再创建新任务
        if proxy_url in self.test_tasks and not self.test_tasks[proxy_url].done():
            return
            
        # 创建一个新的测试任务
        try:
            loop = asyncio.get_event_loop()
            task = loop.create_task(self._test_proxy(proxy_url))
            self.test_tasks[proxy_url] = task
        except RuntimeError:
            # 如果没有运行中的事件循环，使用线程执行测试
            if self.logger:
                self.logger.debug(f"无法在当前线程创建异步任务，将在下次代理请求时测试代理 {proxy_url}")
    
    async def _test_proxy(self, proxy_url: str) -> None:
        """
        测试代理是否可用，使用YouTube频道检查功能进行实际测试
        
        Args:
            proxy_url: 要测试的代理URL
        """
        if self.logger:
            self.logger.debug(f"开始使用YouTube API测试代理 {proxy_url}")
        
        try:
            # 动态导入youtubeCheck模块
            from core.youtubeCheck import _do_youtube_check
            
            # 使用youtubeCheck进行测试 - 只调用内部的直接请求函数
            result = await _do_youtube_check(
                channel_id=self.test_channel_id,
                api_proxy=proxy_url,
                logger=self.logger
            )
            
            # 检查结果
            if result is not None:  # 即使没有直播，只要能成功请求到数据就算成功
                # 测试成功，移除禁用状态
                with self.lock:
                    if proxy_url in self.disabled_proxies:
                        del self.disabled_proxies[proxy_url]
                if self.logger:
                    self.logger.info(f"代理 {proxy_url} 通过YouTube API测试成功，已重新启用")
                return True
            else:
                # 测试失败，更新禁用时间
                current_time = time.time()
                with self.lock:
                    self.disabled_proxies[proxy_url] = current_time
                if self.logger:
                    expiry_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(current_time + self.disable_duration))
                    self.logger.warning(f"代理 {proxy_url} 无法获取YouTube数据，继续禁用至 {expiry_time}")
                return False
                
        except Exception as e:
            # 测试出错，更新禁用时间
            current_time = time.time()
            with self.lock:
                self.disabled_proxies[proxy_url] = current_time
            if self.logger:
                expiry_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(current_time + self.disable_duration))
                self.logger.warning(f"代理 {proxy_url} 测试YouTube API失败 (错误: {e})，继续禁用至 {expiry_time}")
            return False
    
    async def test_proxy_with_youtube(self, proxy_url: str) -> Dict[str, Any]:
        """
        使用YouTube API测试代理并返回结果信息
        
        Args:
            proxy_url: 要测试的代理URL
            
        Returns:
            Dict: 测试结果，包含status, message等信息
        """
        if self.logger:
            self.logger.info(f"开始使用YouTube API测试代理 {proxy_url}")
        
        try:
            # 动态导入youtubeCheck模块
            from core.youtubeCheck import _do_youtube_check
            
            # 记录开始时间
            start_time = time.time()
            
            # 使用youtubeCheck进行测试
            result = await _do_youtube_check(
                channel_id=self.test_channel_id,
                api_proxy=proxy_url,
                logger=self.logger
            )
            
            # 计算耗时
            elapsed = time.time() - start_time
            
            # 检查结果
            if result is not None:  # 即使没有直播，只要能成功请求到数据就算成功
                with self.lock:
                    if proxy_url in self.disabled_proxies:
                        del self.disabled_proxies[proxy_url]
                
                self.logger.info(f"代理 {proxy_url} 通过YouTube API测试成功，响应时间: {elapsed:.2f}秒")
                return {
                    "status": "success",
                    "message": f"通过YouTube API测试成功，响应时间: {elapsed:.2f}秒",
                    "response_time": elapsed,
                    "has_live": len(result) > 0
                }
            else:
                self.logger.warning(f"代理 {proxy_url} 无法获取YouTube数据")
                return {
                    "status": "error",
                    "message": "代理无法获取YouTube数据，请求失败",
                    "response_time": elapsed
                }
        except Exception as e:
            self.logger.error(f"使用YouTube API测试代理 {proxy_url} 时出错: {e}")
            return {
                "status": "error",
                "message": f"测试出错: {str(e)}",
                "error": str(e)
            }
    
    def get_disabled_proxies(self) -> Dict[str, float]:
        """
        获取当前被禁用的代理列表
        
        Returns:
            Dict[str, float]: 键为代理URL，值为禁用时间戳
        """
        with self.lock:
            return self.disabled_proxies.copy()
            
    def clear_disabled_proxies(self) -> None:
        """
        清除所有被禁用的代理
        """
        with self.lock:
            self.disabled_proxies.clear()
        if self.logger:
            self.logger.info("已清除所有被禁用的代理")

# 创建全局代理管理器实例
proxy_manager = ProxyManager()