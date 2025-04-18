import re, os, subprocess, threading, logging
from typing import Dict, List, Any, Optional
from pathlib import Path

from core.logs import get_ytarchive_logger, get_channel_logger
from core.proxy import proxy_manager
from core.cookie import cookie_manager

class ChannelConfig:
    """频道配置，存储每个频道的配置信息"""
    def __init__(self, id: str, name: str, proxy: Optional[str] = None, output: Optional[str] = None,
                 autoRecord: Optional[bool] = None, autoCheck: Optional[bool] = None, options: Dict[str, Any] = None):
        self.id = id
        self.name = name
        self.proxy = proxy
        self.output = output
        self.autoRecord = autoRecord
        self.autoCheck = autoCheck
        self.options = options or {}

class ChannelProcess:
    """频道进程类，管理每个频道的 ytarchive 进程"""
    def __init__(self, config: ChannelConfig, ytarchive_path: str, global_proxy: Optional[str] = None, 
                 global_output: Optional[str] = None, global_output_file: Optional[str] = None,
                 global_options: Dict[str, Any] = None, logger: logging.Logger = None):
        """
        初始化频道进程
        
        Args:
            config: 频道配置
            ytarchive_path: ytarchive 可执行文件路径
            global_proxy: 全局代理设置
            global_output: 全局输出路径模板
            global_output_file: 全局输出文件名模板
            global_options: 全局 ytarchive 选项
            logger: 日志记录器
        """
        self.config = config
        self.ytarchive_path = ytarchive_path
        self.global_proxy = global_proxy
        self.global_output = global_output
        self.global_output_file = global_output_file
        self.global_options = global_options or {}
        self.logger = logger
        self.channel_logger = get_channel_logger(self.config.name)
        self.ytarchive_logger = None 
        self.process = None
        self.pid = None
        self.thread = None
        self.running = False
        self.logs = []
        self.log_lock = threading.Lock()
        self.current_proxy = None  # 当前使用的代理URL

    def start(self):
        """启动 ytarchive 进程"""
        cmd = self.build_command()
        self.setup_logging()
        try:
            self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8')
            self.pid = self.process.pid
            self.running = True
            self.thread = threading.Thread(target=self.read_output, daemon=True)
            self.thread.start()
            if self.logger:
                self.logger.info(f"已启动频道 {self.config.name} ({self.config.id}) 的监控，PID: {self.pid}")
            
            self.channel_logger.info(f"已启动 ytarchive 进程监控，PID: {self.pid}")
        except Exception as e:
            error_msg = f"启动频道 {self.config.name} ({self.config.id}) 的进程时出错：{e}"
            if self.logger:
                self.logger.error(error_msg)
            self.channel_logger.error(error_msg)

    def stop(self):
        """停止 ytarchive 进程"""
        if self.process and self.running:
            self.process.terminate()
            self.process.wait()
            self.pid = None
            self.running = False
            if self.thread and self.thread.is_alive():
                self.thread.join()
                
            if self.logger:
                self.logger.info(f"已停止频道 {self.config.name} ({self.config.id}) 的监控")
            
            self.channel_logger.info(f"已停止 ytarchive 进程监控")

    def build_command(self) -> List[str]:
        """构建 ytarchive 命令行参数"""
        cmd = [self.ytarchive_path]

        combined_options = self.global_options.copy()
        combined_options.update(self.config.options)

        # 处理随机cookie
        random_cookie_file = cookie_manager.get_random_cookie_file()
        if random_cookie_file:
            # 如果options里已经有-c选项，移除它
            if '-c' in combined_options:
                cookie_path = combined_options.pop('-c')
                if self.logger:
                    self.logger.info(f"替换固定cookie文件 {cookie_path} 为随机选择的cookie文件")
                self.channel_logger.info(f"替换固定cookie文件为随机选择的cookie文件")
            
            # 添加随机选择的cookie文件
            combined_options['-c'] = random_cookie_file
            if self.logger:
                self.logger.info(f"使用随机cookie文件: {random_cookie_file}")
            self.channel_logger.info(f"使用随机cookie文件: {os.path.basename(random_cookie_file)}")

        for option, value in combined_options.items():
            if isinstance(value, bool):
                if value:
                    cmd.append(option)
            else:
                cmd.extend([option, str(value)])

        output_template = self.config.output or self.global_output
        if not output_template:
            output_template = '{{ name }}_{{ id }}'

        output_path = output_template.replace('{{ id }}', self.config.id).replace('{{ name }}', self.config.name)
        output_path = os.path.normpath(output_path)

        if not os.path.isabs(output_path):
            output_path = os.path.join(os.getcwd(), 'output', output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        output_file_template = self.config.options.get('output_file') or self.global_output_file or "%(upload_date)s_%(title)s"
        output_path = os.path.join(output_path, output_file_template)

        cmd.extend(['-o', output_path])

        # 优先使用频道特定代理，其次使用代理管理器获取代理
        proxy = self.config.proxy
        if not proxy:
            # 如果频道没有指定代理，则使用代理管理器获取YTA代理
            proxy = proxy_manager.get_yta_proxy()
            
        if proxy:
            self.current_proxy = proxy  # 记录当前使用的代理
            cmd.extend(['--proxy', proxy])

        channel_url = f'https://www.youtube.com/channel/{self.config.id}/live'
        cmd.append(channel_url)
        cmd.append('best')

        return cmd

    def setup_logging(self):
        """设置频道的日志记录"""
        self.ytarchive_logger = get_ytarchive_logger(self.config.name)

    def read_output(self):
        """读取 ytarchive 进程的输出"""
        while self.running and self.process.poll() is None:
            line = self.process.stdout.readline()
            if line:
                with self.log_lock:
                    self.ytarchive_logger.info(line.strip())
                    self.logs.append(line.strip())
                    if len(self.logs) > 1000:
                        self.logs = self.logs[-500:]
        self.running = False
        self.channel_logger.info("ytarchive 进程已退出")

    def parse_latest_status(self) -> dict:
        """解析最近日志，获取录制状态、直播标题、清晰度、开播时间、文件大小等信息"""
        status_info = {
            "recording_state": None,
            "video_title": None,
            "quality": None,
            "start_time": None,
            "file_size": None,
        }
        
        if self.logs:
            for line in reversed(self.logs):
                self._parse_log_line(line, status_info)
                if all(status_info.values()):
                    break
        
        if not any(status_info.values()):
            log_file = Path(f'logs/{self.config.name}/ytarchive/ytarchive.log')
            if log_file.exists():
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    
                    for line in reversed(lines):
                        self._parse_log_line(line, status_info)
                        if all(status_info.values()):
                            break
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"读取日志文件出错: {e}")
        
        return status_info
    
    def _parse_log_line(self, line: str, status_info: dict):
        """从单行日志中解析信息"""
        match_recording = re.search(r"Video Fragments:\s*\d+;\s*Audio Fragments:\s*\d+;\s*Total Downloaded:\s*(\S+)", line)
        if match_recording:
            status_info["recording_state"] = "录制中"
            status_info["file_size"] = match_recording.group(1)
                
        match_monitor = re.search(r"Retries:\s*(\d+).+Total time waited:\s*(\d+)\s*seconds", line)
        if match_monitor and status_info["recording_state"] is None:
            status_info["recording_state"] = "监控中"

        match_title = re.search(r"Video Title:\s*(.+)$", line)
        if match_title and not status_info["video_title"]:
            status_info["video_title"] = match_title.group(1).strip()

        match_quality = re.search(r"Selected quality:\s*(.+)$", line)
        if match_quality and not status_info["quality"]:
            status_info["quality"] = match_quality.group(1).strip()

        match_start_time = re.search(r"Stream started at time\s*(.+)$", line)
        if match_start_time and not status_info["start_time"]:
            status_info["start_time"] = match_start_time.group(1).strip()

    def check_ytarchive_errors(self) -> Optional[str]:
        """检查ytarchive进程的最新日志中是否存在错误
        
        Returns:
            Optional[str]: 如果发现错误，返回错误信息；否则返回None
        """
        if not self.logs:
            return None
            
        # 检查最新的几条日志
        for line in reversed(self.logs[-10:]):  # 只检查最新的10条日志
            if "Video Details not found, video is likely private or does not exist" in line:
                return line.strip()
                
        return None

    def get_current_proxy(self) -> Optional[str]:
        """获取当前使用的代理URL"""
        return self.current_proxy

class ChannelManager:
    """频道管理器，管理多个频道的 ytarchive 进程"""
    def __init__(self, logger: logging.Logger = None):
        """
        初始化频道管理器
        
        Args:
            logger: 日志记录器
        """
        self.logger = logger
        self.channels: Dict[str, ChannelProcess] = {}

    def initialize_channels(self, channels: List[ChannelConfig], ytarchive_path: str, 
                           global_output: Optional[str] = None,
                           global_output_file: Optional[str] = None, global_options: Dict[str, Any] = None, 
                           auto_record: bool = False):
        """
        初始化频道列表
        
        Args:
            channels: 频道配置列表
            ytarchive_path: ytarchive 可执行文件路径
            global_output: 全局输出路径模板
            global_output_file: 全局输出文件名模板
            global_options: 全局 ytarchive 选项
            auto_record: 是否自动启动录制
        """
        for channel_config in channels:
            channel_process = ChannelProcess(
                config=channel_config, 
                ytarchive_path=ytarchive_path,
                global_proxy=None,  # 不再使用global_proxy，而是通过proxy_manager获取
                global_output=global_output,
                global_output_file=global_output_file,
                global_options=global_options,
                logger=self.logger
            )
            self.channels[channel_config.id] = channel_process
            
            if self.logger:
                self.logger.info(f"已初始化频道 {channel_config.name} ({channel_config.id})")
            
            channel_logger = get_channel_logger(channel_config.name)
            channel_logger.info(f"频道初始化完成，ID: {channel_config.id}")

    def start_channel(self, channel_id: str) -> bool:
        """
        启动指定频道的监控
        
        Args:
            channel_id: 频道ID
            
        Returns:
            bool: 是否成功启动
        """
        channel_process = self.channels.get(channel_id)
        if channel_process and not channel_process.running:
            channel_process.start()
            
            channel_logger = get_channel_logger(channel_process.config.name)
            channel_logger.info(f"已启动频道录制")
            
            return True
        return False

    def stop_channel(self, channel_id: str) -> bool:
        """
        停止指定频道的监控
        
        Args:
            channel_id: 频道ID
            
        Returns:
            bool: 是否成功停止
        """
        channel_process = self.channels.get(channel_id)
        if channel_process and channel_process.running:
            channel_process.stop()
            
            # 记录到频道专用日志
            channel_logger = get_channel_logger(channel_process.config.name)
            channel_logger.info(f"已停止频道录制")
            
            return True
        return False

    def add_channel(self, channel_config: ChannelConfig, ytarchive_path: str, 
                    global_output: Optional[str] = None,
                    global_output_file: Optional[str] = None, global_options: Dict[str, Any] = None,
                    auto_record: bool = False) -> bool:
        """
        添加新频道
        
        Args:
            channel_config: 频道配置
            ytarchive_path: ytarchive 可执行文件路径
            global_output: 全局输出路径模板
            global_output_file: 全局输出文件名模板
            global_options: 全局 ytarchive 选项
            auto_record: 是否自动启动录制
            
        Returns:
            bool: 是否成功添加
        """
        if channel_config.id in self.channels:
            return False
            
        channel_process = ChannelProcess(
            config=channel_config, 
            ytarchive_path=ytarchive_path,
            global_proxy=None,  # 不再使用global_proxy，而是通过proxy_manager获取
            global_output=global_output,
            global_output_file=global_output_file,
            global_options=global_options,
            logger=self.logger
        )
        self.channels[channel_config.id] = channel_process
        
        # 记录到频道专用日志
        channel_logger = get_channel_logger(channel_config.name)
        channel_logger.info(f"频道已添加，ID: {channel_config.id}")
        
        # 检查是否需要自动录制
        should_record = channel_config.autoRecord if channel_config.autoRecord is not None else auto_record
        if should_record:
            channel_process.start()
            channel_logger.info("根据配置自动启动录制")
            
        return True

    def remove_channel(self, channel_id: str) -> bool:
        """
        删除指定频道
        
        Args:
            channel_id: 频道ID
            
        Returns:
            bool: 是否成功删除
        """
        channel_process = self.channels.pop(channel_id, None)
        if channel_process:
            # 记录到频道日志
            channel_logger = get_channel_logger(channel_process.config.name)
            channel_logger.info(f"频道已被删除")
            
            # 停止进程
            channel_process.stop()
            return True
        return False
        
    def get_channel_status(self, channel_id: str) -> Optional[dict]:
        """
        获取频道状态
        
        Args:
            channel_id: 频道ID
            
        Returns:
            Optional[dict]: 频道状态信息
        """
        channel_process = self.channels.get(channel_id)
        if not channel_process:
            return None
            
        if not channel_process.running:
            return {
                "running": False,
                "pid": None,
                "recording_state": None,
                "video_title": None,
                "quality": None,
                "start_time": None,
                "file_size": None,
            }
            
        status_info = channel_process.parse_latest_status()
        return {
            "running": True,
            "pid": channel_process.pid,
            "recording_state": status_info.get("recording_state"),
            "video_title": status_info.get("video_title"),
            "quality": status_info.get("quality"),
            "start_time": status_info.get("start_time"),
            "file_size": status_info.get("file_size"),
        }
        
    def get_channel_logs(self, channel_id: str) -> List[str]:
        """
        获取频道日志
        
        Args:
            channel_id: 频道ID
            
        Returns:
            List[str]: 日志列表
        """
        channel_process = self.channels.get(channel_id)
        if channel_process:
            return channel_process.logs
        return []
        
    def get_all_channels_status(self) -> List[Dict[str, Any]]:
        """
        获取所有频道的状态
        
        Returns:
            List[Dict[str, Any]]: 所有频道的状态信息
        """
        channels_status = []
        for channel_id, channel_process in self.channels.items():
            status = {
                "id": channel_process.config.id,
                "name": channel_process.config.name,
                "running": channel_process.running,
                "pid": channel_process.pid,
                "is_live": False,
                "recording_state": None,
                "video_title": None
            }
            
            if channel_process.running:
                detailed_status = channel_process.parse_latest_status()
                status["recording_state"] = detailed_status.get("recording_state")
                status["video_title"] = detailed_status.get("video_title")
                status["is_live"] = detailed_status.get("recording_state") == "录制中"
                
            channels_status.append(status)
        
        return channels_status 

    def restart_channel_with_new_proxy(self, channel_id: str) -> bool:
        """重启频道并更换代理
        
        Args:
            channel_id: 频道ID
            
        Returns:
            bool: 是否成功重启
        """
        channel_process = self.channels.get(channel_id)
        if not channel_process:
            return False
            
        # 获取当前使用的代理
        current_proxy = channel_process.get_current_proxy()
        if current_proxy:
            # 标记当前代理为失败
            proxy_manager.mark_proxy_failed(current_proxy, "ytarchive进程报错")
            if self.logger:
                self.logger.warning(f"频道 {channel_process.config.name} ({channel_id}) 的代理 {current_proxy} 已标记为失败")
            
            channel_logger = get_channel_logger(channel_process.config.name)
            channel_logger.warning(f"代理 {current_proxy} 已标记为失败")
        
        # 停止当前进程
        self.stop_channel(channel_id)
        
        # 重新启动进程（会自动获取新的代理）
        success = self.start_channel(channel_id)
        
        if success:
            if self.logger:
                self.logger.info(f"频道 {channel_process.config.name} ({channel_id}) 已使用新代理重启")
            channel_logger = get_channel_logger(channel_process.config.name)
            channel_logger.info("已使用新代理重启录制")
            return True
            
        return False

    def check_all_channels_errors(self) -> List[Dict[str, Any]]:
        """检查所有频道的ytarchive错误
        
        Returns:
            List[Dict[str, Any]]: 错误信息列表，每个元素包含channel_id和error_message
        """
        errors = []
        for channel_id, channel_process in self.channels.items():
            if not channel_process.running:
                continue
                
            error_message = channel_process.check_ytarchive_errors()
            if error_message:
                errors.append({
                    "channel_id": channel_id,
                    "channel_name": channel_process.config.name,
                    "error_message": error_message,
                    "current_proxy": channel_process.get_current_proxy()
                })
                
        return errors 