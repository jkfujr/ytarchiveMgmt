# main.py

import re, uvicorn, asyncio, time, os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from typing import Dict, List, Any, Optional
from pydantic import BaseModel
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from core.ytarchive import ChannelConfig, ChannelManager
from core.youtubeCheck import youtubeCheck
from core.logs import get_main_logger, get_channel_logger, get_main_logs, get_channel_logs
from core.proxy import proxy_manager
from core.cookie import cookie_manager

#---------------------------------------------
# 日志
#---------------------------------------------
main_logger = get_main_logger()

proxy_manager.logger = main_logger

#---------------------------------------------
# 模型定义
#---------------------------------------------
class ChannelModel(BaseModel):
    id: str 
    name: str
    proxy: Optional[str] = None
    output: Optional[str] = None
    autoRecord: Optional[bool] = None
    autoCheck: Optional[bool] = None
    options: Optional[Dict[str, Any]] = None

class ChannelStatusModel(BaseModel):
    id: str
    name: str
    running: bool
    pid: Optional[int] = None
    checking: bool = False

class LogResponseModel(BaseModel):
    logs: List[str]

class DetailedStatusModel(BaseModel):
    running: bool
    checking: bool
    recording_state: Optional[str] = None
    video_title: Optional[str] = None
    quality: Optional[str] = None
    start_time: Optional[str] = None
    file_size: Optional[str] = None

class ChannelFullStatusModel(BaseModel):
    id: str
    name: str
    running: bool
    checking: bool
    pid: Optional[int] = None
    is_live: bool = False
    recording_state: Optional[str] = None
    video_title: Optional[str] = None

#---------------------------------------------
# 配置管理功能
#---------------------------------------------
def load_config():
    """加载配置文件"""
    try:
        yaml = YAML()
        yaml.preserve_quotes = True
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config_dict = yaml.load(f)
    except FileNotFoundError:
        main_logger.error("配置文件 config.yaml 未找到")
        raise

    config = {
        "host": config_dict.get("host", "127.0.0.1"),
        "port": config_dict.get("port", 45678),
        "auto_check": config_dict.get("autoCheck", False),
        "check_interval": config_dict.get("checkInterval", 300),
        "auto_record": config_dict.get("autoRecord", False),
    }
    
    proxy_config = config_dict.get("proxy", {})
    config["proxy_config"] = proxy_config
    proxy_manager.set_config(proxy_config)
    config["api_proxy"] = proxy_manager.get_api_proxy()
    
    cookie_config = config_dict.get("cookie", {})
    config["cookie_config"] = cookie_config
    
    cookie_manager.set_config(cookie_config)
    cookie_manager.logger = main_logger
    
    ytarchive_config = config_dict.get('ytarchive', {})
    config["ytarchive_path"] = ytarchive_config.get('ytaPath')
    config["ytarchive_proxy"] = proxy_manager.get_yta_proxy()
    config["ytarchive_output"] = ytarchive_config.get('output')
    config["ytarchive_output_file"] = ytarchive_config.get('output_file')
    config["ytarchive_options"] = ytarchive_config.get('options', {})
    
    config["channels"] = []
    for user in config_dict.get('user', []):
        channel = ChannelConfig(
            id=user.get('id'),
            name=user.get('name'),
            proxy=user.get('proxy'),
            output=user.get('output'),
            autoRecord=user.get('autoRecord'),
            autoCheck=user.get('autoCheck'),
            options=user.get('options', {})
        )
        config["channels"].append(channel)

    return config

def save_config(config):
    """保存配置到 config.yaml，保留注释和格式"""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.allow_unicode = True
    yaml.width = 1000
    yaml.indent(mapping=2, sequence=4, offset=2)

    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config_dict = yaml.load(f)
    except FileNotFoundError:
        main_logger.error("配置文件 config.yaml 未找到")
        return

    config_dict["host"] = config.get("host", "127.0.0.1")
    config_dict["port"] = config.get("port", 45678)
    config_dict["autoCheck"] = config.get("auto_check", False)
    config_dict["checkInterval"] = config.get("check_interval", 300)
    config_dict["autoRecord"] = config.get("auto_record", False)

    if config.get("proxy_config"):
        proxy_config = config["proxy_config"]
        
        if "api" in proxy_config:
            config_dict["proxy"]["api"] = proxy_config["api"]
        if "yta" in proxy_config:
            config_dict["proxy"]["yta"] = proxy_config["yta"]
            
        if "groups" in proxy_config:
            if "proxy" not in config_dict:
                config_dict["proxy"] = {}
            if "groups" not in config_dict["proxy"]:
                config_dict["proxy"]["groups"] = {}
                
            for group_name, proxies in proxy_config["groups"].items():
                config_dict["proxy"]["groups"][group_name] = proxies
    
    if config.get("cookie_config"):
        cookie_config = config["cookie_config"]
        
        if "cookie" not in config_dict:
            config_dict["cookie"] = {}
            
        config_dict["cookie"]["enable"] = cookie_config.get("enable", False)
        if "path" in cookie_config:
            config_dict["cookie"]["path"] = cookie_config["path"]

    if 'ytarchive' not in config_dict:
        config_dict['ytarchive'] = {}
    ytarchive_config = config_dict['ytarchive']
    if config.get("ytarchive_path"):
        ytarchive_config['ytaPath'] = DoubleQuotedScalarString(config["ytarchive_path"])
    if config.get("ytarchive_proxy"):
        ytarchive_config['ytaProxy'] = config["ytarchive_proxy"]
    if config.get("ytarchive_output"):
        ytarchive_config['output'] = config["ytarchive_output"]
    if config.get("ytarchive_output_file"):
        ytarchive_config['output_file'] = config["ytarchive_output_file"]
    else:
        ytarchive_config.pop('output_file', None)
    ytarchive_config['options'] = config.get("ytarchive_options", {})
    
    user_list = []
    for channel in config.get("channels", []):
        user_dict = {
            'id': DoubleQuotedScalarString(channel.id),
            'name': DoubleQuotedScalarString(channel.name),
        }
        
        if channel.proxy is not None:
            user_dict['proxy'] = channel.proxy
            
        if channel.output is not None:
            user_dict['output'] = channel.output
            
        if channel.autoRecord is not None:
            user_dict['autoRecord'] = channel.autoRecord
            
        if channel.autoCheck is not None:
            user_dict['autoCheck'] = channel.autoCheck
            
        if channel.options:
            user_dict['options'] = channel.options
            
        user_list.append(user_dict)
        
    config_dict['user'] = user_list

    with open('config.yaml', 'w', encoding='utf-8') as f:
        yaml.dump(config_dict, f)

    main_logger.info("配置已保存")

#---------------------------------------------
# 直播状态检查和自动录制功能
#---------------------------------------------
class LiveStatusChecker:
    """直播状态检查器，负责定期检查频道直播状态"""
    
    def __init__(self, config, manager, logger=None):
        """初始化状态检查器
        
        Args:
            config: 全局配置
            manager: 频道管理器
            logger: 日志记录器
        """
        self.config = config
        self.manager = manager
        self.logger = logger
        self.checking_channels = set()
        self.check_tasks = {}
        self.check_interval = config.get("check_interval", 300)
        self.error_check_interval = 60
        self.error_check_tasks = {}
        
        if self.logger:
            self.logger.info(f"创建直播状态检查器，检查间隔为 {self.check_interval}秒")
            self.logger.info(f"ytarchive错误检查间隔为 {self.error_check_interval}秒")
    
    async def check_channel_live_status(self, channel_id: str) -> bool:
        """检查单个频道的直播状态，如果正在直播返回True"""
        try:
            channel = next((c for c in self.config["channels"] if c.id == channel_id), None)
            if not channel:
                if self.logger:
                    self.logger.error(f"找不到频道 {channel_id}")
                return False

            channel_logger = get_channel_logger(channel.name)
            channel_logger.info(f"开始检查直播状态")
            channel_status = self.manager.get_channel_status(channel_id)
            if channel_status and channel_status.get("running"):
                is_recording = channel_status.get("recording_state") == "录制中"
                if is_recording:
                    if self.logger:
                        self.logger.info(f"频道 {channel.name} ({channel_id}) 已经在录制中")
                    channel_logger.info("频道已经在录制中，跳过检查")
                    return False

            if self.logger:
                self.logger.info(f"正在检查频道 {channel.name} ({channel_id}) 的直播状态")
                
            api_proxy = proxy_manager.get_api_proxy()
            result = await youtubeCheck(channel_id, api_proxy, channel_logger)
            
            if result:
                title = result[0].get('title', 'Unknown Title')
                if self.logger:
                    self.logger.info(f"检测到频道 {channel.name} ({channel_id}) 正在直播: {title}")
                channel_logger.info(f"检测到频道正在直播: {title}")
                return True
            else:
                if self.logger:
                    self.logger.info(f"频道 {channel.name} ({channel_id}) 当前没有直播")
                channel_logger.info("当前没有直播")
                
                if channel_status and channel_status.get("running"):
                    try:
                        ytarchive_logs = get_channel_logs(channel.name, log_type="ytarchive", max_lines=10)
                        
                        if ytarchive_logs and len(ytarchive_logs) > 0:
                            latest_log = ytarchive_logs[-1].strip()

                            retry_match = re.search(r"Retries:\s*(\d+)\s*\(Last retry:.*?\),\s*Total time waited:\s*(\d+)\s*seconds", latest_log)
                            
                            if retry_match:
                                retries = retry_match.group(1)
                                total_waited = retry_match.group(2)
                                retry_info = f"Retries: {retries}, Total time waited: {total_waited} seconds"
                                
                                if self.logger:
                                    self.logger.warning(f"频道 {channel.name} ({channel_id}) 检测到ytarchive重试信息「{retry_info}」，自动停止录制")
                                channel_logger.warning(f"检测到ytarchive重试信息「{retry_info}」，自动停止录制")
                                
                                self.manager.stop_channel(channel_id)
                                channel_logger.info("已自动停止录制进程")
                    except Exception as e:
                        error_msg = f"处理ytarchive日志时出错: {e}"
                        if self.logger:
                            self.logger.error(error_msg)
                        channel_logger.error(error_msg)
                
                return False
                
        except Exception as e:
            error_msg = f"检查频道 {channel_id} 直播状态时出错: {e}"
            if self.logger:
                self.logger.error(error_msg)
            
            if channel:
                channel_logger = get_channel_logger(channel.name)
                channel_logger.error(f"检查直播状态时出错: {e}")
                
            return False

    async def run_channel_check(self, channel_id: str):
        """运行单个频道的定期检查"""
        channel = next((c for c in self.config["channels"] if c.id == channel_id), None)
        if not channel:
            if self.logger:
                self.logger.error(f"找不到频道 {channel_id}")
            return

        channel_logger = get_channel_logger(channel.name)

        try:
            self.checking_channels.add(channel_id)
            if self.logger:
                self.logger.info(f"开始定期检查频道 {channel.name} ({channel_id}) 的直播状态")
            channel_logger.info("开始定期检查直播状态")
            
            while channel_id in self.checking_channels:
                is_live = await self.check_channel_live_status(channel_id)
                
                if is_live:
                    should_record = channel.autoRecord if channel.autoRecord is not None else self.config.get('auto_record', False)
                    if should_record:
                        success = self.manager.start_channel(channel_id)
                        if success:
                            if self.logger:
                                self.logger.info(f"已自动启动频道 {channel.name} ({channel_id}) 的录制")
                            channel_logger.info("已自动启动录制")
                        else:
                            channel_logger.warning("尝试自动启动录制失败")
                
                if self.logger:
                    self.logger.info(f"频道 {channel.name} 将在 {self.check_interval} 秒后再次检查")
                channel_logger.info(f"将在 {self.check_interval} 秒后再次检查")
                await asyncio.sleep(self.check_interval)
        
        except asyncio.CancelledError:
            if self.logger:
                self.logger.info(f"停止频道 {channel.name} ({channel_id}) 的定期检查")
            channel_logger.info("停止定期检查")
            self.checking_channels.discard(channel_id)
        except Exception as e:
            error_msg = f"频道 {channel_id} 的定期检查任务出错: {e}"
            if self.logger:
                self.logger.error(error_msg)
            channel_logger.error(f"定期检查任务出错: {e}")
            self.checking_channels.discard(channel_id)

    def start_channel_check(self, channel_id: str) -> bool:
        """开始检查特定频道的直播状态"""
        if channel_id in self.checking_channels:
            return False
            
        channel = next((c for c in self.config["channels"] if c.id == channel_id), None)
        if not channel:
            if self.logger:
                self.logger.error(f"找不到频道 {channel_id}")
            return False
            
        channel_logger = get_channel_logger(channel.name)
        
        task = asyncio.create_task(self.run_channel_check(channel_id))
        self.check_tasks[channel_id] = task
        
        if self.logger:
            self.logger.info(f"已启动频道 {channel.name} ({channel_id}) 的直播状态检查")
        channel_logger.info("已启动直播状态检查")
        return True

    def stop_channel_check(self, channel_id: str) -> bool:
        """停止检查特定频道的直播状态"""
        if channel_id not in self.checking_channels:
            return False

        channel = next((c for c in self.config["channels"] if c.id == channel_id), None)
        
        if channel:
            channel_logger = get_channel_logger(channel.name)
            
        if channel_id in self.check_tasks:
            task = self.check_tasks.pop(channel_id)
            task.cancel()
            
        self.checking_channels.discard(channel_id)
        
        if channel:
            if self.logger:
                self.logger.info(f"已停止频道 {channel.name} ({channel_id}) 的直播状态检查")
            channel_logger.info("已停止直播状态检查")
        return True

    def is_checking(self, channel_id: str) -> bool:
        """检查是否正在监控指定频道的状态"""
        return channel_id in self.checking_channels

    def get_checking_channels(self) -> List[str]:
        """获取所有正在检查状态的频道ID列表"""
        return list(self.checking_channels)

    async def check_ytarchive_errors(self):
        """定期检查所有频道的ytarchive错误"""
        while True:
            try:
                errors = self.manager.check_all_channels_errors()
                
                for error in errors:
                    channel_id = error["channel_id"]
                    channel_name = error["channel_name"]
                    error_message = error["error_message"]
                    current_proxy = error["current_proxy"]
                    
                    if self.logger:
                        self.logger.warning(f"频道 {channel_name} ({channel_id}) 检测到ytarchive错误: {error_message}")
                        if current_proxy:
                            self.logger.warning(f"当前使用的代理: {current_proxy}")
                    
                    channel_logger = get_channel_logger(channel_name)
                    channel_logger.warning(f"检测到ytarchive错误: {error_message}")
                    if current_proxy:
                        channel_logger.warning(f"当前使用的代理: {current_proxy}")
                    
                    success = self.manager.restart_channel_with_new_proxy(channel_id)
                    if success:
                        if self.logger:
                            self.logger.info(f"频道 {channel_name} ({channel_id}) 已使用新代理重启")
                        channel_logger.info("已使用新代理重启录制")
                    else:
                        if self.logger:
                            self.logger.error(f"频道 {channel_name} ({channel_id}) 重启失败")
                        channel_logger.error("重启失败")
                
                await asyncio.sleep(self.error_check_interval)
                
            except Exception as e:
                if self.logger:
                    self.logger.error(f"检查ytarchive错误时出错: {e}")
                await asyncio.sleep(self.error_check_interval)

    def start_error_check(self):
        """启动ytarchive错误检查"""
        if not self.error_check_tasks:
            task = asyncio.create_task(self.check_ytarchive_errors())
            self.error_check_tasks["main"] = task
            if self.logger:
                self.logger.info("已启动ytarchive错误检查")

    def stop_error_check(self):
        """停止ytarchive错误检查"""
        if "main" in self.error_check_tasks:
            task = self.error_check_tasks.pop("main")
            task.cancel()
            if self.logger:
                self.logger.info("已停止ytarchive错误检查")

#---------------------------------------------
# 应用初始化和全局变量
#---------------------------------------------
# 加载配置并初始化频道管理器
config = load_config()
manager = ChannelManager(logger=main_logger)
manager.initialize_channels(
    channels=config["channels"],
    ytarchive_path=config["ytarchive_path"],
    global_output=config["ytarchive_output"],
    global_output_file=config["ytarchive_output_file"],
    global_options=config["ytarchive_options"],
    auto_record=config["auto_record"]
)

status_checker = LiveStatusChecker(config, manager, main_logger)
app = FastAPI()

#---------------------------------------------
# FastAPI事件处理
#---------------------------------------------
@app.on_event("startup")
async def startup_event():
    """FastAPI启动时的处理"""
    main_logger.info("服务已启动")
    global_auto_check = config.get("auto_check", False)
    if global_auto_check:
        main_logger.info("根据全局配置自动启动频道状态检查")
        for channel in config["channels"]:
            should_check = channel.autoCheck if channel.autoCheck is not None else global_auto_check
            if should_check:
                status_checker.start_channel_check(channel.id)
                main_logger.info(f"已启动频道 {channel.name} ({channel.id}) 的状态检查")
            else:
                main_logger.info(f"频道 {channel.name} ({channel.id}) 配置了不自动检查，跳过")
    
    # 启动ytarchive错误检查
    status_checker.start_error_check()
    
    # 启动cookie定时更新任务
    if cookie_manager.enabled:
        cookie_manager.start_update_scheduler()

@app.on_event("shutdown")
async def shutdown_event():
    """FastAPI关闭时的处理"""
    checking_channels = status_checker.get_checking_channels()
    for channel_id in checking_channels:
        status_checker.stop_channel_check(channel_id)
    
    # 停止ytarchive错误检查
    status_checker.stop_error_check()
    
    # 停止cookie定时更新任务
    cookie_manager.stop_update_scheduler()
    
    main_logger.info("服务关闭，已停止所有任务")

#---------------------------------------------
# 基础信息API端点
#---------------------------------------------
# 首页
@app.get("/", response_class=HTMLResponse)
async def read_index():
    """返回首页HTML"""
    return FileResponse('index.html')

#---------------------------------------------
# 频道管理API端点
#---------------------------------------------

@app.get("/channels")
async def get_channels():
    """获取所有频道的完整信息"""
    channels_data = []
    
    all_status = manager.get_all_channels_status()
    
    for status in all_status:
        channel_id = status["id"]
        status["checking"] = status_checker.is_checking(channel_id)
        detailed_status = manager.get_channel_status(channel_id)
        if detailed_status:
            status["quality"] = detailed_status.get("quality")
            status["start_time"] = detailed_status.get("start_time")
            status["file_size"] = detailed_status.get("file_size")
            
        channels_data.append(status)
        
    return channels_data

@app.get("/channels/{channel_id}")
async def get_channel(channel_id: str):
    """获取指定频道的完整信息"""
    channel_process = manager.channels.get(channel_id)
    if not channel_process:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    status = manager.get_channel_status(channel_id)
    if not status:
        raise HTTPException(status_code=404, detail="Channel status not found")
    
    result = {
        "id": channel_id,
        "name": channel_process.config.name,
        "running": status["running"],
        "checking": status_checker.is_checking(channel_id),
        "pid": channel_process.pid,
        "is_live": status.get("recording_state") == "录制中",
        "recording_state": status.get("recording_state"),
        "video_title": status.get("video_title"),
        "quality": status.get("quality"),
        "start_time": status.get("start_time"),
        "file_size": status.get("file_size"),
        "config": {
            "proxy": channel_process.config.proxy,
            "output": channel_process.config.output,
            "autoRecord": channel_process.config.autoRecord,
            "options": channel_process.config.options
        }
    }
    
    return result

@app.post("/channels")
async def add_channel(channel: ChannelModel):
    """添加新频道"""
    channel_config = ChannelConfig(
        id=channel.id,
        name=channel.name,
        proxy=channel.proxy,
        output=channel.output,
        autoRecord=channel.autoRecord,
        autoCheck=channel.autoCheck,
        options=channel.options or {}
    )

    success = manager.add_channel(
        channel_config=channel_config,
        ytarchive_path=config["ytarchive_path"],
        global_output=config["ytarchive_output"],
        global_output_file=config["ytarchive_output_file"],
        global_options=config["ytarchive_options"],
        auto_record=config["auto_record"]
    )

    if success:
        config["channels"].append(channel_config)
        save_config(config)
        return {"status": "added", "channel_id": channel.id}
    else:
        return {"status": "exists", "channel_id": channel.id}

@app.delete("/channels/{channel_id}")
async def delete_channel(channel_id: str):
    """删除频道"""
    status_checker.stop_channel_check(channel_id)
    manager.stop_channel(channel_id)
    
    success = manager.remove_channel(channel_id)
    if success:
        config["channels"] = [c for c in config["channels"] if c.id != channel_id]
        save_config(config)
        return {"status": "deleted", "channel_id": channel_id}
    else:
        return {"status": "not found", "channel_id": channel_id}

@app.post("/channels/{channel_id}/start")
async def start_channel_check(channel_id: str):
    """启动频道状态检查"""
    success = status_checker.start_channel_check(channel_id)
    if success:
        return {"status": "started", "channel_id": channel_id, "message": "频道状态检查已启动"}
    else:
        return {"status": "failed", "channel_id": channel_id, "message": "频道状态检查启动失败，可能已在运行"}

@app.post("/channels/{channel_id}/stop")
async def stop_channel_check(channel_id: str):
    """停止频道状态检查"""
    success = status_checker.stop_channel_check(channel_id)
    if success:
        return {"status": "stopped", "channel_id": channel_id, "message": "频道状态检查已停止"}
    else:
        return {"status": "failed", "channel_id": channel_id, "message": "频道状态检查停止失败，可能未在运行"}

@app.post("/channels/{channel_id}/startrecord")
async def start_channel_record(channel_id: str):
    """启动频道录制"""
    success = manager.start_channel(channel_id)
    if success:
        return {"status": "started", "channel_id": channel_id, "message": "频道录制已启动"}
    else:
        return {"status": "failed", "channel_id": channel_id, "message": "频道录制启动失败，可能已在录制"}

@app.post("/channels/{channel_id}/stoprecord")
async def stop_channel_record(channel_id: str):
    """停止频道录制"""
    success = manager.stop_channel(channel_id)
    if success:
        return {"status": "stopped", "channel_id": channel_id, "message": "频道录制已停止"}
    else:
        return {"status": "failed", "channel_id": channel_id, "message": "频道录制停止失败，可能未在录制"}

#---------------------------------------------
# 日志获取API端点
#---------------------------------------------
@app.get("/channels/{channel_id}/logs")
async def get_channel_logs_api(channel_id: str, log_type: str = "ytarchive"):
    """获取指定频道的日志
    
    Args:
        channel_id: 频道ID
        log_type: 日志类型，可选值：ytarchive, main
    """
    channel = next((c for c in config["channels"] if c.id == channel_id), None)
    if not channel:
        return LogResponseModel(logs=["频道不存在"])

    logs = get_channel_logs(channel.name, log_type)
    return LogResponseModel(logs=logs)

@app.get("/logs")
async def get_main_logs_api():
    """获取主程序的日志"""
    logs = get_main_logs()
    return LogResponseModel(logs=logs)

#---------------------------------------------
# 配置和代理API端点
#---------------------------------------------
@app.get("/config/proxy/disabled")
async def get_disabled_proxies():
    """获取被禁用的代理列表"""
    disabled_proxies = proxy_manager.get_disabled_proxies()
    formatted_proxies = []
    
    for proxy_url, timestamp in disabled_proxies.items():
        disabled_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        expiry_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp + proxy_manager.disable_duration))
        remaining_seconds = max(0, int(timestamp + proxy_manager.disable_duration - time.time()))
        remaining_time = f"{remaining_seconds // 60}分{remaining_seconds % 60}秒"
        
        formatted_proxies.append({
            "proxy_url": proxy_url,
            "disabled_at": disabled_time,
            "expires_at": expiry_time,
            "remaining_time": remaining_time
        })
    
    return {"disabled_proxies": formatted_proxies}

@app.post("/config/proxy/clear_disabled")
async def clear_disabled_proxies():
    """清除所有被禁用的代理"""
    disabled_count = len(proxy_manager.get_disabled_proxies())
    proxy_manager.clear_disabled_proxies()
    return {"status": "success", "message": f"已清除 {disabled_count} 个被禁用的代理"}

@app.post("/config/proxy/test")
async def test_proxy_connection(proxy_url: str):
    """测试指定代理的连接状态，使用YouTube API测试其实际可用性"""
    main_logger.info(f"开始测试代理 {proxy_url} (使用YouTube API)")
    
    result = await proxy_manager.test_proxy_with_youtube(proxy_url)
    
    if result["status"] == "success":
        main_logger.info(f"代理 {proxy_url} 测试成功 - {result['message']}")
        if proxy_url in proxy_manager.disabled_proxies:
            proxy_manager.disabled_proxies.pop(proxy_url)
            main_logger.info(f"代理 {proxy_url} 已从禁用列表中移除")
    else:
        proxy_manager.mark_proxy_failed(proxy_url, f"手动测试失败: {result.get('message')}")
        main_logger.warning(f"代理 {proxy_url} 测试失败，已标记为禁用")
    
    return result

@app.post("/config/proxy/enable/{proxy_url:path}")
async def enable_proxy(proxy_url: str):
    """手动启用特定代理"""
    if proxy_url in proxy_manager.disabled_proxies:
        proxy_manager.disabled_proxies.pop(proxy_url)
        main_logger.info(f"手动启用代理 {proxy_url}")
        return {"status": "success", "message": f"代理 {proxy_url} 已启用"}
    else:
        return {"status": "info", "message": f"代理 {proxy_url} 已经是启用状态"}

@app.post("/config/proxy/disable/{proxy_url:path}")
async def disable_proxy(proxy_url: str):
    """手动禁用特定代理"""
    if proxy_url not in proxy_manager.disabled_proxies:
        proxy_manager.mark_proxy_failed(proxy_url, "手动禁用")
        main_logger.info(f"手动禁用代理 {proxy_url}")
        return {"status": "success", "message": f"代理 {proxy_url} 已禁用"}
    else:
        return {"status": "info", "message": f"代理 {proxy_url} 已经是禁用状态"}

@app.get("/config/cookie/status")
async def get_cookie_status():
    """获取Cookie管理器的状态和cookie文件列表"""
    cookie_files = []
    for file_path in cookie_manager.cookie_files:
        try:
            file_size = os.path.getsize(file_path)
            mtime = os.path.getmtime(file_path)
            mod_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
            cookie_files.append({
                "path": file_path,
                "filename": os.path.basename(file_path),
                "size": f"{file_size / 1024:.2f} KB",
                "modified": mod_time
            })
        except Exception as e:
            main_logger.error(f"获取cookie文件信息时出错: {e}")
            cookie_files.append({
                "path": file_path,
                "filename": os.path.basename(file_path),
                "error": str(e)
            })
    
    return {
        "enabled": cookie_manager.enabled,
        "cookies_path": cookie_manager.cookies_path or os.path.join(os.getcwd(), 'cookies'),
        "cookie_count": len(cookie_manager.cookie_files),
        "cookie_files": cookie_files
    }

@app.post("/config/cookie/reload")
async def reload_cookie_files():
    """重新加载cookie文件"""
    old_count = len(cookie_manager.cookie_files)
    cookie_manager.reload_cookie_files()
    new_count = len(cookie_manager.cookie_files)
    
    main_logger.info(f"已重新加载cookie文件：原有 {old_count} 个，现有 {new_count} 个")
    
    return {
        "status": "success",
        "message": f"已重新加载cookie文件",
        "old_count": old_count,
        "new_count": new_count
    }

@app.post("/config/cookie/toggle")
async def toggle_cookie_manager(enable: bool):
    """启用或禁用Cookie管理器"""
    old_status = cookie_manager.enabled
    
    config["cookie_config"]["enable"] = enable
    cookie_manager.set_config(config["cookie_config"])
    save_config(config)
    
    main_logger.info(f"Cookie管理器状态已从 {old_status} 变更为 {enable}")
    
    return {
        "status": "success",
        "message": f"Cookie管理器已{('启用' if enable else '禁用')}",
        "enabled": enable
    }

@app.post("/config/cookie/path")
async def set_cookie_path(path: str):
    """设置cookie文件夹路径"""
    old_path = cookie_manager.cookies_path
    
    config["cookie_config"]["path"] = path
    cookie_manager.set_config(config["cookie_config"])
    save_config(config)
    
    main_logger.info(f"Cookie文件夹路径已从 {old_path or '默认路径'} 变更为 {path or '默认路径'}")
    
    return {
        "status": "success",
        "message": f"Cookie文件夹路径已设置为 {path or '默认路径'}",
        "path": path
    }

@app.get("/config/cookie/update_status")
async def get_cookie_update_status():
    """获取cookie更新状态"""
    status = cookie_manager.get_update_status()
    return status

@app.post("/config/cookie/refresh")
async def refresh_cookies():
    """手动触发cookie刷新"""
    result = await cookie_manager.manually_refresh_cookies()
    return result

@app.post("/config/cookie/scheduler/start")
async def start_cookie_update_scheduler():
    """启动cookie定时更新任务"""
    if cookie_manager.is_update_scheduler_running():
        return {
            "status": "info",
            "message": "Cookie定时更新任务已经在运行中"
        }
    
    cookie_manager.start_update_scheduler()
    return {
        "status": "success",
        "message": "已启动Cookie定时更新任务"
    }

@app.post("/config/cookie/scheduler/stop")
async def stop_cookie_update_scheduler():
    """停止cookie定时更新任务"""
    if not cookie_manager.is_update_scheduler_running():
        return {
            "status": "info",
            "message": "Cookie定时更新任务未在运行"
        }
    
    cookie_manager.stop_update_scheduler()
    return {
        "status": "success",
        "message": "已停止Cookie定时更新任务"
    }

#---------------------------------------------
# 主程序入口
#---------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host=config["host"], port=config["port"])
