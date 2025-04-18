import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Dict

# 全局处理器映射
handlers_cache: Dict[str, logging.Handler] = {}
loggers_cache: Dict[str, logging.Logger] = {}

def setup_logger(logger_name: str, log_file: Path, level=logging.INFO, 
                 when='midnight', backupCount=30, formatter=None) -> logging.Logger:
    """
    创建并配置日志记录器
    
    Args:
        logger_name: 日志记录器名称
        log_file: 日志文件路径
        level: 日志级别
        when: 日志轮换时间，默认为午夜
        backupCount: 保留的历史日志文件数量
        formatter: 日志格式化器，如果为None则使用默认格式
        
    Returns:
        logging.Logger: 配置好的日志记录器
    """
    if logger_name in loggers_cache:
        return loggers_cache[logger_name]

    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    
    if not logger.handlers:
        handler_key = str(log_file.absolute())
        if handler_key in handlers_cache:
            handler = handlers_cache[handler_key]
        else:
            handler = TimedRotatingFileHandler(
                log_file, 
                when=when, 
                backupCount=backupCount,
                encoding='utf-8'
            )
            
            if formatter is None:
                formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
            
            handler.setFormatter(formatter)
            handlers_cache[handler_key] = handler
        
        logger.addHandler(handler)
    
    loggers_cache[logger_name] = logger
    return logger

def get_main_logger() -> logging.Logger:
    """
    获取全局主日志记录器
    
    Returns:
        logging.Logger: 主日志记录器
    """
    logs_dir = Path('logs/main')
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / 'main.log'
    return setup_logger('main', log_file)

def get_channel_logger(channel_name: str) -> logging.Logger:
    """
    获取频道主日志记录器
    
    Args:
        channel_name: 频道名称
        
    Returns:
        logging.Logger: 频道主日志记录器
    """
    logs_dir = Path(f'logs/{channel_name}')
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / 'main.log'
    return setup_logger(f'channel_{channel_name}', log_file)

def get_ytarchive_logger(channel_name: str) -> logging.Logger:
    """
    获取频道的ytarchive进程日志记录器
    
    Args:
        channel_name: 频道名称
        
    Returns:
        logging.Logger: ytarchive进程日志记录器
    """
    logs_dir = Path(f'logs/{channel_name}/ytarchive')
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / 'ytarchive.log'
    return setup_logger(f'ytarchive_{channel_name}', log_file)

def get_channel_logs(channel_name: str, log_type: str = 'main', max_lines: int = 500) -> list:
    """
    读取频道的日志内容
    
    Args:
        channel_name: 频道名称
        log_type: 日志类型，'main'或'ytarchive'
        max_lines: 返回的最大行数
        
    Returns:
        list: 日志行列表
    """
    if log_type == 'main':
        log_file = Path(f'logs/{channel_name}/main.log')
    else:
        log_file = Path(f'logs/{channel_name}/ytarchive/ytarchive.log')
    
    if not log_file.exists():
        return []
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return lines[-max_lines:] if len(lines) > max_lines else lines
    except Exception as e:
        return [f"读取日志文件出错: {str(e)}"]

def get_main_logs(max_lines: int = 500) -> list:
    """
    读取主程序日志内容
    
    Args:
        max_lines: 返回的最大行数
        
    Returns:
        list: 日志行列表
    """
    log_file = Path('logs/main/main.log')
    
    if not log_file.exists():
        return []
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return lines[-max_lines:] if len(lines) > max_lines else lines
    except Exception as e:
        return [f"读取日志文件出错: {str(e)}"] 