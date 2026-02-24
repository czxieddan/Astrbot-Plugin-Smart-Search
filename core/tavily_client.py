"""
Tavily API 客户端
封装 Tavily 搜索 API 调用，支持 API Key 轮询
"""
import httpx
from typing import List, Dict, Optional
from astrbot.api import logger


class TavilyKeyPool:
    """
    Tavily API Key 轮询池
    支持多个 Key 轮询使用，自动跳过失败的 Key
    """
    
    def __init__(self, keys: List[Dict]):
        """
        初始化 Key 池
        
        Args:
            keys: Key 配置列表，格式 [{"key": "xxx", "name": "备注"}]
        """
        self.keys = keys if keys else []
        self.current_index = 0
        self.failed_keys = set()  # 记录失败的 key（额度用尽/无效）
    
    def get_next_key(self) -> str:
        """
        获取下一个可用的 Key（轮询）
        
        Returns:
            可用的 API Key
            
        Raises:
            ValueError: 没有配置任何 Key
        """
        if not self.keys:
            raise ValueError("没有配置 Tavily API Key，请在插件配置中添加")
        
        # 尝试获取可用的 key
        attempts = 0
        while attempts < len(self.keys):
            key_info = self.keys[self.current_index]
            key = key_info.get("key", "")
            name = key_info.get("name", f"Key-{self.current_index}")
            
            # 移动到下一个索引
            self.current_index = (self.current_index + 1) % len(self.keys)
            
            # 跳过已失败的 key
            if key and key not in self.failed_keys:
                logger.debug(f"[Tavily] 使用 Key: {name}")
                return key
            
            attempts += 1
        
        # 所有 key 都失败了，重置并重试第一个
        logger.warning("[Tavily] 所有 API Key 都已失败，重置状态并重试")
        self.failed_keys.clear()
        return self.keys[0].get("key", "")
    
    def mark_failed(self, key: str):
        """
        标记某个 Key 失败（额度用尽/无效）
        
        Args:
            key: 失败的 API Key
        """
        self.failed_keys.add(key)
        # 找到对应的名称用于日志
        for key_info in self.keys:
            if key_info.get("key") == key:
                name = key_info.get("name", key[:8] + "...")
                logger.warning(f"[Tavily] API Key 已标记为失败: {name}")
                break
    
    def has_available_keys(self) -> bool:
        """检查是否还有可用的 Key"""
        if not self.keys:
            return False
        available = sum(1 for k in self.keys if k.get("key") not in self.failed_keys)
        return available > 0
    
    def reset(self):
        """
        重置所有 Key 状态（新任务开始时调用）
        让所有之前失败的 Key 重新可用
        """
        if self.failed_keys:
            logger.info(f"[Tavily] 重置 Key 池状态，{len(self.failed_keys)} 个失败 Key 重新可用")
        self.failed_keys.clear()


class TavilyClient:
    """
    Tavily 搜索 API 客户端
    """
    
    TAVILY_API_URL = "https://api.tavily.com/search"
    
    def __init__(self, key_pool: TavilyKeyPool, search_depth: str = "advanced", max_results: int = 5, proxy: Optional[str] = None):
        """
        初始化客户端
        
        Args:
            key_pool: API Key 轮询池
            search_depth: 搜索深度 basic/advanced
            max_results: 每次搜索最大结果数
            proxy: 代理地址（可选）
        """
        self.key_pool = key_pool
        self.search_depth = search_depth
        self.max_results = max_results
        # 处理空字符串代理（铁律 1）
        self.proxy = proxy if proxy else None
    
    async def search(self, query: str, max_results: Optional[int] = None, include_domains: Optional[List[str]] = None, days: Optional[int] = None) -> List[Dict]:
        """
        执行搜索
        
        任何原因失败的 Key 都会被标记，本次任务中不再使用
        失败后会自动切换到下一个可用 Key 继续同一搜索
        
        Args:
            query: 搜索关键词
            max_results: 最大结果数（可选，覆盖默认值）
            include_domains: 限制搜索的域名列表（可选）
            days: 时间过滤，只返回最近 N 天内的结果（可选，Tavily API 原生支持）
            
        Returns:
            搜索结果列表，每个结果包含 title, url, content
        """
        results_count = max_results if max_results else self.max_results
        
        # 循环尝试，直到成功或所有 key 都失败
        while True:
            # 获取下一个可用 key
            try:
                api_key = self.key_pool.get_next_key()
            except ValueError as e:
                logger.error(f"[Tavily] {str(e)}")
                return []
            
            payload = {
                "api_key": api_key,
                "query": query,
                "search_depth": self.search_depth,
                "max_results": results_count,
                "include_answer": False,
                "include_raw_content": False
            }
            
            # 添加域名限制（如果指定）
            if include_domains:
                payload["include_domains"] = include_domains
            
            # 添加时间过滤（Tavily API 原生支持）
            if days and days > 0:
                payload["days"] = days
                logger.info(f"[Tavily] 时间过滤: 只搜索最近 {days} 天的内容")
            
            try:
                # 使用 proxy 参数而非 proxies（铁律 1）
                async with httpx.AsyncClient(proxy=self.proxy, timeout=30.0) as client:
                    response = await client.post(self.TAVILY_API_URL, json=payload)
                    
                    if response.status_code == 200:
                        data = response.json()
                        results = data.get("results", [])
                        logger.info(f"[Tavily] 搜索 '{query[:30]}...' 获取 {len(results)} 条结果")
                        return results
                    
                    # 任何非200状态码都标记失败并尝试切换
                    error_msg = f"状态码 {response.status_code}"
                    if response.status_code == 401:
                        error_msg = "API Key 无效"
                    elif response.status_code == 429:
                        error_msg = "额度用尽"
                    
                    logger.warning(f"[Tavily] 搜索失败 ({error_msg}): {api_key[:8]}...")
                    self.key_pool.mark_failed(api_key)
                    
                    # 如果还有可用 key，继续循环用新 key 重试同一搜索
                    if self.key_pool.has_available_keys():
                        logger.info(f"[Tavily] 切换到下一个 Key 继续搜索...")
                        continue
                    
                    logger.error(f"[Tavily] 所有 Key 都已失败，搜索终止")
                    return []
                        
            except httpx.TimeoutException:
                logger.warning(f"[Tavily] 搜索超时: {query[:30]}... (Key: {api_key[:8]}...)")
                self.key_pool.mark_failed(api_key)
                
                if self.key_pool.has_available_keys():
                    logger.info(f"[Tavily] 切换到下一个 Key 继续搜索...")
                    continue
                
                logger.error(f"[Tavily] 所有 Key 都已失败，搜索终止")
                return []
                
            except Exception as e:
                logger.warning(f"[Tavily] 搜索异常: {str(e)} (Key: {api_key[:8]}...)")
                self.key_pool.mark_failed(api_key)
                
                if self.key_pool.has_available_keys():
                    logger.info(f"[Tavily] 切换到下一个 Key 继续搜索...")
                    continue
                
                logger.error(f"[Tavily] 所有 Key 都已失败，搜索终止")
                return []
