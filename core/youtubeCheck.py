import httpx, logging
from typing import List, Dict, Optional, Any
from core.proxy import proxy_manager

async def youtubeCheck(channel_id: str, api_proxy: Optional[str] = None, logger: Optional[logging.Logger] = None, retry_count: int = 2) -> Optional[List[Dict[str, Any]]]:
    """检测YouTube频道直播状态
    
    Args:
        channel_id: YouTube频道ID
        api_proxy: API请求代理地址，为空则不使用代理
        logger: 日志记录器，为空则不记录日志
        retry_count: 代理失败时的重试次数，默认为2
        
    Returns:
        List[Dict]: 直播信息列表，每个字典包含标题、视频ID等信息，无直播时返回空列表，请求失败时返回None
    """
    
    if logger:
        logger.info(f"开始检查频道 {channel_id} 的直播状态")
    
    # 记录初始代理
    original_proxy = api_proxy
    
    # 尝试请求（包括重试逻辑）
    for attempt in range(retry_count + 1):
        if attempt > 0 and logger:
            logger.warning(f"第 {attempt} 次重试检查频道 {channel_id} 的直播状态")
        
        result = await _do_youtube_check(channel_id, api_proxy, logger)
        
        # 请求成功，返回结果
        if result is not None:
            return result
            
        # 请求失败，检查是否是代理问题
        if api_proxy:
            # 标记代理失败
            proxy_manager.mark_proxy_failed(api_proxy, f"检查频道 {channel_id} 直播状态失败")
            
            if logger:
                logger.warning(f"代理 {api_proxy} 请求失败，已标记为禁用")
            
            # 获取新的代理
            api_proxy = proxy_manager.get_api_proxy()
            
            if api_proxy:
                if logger:
                    logger.info(f"切换到新代理 {api_proxy} 重试请求")
            else:
                if logger:
                    logger.warning("无可用代理，将不使用代理重试请求")
        
        # 如果是最后一次尝试，且依然失败，记录错误
        if attempt == retry_count and logger:
            if original_proxy:
                logger.error(f"使用代理多次重试后仍然失败，无法检查频道 {channel_id} 的直播状态")
            else:
                logger.error(f"多次重试后仍然失败，无法检查频道 {channel_id} 的直播状态")
    
    # 所有尝试都失败，返回None
    return None

async def _do_youtube_check(channel_id: str, api_proxy: Optional[str] = None, logger: Optional[logging.Logger] = None) -> Optional[List[Dict[str, Any]]]:
    """执行实际的YouTube检查请求
    
    Args:
        channel_id: YouTube频道ID
        api_proxy: API请求代理地址
        logger: 日志记录器
        
    Returns:
        检查结果，失败返回None
    """
    url = 'https://www.youtube.com/youtubei/v1/browse'
    
    params = {
        'key': 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8',
        'prettyPrint': False
    }
    
    data = {
        'context': {
            'client': {
                'hl': 'zh-CN',
                'clientName': 'MWEB',
                'clientVersion': '2.20230101.00.00',
                'timeZone': 'Asia/Shanghai'
            }
        },
        'browseId': channel_id,
        'params': 'EgdzdHJlYW1z8gYECgJ6AA%3D%3D'
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    client_kwargs = {
        'headers': headers,
        'timeout': 30.0
    }
    
    if api_proxy:
        client_kwargs['proxy'] = api_proxy
        if logger:
            logger.info(f"使用代理 {api_proxy}")

    async with httpx.AsyncClient(**client_kwargs) as client:
        try:
            response = await client.post(url, params=params, json=data)
            response.raise_for_status()
            result = response.json()
            live_streams = []
            
            tabs = result.get("contents", {}).get("singleColumnBrowseResultsRenderer", {}).get("tabs", [])
            
            for tab in tabs:
                tab_renderer = tab.get("tabRenderer", {})
                if tab_renderer.get("title") == "直播":
                    content = tab_renderer.get("content", {}).get("richGridRenderer", {}).get("contents", [])
                    
                    for item in content:
                        video = item.get("richItemRenderer", {}).get("content", {}).get("videoWithContextRenderer", {})
                        overlays = video.get("thumbnailOverlays", [])
                        is_live = any(
                            overlay.get("thumbnailOverlayTimeStatusRenderer", {}).get("style") == "LIVE"
                            for overlay in overlays
                        )
                        
                        if is_live:
                            live_info = {
                                "title": video.get("headline", {}).get("runs", [{}])[0].get("text"),
                                "video_id": video.get("videoId"),
                                "viewers": video.get("shortViewCountText", {}).get("runs", [{}])[0].get("text"),
                                "thumbnail": video.get("thumbnail", {}).get("thumbnails", [{}])[-1].get("url")
                            }
                            live_streams.append(live_info)
                            
                            if logger:
                                logger.info(f"检测到直播：{live_info['title']} ({live_info['video_id']})")
            
            if not live_streams and logger:
                logger.info(f"频道 {channel_id} 当前没有直播")
                
            return live_streams
            
        except Exception as e:
            if logger:
                error_info = f"检查频道 {channel_id} 直播状态时出错: {e}"
                if api_proxy:
                    error_info += f" (使用代理: {api_proxy})"
                logger.error(error_info)
            return None 