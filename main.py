"""
智能联网搜索插件
基于 Tavily API，为 LLM 提供搜索结果作为参考资料
"""
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig

from .core.tavily_client import TavilyKeyPool, TavilyClient
from .core.search_framework import SearchFramework


@register(
    "smart_search",
    "Yezi",
    "智能联网搜索插件 - 为 LLM 提供最新准确的网络信息",
    "1.3.0",
    "https://github.com/astrbot/"
)
class SmartSearchPlugin(Star):
    """
    智能联网搜索插件
    
    功能：
    1. 注册 LLM 函数工具，让 AI 可以主动调用联网搜索
    2. 支持 Tavily API Key 轮询
    3. 支持时间过滤（Tavily API 原生）
    """
    
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._init_client()
        logger.info("[智能搜索] 插件已加载")
    
    def _init_client(self):
        """初始化 Tavily 客户端"""
        # 读取配置
        try:
            api_keys = []
            for i in range(1, 4):
                key = self.config.get(f"tavily_api_key_{i}", "")
                if key:
                    api_keys.append({"key": key, "name": f"Key-{i}"})
            
            self.max_days_old = self.config.get("max_days_old", 0)
            self.show_sources = self.config.get("show_sources", False)
        except Exception as e:
            logger.warning(f"[智能搜索] 配置读取失败: {e}")
            api_keys = []
            self.max_days_old = 0
            self.show_sources = False
        
        # 初始化客户端
        self.key_pool = TavilyKeyPool(api_keys)
        self.tavily_client = TavilyClient(
            key_pool=self.key_pool,
            search_depth="advanced",
            max_results=5
        )
        
        if not api_keys:
            logger.warning("[智能搜索] 未配置 Tavily API Key")
        elif self.max_days_old > 0:
            logger.info(f"[智能搜索] 时间过滤: {self.max_days_old} 天内")
    
    async def _do_search(self, query: str) -> str:
        """执行搜索的核心逻辑"""
        if not self.key_pool.keys:
            return "搜索功能未配置 Tavily API Key，请在插件配置中添加。"
        
        framework = SearchFramework(
            tavily_client=self.tavily_client,
            max_days_old=self.max_days_old,
            show_sources=self.show_sources
        )
        
        report = await framework.search(query)
        return report.summary if report.summary else "搜索未找到相关结果。"
    
    @filter.llm_tool(name="web_search")
    async def web_search(self, event: AstrMessageEvent, query: str):
        '''联网搜索获取最新信息。当需要查询最新资讯、版本信息、实时数据或验证事实时使用此工具。

        【重要规则】
        1. query 必须是用户的原始问题，禁止任何修改
        2. 禁止翻译、展开缩写、添加年份日期

        Args:
            query(string): 用户的原始问题，必须原样传递
        '''
        logger.info(f"[智能搜索] LLM 调用搜索: {query}")
        return await self._do_search(query)
    
    @filter.command("search")
    async def search_command(self, event: AstrMessageEvent, query: str = ""):
        '''手动触发联网搜索
        
        用法: /search <搜索内容>
        '''
        if not query:
            yield event.plain_result("请提供搜索内容，例如: /search HOI4 最新版本")
            return
        
        logger.info(f"[智能搜索] 手动搜索: {query}")
        result = await self._do_search(query)
        yield event.plain_result(result)
    
    async def terminate(self):
        """插件卸载"""
        logger.info("[智能搜索] 插件已卸载")
