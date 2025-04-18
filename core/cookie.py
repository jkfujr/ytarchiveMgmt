"""
Cookie 管理模块 - 负责管理多个cookie文件并提供随机选择功能
"""

import os
import random
import datetime
import asyncio
from typing import Optional, Dict, Any, List

class CookieManager:
    """Cookie管理器类，处理多个cookie文件的管理和随机选择"""
    
    def __init__(self, cookie_config: Dict[str, Any] = None, logger=None):
        """
        初始化Cookie管理器
        
        Args:
            cookie_config: Cookie配置字典，包含enable和path配置
            logger: 日志记录器
        """
        self.cookie_config = cookie_config or {}
        self.logger = logger
        self.enabled = self.cookie_config.get('enable', False)
        self.cookies_path = self.cookie_config.get('path', '')
        self.cookie_files = []
        self.reload_cookie_files()
        
        # 定时更新相关的属性
        ## 异步定时更新任务
        self.update_task = None
        ## 是否正在更新
        self.updating = False
        ## 上次更新时间
        self.last_update_time = None
        ## 下次更新时间列表
        self.next_update_times = []
        
        if self.logger:
            if self.enabled:
                self.logger.info(f"Cookie管理器已启用，路径: {self.cookies_path or '默认cookies目录'}")
                self.logger.info(f"已加载 {len(self.cookie_files)} 个cookie文件")
            else:
                self.logger.info("Cookie管理器已禁用")
    
    def reload_cookie_files(self):
        """重新加载cookie文件列表"""
        if not self.enabled:
            self.cookie_files = []
            return
            
        cookies_dir = self.cookies_path
        if not cookies_dir:
            cookies_dir = os.path.join(os.getcwd(), 'cookies')
            
        os.makedirs(cookies_dir, exist_ok=True)
        
        self.cookie_files = []
        try:
            for file in os.listdir(cookies_dir):
                if file.endswith('.txt'):
                    full_path = os.path.join(cookies_dir, file)
                    if os.path.isfile(full_path):
                        self.cookie_files.append(full_path)
                        
            if self.logger:
                if self.cookie_files:
                    self.logger.info(f"已加载 {len(self.cookie_files)} 个cookie文件")
                else:
                    self.logger.warning(f"在 {cookies_dir} 目录中未找到任何cookie文件")
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载cookie文件时出错: {e}")
    
    def get_random_cookie_file(self) -> Optional[str]:
        """
        随机选择一个cookie文件
        
        Returns:
            Optional[str]: 随机选择的cookie文件路径，如果没有可用cookie则返回None
        """
        if not self.enabled or not self.cookie_files:
            return None
            
        cookie_file = random.choice(self.cookie_files)
        
        if self.logger:
            self.logger.debug(f"随机选择cookie文件: {cookie_file}")
            
        return cookie_file
    
    def set_config(self, cookie_config: Dict[str, Any]):
        """
        设置或更新cookie配置
        
        Args:
            cookie_config: 新的cookie配置
        """
        self.cookie_config = cookie_config or {}
        self.enabled = self.cookie_config.get('enable', False)
        self.cookies_path = self.cookie_config.get('path', '')
        self.reload_cookie_files()
        
        if self.logger:
            if self.enabled:
                self.logger.info(f"Cookie管理器配置已更新，路径: {self.cookies_path or '默认cookies目录'}")
                self.logger.info(f"已加载 {len(self.cookie_files)} 个cookie文件")
            else:
                self.logger.info("Cookie管理器已禁用")
    
    async def refresh_cookie(self, cookie_file: str) -> bool:
        """
        使用yt-dlp刷新单个cookie文件
        
        Args:
            cookie_file: cookie文件路径
            
        Returns:
            bool: 是否成功刷新
        """
        if not os.path.exists(cookie_file):
            if self.logger:
                self.logger.error(f"cookie文件不存在: {cookie_file}")
            return False
            
        try:
            cmd = ["yt-dlp", "--cookies", cookie_file, "--simulate", "https://youtube.com/watch?v=ODPDaIwVc-U"]
            
            if self.logger:
                self.logger.info(f"开始刷新cookie文件: {os.path.basename(cookie_file)}")
                
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                if self.logger:
                    self.logger.info(f"成功刷新cookie文件: {os.path.basename(cookie_file)}")
                return True
            else:
                error_msg = stderr.decode('utf-8', errors='replace')
                if self.logger:
                    self.logger.error(f"刷新cookie文件失败: {os.path.basename(cookie_file)}, 错误: {error_msg}")
                return False
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"刷新cookie文件时出错: {os.path.basename(cookie_file)}, 异常: {e}")
            return False
    
    async def refresh_all_cookies(self):
        """刷新所有cookie文件"""
        if not self.enabled or not self.cookie_files:
            if self.logger:
                self.logger.warning("Cookie管理器未启用或没有cookie文件，跳过刷新")
            return
            
        if self.updating:
            if self.logger:
                self.logger.warning("已有cookie刷新任务正在进行，跳过本次刷新")
            return
            
        self.updating = True
        self.last_update_time = datetime.datetime.now()
        
        try:
            if self.logger:
                self.logger.info(f"开始刷新所有cookie文件，共 {len(self.cookie_files)} 个")
                
            # 重新加载确保最新状态
            self.reload_cookie_files()
            
            success_count = 0
            fail_count = 0
            
            for cookie_file in self.cookie_files:
                success = await self.refresh_cookie(cookie_file)
                if success:
                    success_count += 1
                else:
                    fail_count += 1
                # 短暂等待，避免连续请求
                await asyncio.sleep(2)
                
            if self.logger:
                self.logger.info(f"所有cookie文件刷新完成: 成功 {success_count} 个, 失败 {fail_count} 个")
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"刷新所有cookie时出错: {e}")
        finally:
            self.updating = False
            # 安排下一次更新
            self._schedule_next_updates()
    
    def _schedule_next_updates(self):
        """安排下一次更新的时间点"""
        # 获取当前时间
        now = datetime.datetime.now()
        today = now.date()
        tomorrow = today + datetime.timedelta(days=1)
        
        # 定义两个时间区间
        morning_start = datetime.datetime.combine(today, datetime.time(10, 0))
        morning_end = datetime.datetime.combine(today, datetime.time(12, 0))
        
        night_start = datetime.datetime.combine(today, datetime.time(22, 0))
        night_end = datetime.datetime.combine(today, datetime.time(23, 59, 59))
        
        # 明天的时间区间
        tomorrow_morning_start = datetime.datetime.combine(tomorrow, datetime.time(10, 0))
        tomorrow_morning_end = datetime.datetime.combine(tomorrow, datetime.time(12, 0))
        
        tomorrow_night_start = datetime.datetime.combine(tomorrow, datetime.time(22, 0))
        tomorrow_night_end = datetime.datetime.combine(tomorrow, datetime.time(23, 59, 59))
        
        # 清空之前的安排
        self.next_update_times = []
        
        # 根据当前时间确定下次更新时间
        if now < morning_start:
            # 今天的两个时段都还没到
            self._add_random_time(morning_start, morning_end)
            self._add_random_time(night_start, night_end)
        elif now < morning_end:
            # 正处于早上时段，只安排今天晚上和明天的
            self._add_random_time(night_start, night_end)
            self._add_random_time(tomorrow_morning_start, tomorrow_morning_end)
        elif now < night_start:
            # 早上已过，晚上未到
            self._add_random_time(night_start, night_end)
            self._add_random_time(tomorrow_morning_start, tomorrow_morning_end)
        elif now < night_end:
            # 正处于晚上时段，安排明天的两个时段
            self._add_random_time(tomorrow_morning_start, tomorrow_morning_end)
            self._add_random_time(tomorrow_night_start, tomorrow_night_end)
        else:
            # 今天已经结束，安排明天的两个时段
            self._add_random_time(tomorrow_morning_start, tomorrow_morning_end)
            self._add_random_time(tomorrow_night_start, tomorrow_night_end)
        
        if self.logger:
            time_strs = [t.strftime("%Y-%m-%d %H:%M:%S") for t in self.next_update_times]
            self.logger.info(f"已安排下次cookie更新时间: {', '.join(time_strs)}")
    
    def _add_random_time(self, start_time: datetime.datetime, end_time: datetime.datetime):
        """在指定时间范围内添加一个随机时间"""
        # 计算时间范围内的总秒数
        time_delta = (end_time - start_time).total_seconds()
        # 随机选择一个偏移量（秒）
        random_seconds = int(random.uniform(0, time_delta))
        # 计算随机时间点
        random_time = start_time + datetime.timedelta(seconds=random_seconds)
        # 添加到下次更新时间列表
        self.next_update_times.append(random_time)
    
    async def _update_scheduler(self):
        """定时器，负责在指定时间执行cookie更新"""
        try:
            # 初始化时安排下次更新时间
            self._schedule_next_updates()
            
            while True:
                if not self.enabled:
                    # 如果cookie管理器被禁用，等待一段时间后重新检查
                    await asyncio.sleep(3600)  # 一小时后重新检查
                    continue
                
                now = datetime.datetime.now()
                
                # 检查是否有需要执行的更新任务
                for update_time in self.next_update_times[:]:
                    if now >= update_time:
                        # 时间到，执行更新
                        self.next_update_times.remove(update_time)
                        await self.refresh_all_cookies()
                        break
                
                # 如果没有安排的更新时间，重新安排
                if not self.next_update_times:
                    self._schedule_next_updates()
                
                # 计算最近的更新时间
                if self.next_update_times:
                    next_time = min(self.next_update_times)
                    wait_seconds = (next_time - now).total_seconds()
                    # 如果等待时间小于0，立即检查
                    wait_seconds = max(1, wait_seconds)
                    # 如果等待时间太长，设定一个最大等待时间，定期重新检查
                    wait_seconds = min(wait_seconds, 3600)
                else:
                    # 如果没有安排的更新时间，等待一小时后重新检查
                    wait_seconds = 3600
                
                await asyncio.sleep(wait_seconds)
        
        except asyncio.CancelledError:
            # 任务被取消
            if self.logger:
                self.logger.info("Cookie定时更新任务已取消")
            raise
        except Exception as e:
            # 发生异常，记录错误并继续运行
            if self.logger:
                self.logger.error(f"Cookie定时更新任务出错: {e}")
            # 等待一段时间后重新启动定时器
            await asyncio.sleep(300)  # 5分钟后重试
            asyncio.create_task(self._update_scheduler())
    
    def start_update_scheduler(self):
        """启动cookie定时更新任务"""
        if self.update_task is None or self.update_task.done():
            self.update_task = asyncio.create_task(self._update_scheduler())
            if self.logger:
                self.logger.info("已启动Cookie定时更新任务")
    
    def stop_update_scheduler(self):
        """停止cookie定时更新任务"""
        if self.update_task and not self.update_task.done():
            self.update_task.cancel()
            if self.logger:
                self.logger.info("已停止Cookie定时更新任务")
            self.update_task = None
    
    def is_update_scheduler_running(self) -> bool:
        """检查cookie定时更新任务是否正在运行"""
        return self.update_task is not None and not self.update_task.done()
    
    def get_next_update_times(self) -> List[datetime.datetime]:
        """获取下次更新时间列表"""
        return self.next_update_times.copy()
    
    def get_update_status(self) -> Dict[str, Any]:
        """获取更新状态信息"""
        return {
            "enabled": self.enabled,
            "updating": self.updating,
            "last_update_time": self.last_update_time.strftime("%Y-%m-%d %H:%M:%S") if self.last_update_time else None,
            "next_update_times": [t.strftime("%Y-%m-%d %H:%M:%S") for t in self.next_update_times],
            "scheduler_running": self.is_update_scheduler_running()
        }
    
    async def manually_refresh_cookies(self) -> Dict[str, Any]:
        """手动触发cookie刷新"""
        if self.updating:
            return {
                "status": "busy",
                "message": "已有cookie刷新任务正在进行，请稍后再试"
            }
            
        # 创建一个新的任务执行刷新
        asyncio.create_task(self.refresh_all_cookies())
        
        return {
            "status": "started",
            "message": f"已开始刷新 {len(self.cookie_files)} 个cookie文件"
        }

# 创建全局Cookie管理器实例
cookie_manager = CookieManager() 