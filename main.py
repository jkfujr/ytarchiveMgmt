# main.py

import os
import subprocess
import threading
import uvicorn
import logging
from logging.handlers import TimedRotatingFileHandler
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from typing import Dict, List, Any, Optional
from pathlib import Path
from pydantic import BaseModel
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import DoubleQuotedScalarString
import re
from datetime import datetime, timezone, timedelta

# 设置主程序日志
main_logs_dir = Path('logs/main')
main_logs_dir.mkdir(parents=True, exist_ok=True)
main_log_file = main_logs_dir / 'main.log'
main_logger = logging.getLogger('main')
main_logger.setLevel(logging.INFO)
main_handler = TimedRotatingFileHandler(main_log_file, when='midnight', backupCount=30, encoding='utf-8')
main_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
main_handler.setFormatter(main_formatter)
main_logger.addHandler(main_handler)

class ChannelConfig:
    """
    频道配置, 存储每个频道的配置信息
    """
    def __init__(self, id: str, name: str, proxy: Optional[str] = None, output: Optional[str] = None,
                 autoRecord: Optional[bool] = None, options: Dict[str, Any] = None):
        self.id = id
        self.name = name
        self.proxy = proxy
        self.output = output
        self.autoRecord = autoRecord
        self.options = options or {}

class GlobalConfig:
    """
    全局配置, 存储程序的全局配置信息
    """
    def __init__(self, ytarchive: str, proxy: Optional[str] = None, output: Optional[str] = None,
                 autoRecord: Optional[bool] = None, options: Dict[str, Any] = None,
                 users: List[ChannelConfig] = None, output_time_tz: str = "UTC", output_file: Optional[str] = None):
        self.ytarchive = ytarchive
        self.proxy = proxy
        self.output = output
        self.autoRecord = autoRecord
        self.options = options or {}
        self.users = users or []
        self.output_time_tz = output_time_tz
        self.output_file = output_file

def load_config() -> GlobalConfig:
    try:
        yaml = YAML()
        yaml.preserve_quotes = True
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config_dict = yaml.load(f)
    except FileNotFoundError:
        main_logger.error("配置文件 config.yaml 未找到")
        raise

    ytarchive = config_dict.get('ytarchive')
    proxy = config_dict.get('proxy')
    output = config_dict.get('output')
    autoRecord = config_dict.get('autoRecord', False)
    options = config_dict.get('options', {})
    output_time_tz = config_dict.get('output_time_tz', "UTC")
    output_file = config_dict.get('output_file')  # 从顶层读取 output_file
    users = []
    for user in config_dict.get('user', []):
        id = user.get('id')
        name = user.get('name')
        user_proxy = user.get('proxy')
        user_output = user.get('output')
        user_autoRecord = user.get('autoRecord')
        user_options = user.get('options', {})
        channel = ChannelConfig(
            id=id, name=name, proxy=user_proxy, output=user_output,
            autoRecord=user_autoRecord, options=user_options
        )
        users.append(channel)
    global_config = GlobalConfig(
        ytarchive=ytarchive, proxy=proxy, output=output,
        autoRecord=autoRecord, options=options, users=users,
        output_time_tz=output_time_tz, output_file=output_file
    )
    return global_config

def save_config():
    """
    保存配置到 config.yaml，保留注释和格式
    """
    yaml = YAML()
    # 保留引号
    yaml.preserve_quotes = True
    # 允许 Unicode 字符
    yaml.allow_unicode = True
    # 设置行宽，防止自动换行
    yaml.width = 1000
    # 设置缩进
    yaml.indent(mapping=2, sequence=4, offset=2)

    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config_dict = yaml.load(f)
    except FileNotFoundError:
        main_logger.error("配置文件 config.yaml 未找到")
        return

    # 更新全局配置项
    if global_config.ytarchive:
        config_dict['ytarchive'] = DoubleQuotedScalarString(global_config.ytarchive)
    if global_config.proxy:
        config_dict['proxy'] = global_config.proxy
    if global_config.output:
        config_dict['output'] = global_config.output
    config_dict['output_time_tz'] = DoubleQuotedScalarString(global_config.output_time_tz)
    config_dict['output_file'] = global_config.output_file or "%(upload_date)s_%(title)s"
    config_dict['autoRecord'] = global_config.autoRecord
    config_dict['options'] = global_config.options

    # 更新用户列表
    existing_users = config_dict.get('user', [])
    existing_user_ids = [user.get('id') for user in existing_users]

    # 遍历程序中的用户列表，检查是否有新用户
    for user in global_config.users:
        if user.id not in existing_user_ids:
            user_dict = {
                'id': DoubleQuotedScalarString(user.id),
                'name': DoubleQuotedScalarString(user.name),
            }
            if user.proxy is not None:
                user_dict['proxy'] = user.proxy
            if user.output is not None:
                user_dict['output'] = user.output
            if user.autoRecord is not None:
                user_dict['autoRecord'] = user.autoRecord
            if user.options:
                user_dict['options'] = user.options
            existing_users.append(user_dict)
            existing_user_ids.append(user.id)
    config_dict['user'] = existing_users

    with open('config.yaml', 'w', encoding='utf-8') as f:
        yaml.dump(config_dict, f)

def parse_timezone(tz_str: str) -> timezone:
    """
    解析时区字符串，如 "UTC", "UTC+8", "UTC-5"。
    返回一个 timezone 对象。
    """
    if tz_str.upper() == "UTC":
        return timezone.utc
    match = re.match(r"UTC([+-])(\d+)", tz_str.upper())
    if match:
        sign, hours = match.groups()
        offset_hours = int(hours)
        if sign == '-':
            offset_hours = -offset_hours
        return timezone(timedelta(hours=offset_hours))
    # 如果格式不匹配，默认返回 UTC
    return timezone.utc

def replace_time_variables(template: str, tz_str: str = "UTC") -> str:
    """
    替换路径或文件名模板中的时间变量。
    支持以下变量:
        {{ YYYY }} - 年
        {{ MM }} - 月
        {{ DD }} - 日
        {{ HH }} - 时
        {{ mm }} - 分
        {{ ss }} - 秒
        {{ YYYYMMDD }} - 年月日
        {{ HHmmss }} - 时分秒
    支持时区配置，如 "UTC", "UTC+8", "UTC-5"
    """
    tz = parse_timezone(tz_str)
    now = datetime.now(tz)
    replacements = {
        "{{ YYYY }}": now.strftime("%Y"),
        "{{ MM }}": now.strftime("%m"),
        "{{ DD }}": now.strftime("%d"),
        "{{ HH }}": now.strftime("%H"),
        "{{ mm }}": now.strftime("%M"),
        "{{ ss }}": now.strftime("%S"),
        "{{ YYYYMMDD }}": now.strftime("%Y%m%d"),
        "{{ HHmmss }}": now.strftime("%H%M%S"),
    }

    for key, value in replacements.items():
        template = template.replace(key, value)
    
    return template

class ChannelProcess:
    """
    频道进程类，管理每个频道的 ytarchive 进程
    """
    def __init__(self, config: ChannelConfig, global_config: GlobalConfig):
        self.config = config
        self.global_config = global_config
        self.process = None
        self.pid = None  # 初始化 PID
        self.thread = None
        self.logger = None
        self.running = False
        self.logs = []
        self.log_lock = threading.Lock()

    def start(self):
        """
        启动 ytarchive 进程
        """
        cmd = self.build_command()
        self.setup_logging()
        try:
            # 启动进程
            self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8')
            self.pid = self.process.pid
            self.running = True
            # 启动线程读取输出
            self.thread = threading.Thread(target=self.read_output, daemon=True)
            self.thread.start()
            main_logger.info(f"已启动频道 {self.config.name} ({self.config.id}) 的监控，PID: {self.pid}")
        except Exception as e:
            main_logger.error(f"启动频道 {self.config.name} ({self.config.id}) 的进程时出错：{e}")

    def stop(self):
        """
        停止 ytarchive 进程
        """
        if self.process and self.running:
            self.process.terminate()
            self.process.wait()
            self.pid = None
            self.running = False
            if self.thread and self.thread.is_alive():
                self.thread.join()
            main_logger.info(f"已停止频道 {self.config.name} ({self.config.id}) 的监控")

    def build_command(self) -> List[str]:
        """
        构建 ytarchive 命令行参数
        """
        ytarchive_path = self.global_config.ytarchive
        cmd = [ytarchive_path]

        # 合并全局和频道的选项
        combined_options = self.global_config.options.copy()
        combined_options.update(self.config.options)

        for option, value in combined_options.items():
            if isinstance(value, bool):
                if value:
                    cmd.append(option)
            else:
                cmd.extend([option, str(value)])

        # 构建输出路径
        output_template = self.config.output or self.global_config.output
        if not output_template:
            output_template = '{{ name }}_{{ id }}'
        
        # 替换 {{ name }} 和 {{ id }}
        output_path = output_template.replace('{{ id }}', self.config.id).replace('{{ name }}', self.config.name)
        # 替换时间变量
        output_path = replace_time_variables(output_path, self.global_config.output_time_tz)
        output_path = os.path.normpath(output_path)
        
        # 如果是相对路径, 输出到运行目录 'output' 文件夹
        if not os.path.isabs(output_path):
            output_path = os.path.join(os.getcwd(), 'output', output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # 使用配置中的 output_file
        # 优先使用频道级别的 output_file，如果没有，则使用全局配置的
        output_file_template = self.config.options.get('output_file') or self.global_config.output_file or "%(upload_date)s_%(title)s"
        # 替换时间变量
        output_file_template = replace_time_variables(output_file_template, self.global_config.output_time_tz)
        output_path = os.path.join(output_path, output_file_template)

        cmd.extend(['-o', output_path])

        # 添加代理设置
        proxy = self.config.proxy or self.global_config.proxy
        if proxy:
            cmd.extend(['--proxy', proxy])

        # 添加频道URL
        channel_url = f'https://www.youtube.com/channel/{self.config.id}/live'
        cmd.append(channel_url)
        cmd.append('best')

        return cmd

    def setup_logging(self):
        """
        设置频道的日志记录
        """
        logs_dir = Path(f'logs/ytarchive/{self.config.name}')
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / f'{self.config.name}.log'
        self.logger = logging.getLogger(f'ytarchive_{self.config.name}')
        self.logger.setLevel(logging.INFO)
        handler = TimedRotatingFileHandler(log_file, when='midnight', backupCount=30, encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        handler.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(handler)

    def read_output(self):
        """
        读取 ytarchive 进程的输出
        """
        while self.running and self.process.poll() is None:
            line = self.process.stdout.readline()
            if line:
                with self.log_lock:
                    self.logger.info(line.strip())
                    self.logs.append(line.strip())
                    if len(self.logs) > 1000:
                        self.logs = self.logs[-500:]
        self.running = False

    def parse_latest_status(self) -> dict:
        """
        解析最近日志, 获取监控或录制的一些信息, 包括录制状态、直播标题、清晰度、开播时间、文件大小等
        """
        status_info = {
            "recording_state": None,   # 可能的值: "监控中"、"录制中"、None
            "video_title": None,
            "quality": None,
            "start_time": None,
            "file_size": None,
        }
        
        # 获取当前日志文件以及若干天前的日志文件
        # logs/ytarchive/{self.config.name}/{self.config.name}.log
        logs_dir = Path(f'logs/ytarchive/{self.config.name}')
        
        # 先检查当前日志文件
        log_files = [logs_dir / f"{self.config.name}.log"]
        # 再往前几天的归档文件，如 {name}.log.2024-12-31 等
        # 这里示例检查最近3天
        for i in range(1, 4):
            day = (datetime.now(timezone.utc) - timedelta(days=i)).astimezone(parse_timezone(self.global_config.output_time_tz)).strftime("%Y-%m-%d")
            archived_file = logs_dir / f"{self.config.name}.log.{day}"
            log_files.append(archived_file)

        # 从最新文件开始往前找，只要匹配到就可以停止
        for log_file in log_files:
            if not log_file.exists():
                continue
            # 读取行，并从结尾往前匹配
            lines = []
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            lines.reverse()  # 从最新一行往前处理

            for line in lines:
                # 1. 判断是否 "录制中" 的匹配：匹配“Video Fragments: ... Total Downloaded: ...”
                match_recording = re.search(r"Video Fragments:\s*\d+;\s*Audio Fragments:\s*\d+;\s*Total Downloaded:\s*(\S+)", line)
                if match_recording:
                    status_info["recording_state"] = "录制中"
                    status_info["file_size"] = match_recording.group(1)  # 例如 "2.80MiB"
                    # 可以继续往前匹配其他信息
                        
                # 2. 判断是否 "监控中" 的匹配：匹配 “Retries: 5 (Last retry: ... ), Total time waited: ...”
                match_monitor = re.search(r"Retries:\s*(\d+).+Total time waited:\s*(\d+)\s*seconds", line)
                if match_monitor:
                    # 如果还没发现"录制中"的行，那么可以认为是"监控中"
                    if status_info["recording_state"] is None:
                        status_info["recording_state"] = "监控中"
                    # 可保存重试次数和总等待时间等信息

                # 3. 匹配“直播标题”
                match_title = re.search(r"Video Title:\s*(.+)$", line)
                if match_title and not status_info["video_title"]:
                    status_info["video_title"] = match_title.group(1).strip()

                # 4. 匹配“录制清晰度”
                match_quality = re.search(r"Selected quality:\s*(.+)$", line)
                if match_quality and not status_info["quality"]:
                    status_info["quality"] = match_quality.group(1).strip()

                # 5. 匹配“开播时间”
                match_start_time = re.search(r"Stream started at time\s*(.+)$", line)
                if match_start_time and not status_info["start_time"]:
                    status_info["start_time"] = match_start_time.group(1).strip()

            # 如果已经拿到需要的全部字段，可以 break
            if any(status_info.values()):
                break

        return status_info

class ChannelManager:
    """
    频道管理器, 管理多个频道的 ytarchive 进程
    """
    def __init__(self, global_config: GlobalConfig):
        self.global_config = global_config
        self.channels: Dict[str, ChannelProcess] = {}
        self.load_channels()

    def load_channels(self):
        """
        加载配置并初始化频道
        """
        for channel_config in self.global_config.users:
            channel_process = ChannelProcess(channel_config, self.global_config)
            self.channels[channel_config.id] = channel_process
            autoRecord = channel_config.autoRecord
            if autoRecord is None:
                autoRecord = self.global_config.autoRecord
            if autoRecord:
                channel_process.start()

    def start_channel(self, channel_id: str):
        """
        启动指定频道的监控
        """
        channel_process = self.channels.get(channel_id)
        if channel_process and not channel_process.running:
            channel_process.start()

    def stop_channel(self, channel_id: str):
        """
        停止指定频道的监控
        """
        channel_process = self.channels.get(channel_id)
        if channel_process and channel_process.running:
            channel_process.stop()

    def add_channel(self, channel_config: ChannelConfig) -> bool:
        """
        添加新频道
        """
        if channel_config.id in self.channels:
            return False
        self.global_config.users.append(channel_config)
        channel_process = ChannelProcess(channel_config, self.global_config)
        self.channels[channel_config.id] = channel_process
        autoRecord = channel_config.autoRecord
        if autoRecord is None:
            autoRecord = self.global_config.autoRecord
        if autoRecord:
            channel_process.start()
        save_config()
        return True

    def remove_channel(self, channel_id: str) -> bool:
        """
        删除指定频道
        """
        channel_process = self.channels.pop(channel_id, None)
        if channel_process:
            channel_process.stop()
            self.global_config.users = [u for u in self.global_config.users if u.id != channel_id]
            save_config()
            return True
        return False

# 加载配置初始化频道管理器
global_config = load_config()
manager = ChannelManager(global_config)

app = FastAPI()

# 定义请求和响应模型
class ChannelModel(BaseModel):
    id: str  # 频道ID，必填
    name: str  # 频道名称，必填
    proxy: Optional[str] = None  # 代理，可选
    output: Optional[str] = None  # 输出路径，可选
    autoRecord: Optional[bool] = None  # 自动录制，可选
    options: Optional[Dict[str, Any]] = None  # 命令行参数，可选

class ChannelStatusModel(BaseModel):
    id: str
    name: str
    running: bool
    pid: Optional[int] = None

class LogResponseModel(BaseModel):
    logs: List[str]

class DetailedStatusModel(BaseModel):
    running: bool
    recording_state: Optional[str] = None  # "监控中" / "录制中" / None
    video_title: Optional[str] = None
    quality: Optional[str] = None
    start_time: Optional[str] = None
    file_size: Optional[str] = None

# 首页
@app.get("/", response_class=HTMLResponse)
async def read_index():
    return FileResponse('index.html')

@app.get("/channels")
async def get_channels():
    channel_status_list = []
    for channel_id, channel_process in manager.channels.items():
        status = ChannelStatusModel(
            id=channel_process.config.id,
            name=channel_process.config.name,
            running=channel_process.running,
            pid=channel_process.pid
        )
        channel_status_list.append(status)
    return channel_status_list

# 启动频道监控
@app.post("/channels/{channel_id}/start")
async def start_channel(channel_id: str):
    manager.start_channel(channel_id)
    return {"status": "started", "channel_id": channel_id}

# 停止频道监控
@app.post("/channels/{channel_id}/stop")
async def stop_channel(channel_id: str):
    manager.stop_channel(channel_id)
    return {"status": "stopped", "channel_id": channel_id}

# 添加新频道
@app.post("/channels")
async def add_channel(channel: ChannelModel):
    """
    添加新频道的接口
    只需要提供频道ID和频道名称，其他字段为可选
    """
    options = channel.options or {}
    channel_config = ChannelConfig(
        id=channel.id,
        name=channel.name,
        proxy=channel.proxy,
        output=channel.output,
        autoRecord=channel.autoRecord,
        options=options
    )

    success = manager.add_channel(channel_config)

    if success:
        return {"status": "added", "channel_id": channel.id}
    else:
        return {"status": "exists", "channel_id": channel.id}

# 删除频道
@app.delete("/channels/{channel_id}")
async def delete_channel(channel_id: str):
    success = manager.remove_channel(channel_id)
    if success:
        return {"status": "deleted", "channel_id": channel_id}
    else:
        return {"status": "not found", "channel_id": channel_id}

# 获取指定频道的日志
@app.get("/channels/{channel_id}/logs")
async def get_channel_logs(channel_id: str):
    channel_process = manager.channels.get(channel_id)
    if channel_process:
        return LogResponseModel(logs=channel_process.logs)
    else:
        return {"logs": []}

# 获取主程序的日志
@app.get("/logs/main")
async def get_main_logs():
    if main_log_file.exists():
        with open(main_log_file, 'r', encoding='utf-8') as f:
            logs = f.readlines()
        return LogResponseModel(logs=logs[-500:])
    else:
        return LogResponseModel(logs=[])

# 新增接口：获取频道的详细状态
@app.get("/channels/{channel_id}/status", response_model=DetailedStatusModel)
async def get_channel_status(channel_id: str):
    channel_process = manager.channels.get(channel_id)
    if not channel_process:
        raise HTTPException(status_code=404, detail="Channel not found")

    if not channel_process.running:
        # 如果进程都没启动，就直接返回 stopped 的信息
        return DetailedStatusModel(
            running=False,
            recording_state=None,
            video_title=None,
            quality=None,
            start_time=None,
            file_size=None
        )

    # 如果正在运行, 去解析日志拿到相关信息
    status_info = channel_process.parse_latest_status()
    return DetailedStatusModel(
        running=True,
        recording_state=status_info.get("recording_state"),
        video_title=status_info.get("video_title"),
        quality=status_info.get("quality"),
        start_time=status_info.get("start_time"),
        file_size=status_info.get("file_size")
    )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=45678)