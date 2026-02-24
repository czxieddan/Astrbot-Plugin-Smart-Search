"""
搜索框架 - 精简版
直接用用户原句 + 固定后缀搜索，使用 Tavily API 原生时间过滤
"""
import asyncio
import re
from typing import List, Dict
from astrbot.api import logger

from .models import SearchResult, SearchReport
from .tavily_client import TavilyClient


class SearchFramework:
    """
    搜索框架
    
    流程：原句 + 固定后缀 → 并行搜索 → 去重 → 格式化返回
    """
    
    def __init__(self, tavily_client: TavilyClient, max_days_old: int = 0, show_sources: bool = False):
        """
        初始化搜索框架
        
        Args:
            tavily_client: Tavily API 客户端
            max_days_old: 时间过滤（天），0 表示不限制
            show_sources: 是否在结果中显示来源 URL
        """
        self.tavily = tavily_client
        self.max_days_old = max_days_old
        self.show_sources = show_sources
    
    async def search(self, query: str) -> SearchReport:
        """
        执行搜索
        
        Args:
            query: 用户的搜索问题
            
        Returns:
            SearchReport: 搜索报告
        """
        report = SearchReport(original_query=query)
        
        # 清理搜索词中的日期（防止 AI 自作主张添加）
        query = self._clean_query(query)
        
        # 显示配置
        if self.max_days_old > 0:
            logger.info(f"🔍 [搜索] 时间过滤: {self.max_days_old} 天内")
        
        logger.info(f"🔍 [搜索] 关键词: {query}")
        
        # 生成搜索词（原句 + 固定后缀）
        search_queries = [
            f"{query} wiki",
            f"{query} 贴吧",
            f"{query} 攻略",
            query,
            f"{query} wiki",      # 英文 wiki
            f"{query} reddit"     # Reddit
        ]
        
        # 重置 Key 池状态
        self.tavily.key_pool.reset()
        
        # 并行搜索
        logger.info(f"   → 并行搜索 {len(search_queries)} 个词...")
        tasks = [
            self.tavily.search(q, max_results=10, days=self.max_days_old if self.max_days_old > 0 else None)
            for q in search_queries
        ]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 收集结果并去重
        seen_urls = set()
        all_results = []
        
        for i, results in enumerate(results_list):
            if isinstance(results, Exception):
                logger.warning(f"      搜索失败: {results}")
                continue
            
            if results:
                logger.info(f"      '{search_queries[i][:20]}...' 返回 {len(results)} 条")
            
            for r in results or []:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    content = r.get("content", "")
                    all_results.append(SearchResult(
                        title=r.get("title", ""),
                        url=url,
                        content=content,
                        language="zh" if any('\u4e00' <= c <= '\u9fff' for c in content[:100]) else "en"
                    ))
        
        report.all_results = all_results
        report.valid_results = all_results
        
        logger.info(f"   → 总计 {len(all_results)} 条唯一结果")
        
        # 格式化为参考资料
        report.summary = self._format_reference(query, all_results)
        
        return report
    
    def _clean_query(self, query: str) -> str:
        """清理搜索词中的日期"""
        original = query
        
        # 移除年份和日期
        query = re.sub(r'\b20\d{2}\b', '', query)
        query = re.sub(r'\d{4}[-/.]\d{1,2}[-/.]\d{1,2}', '', query)
        query = re.sub(r'\d{4}年\d{1,2}月\d{1,2}日?', '', query)
        query = re.sub(r'\s+', ' ', query).strip()
        
        if query != original:
            logger.info(f"🔍 [搜索] 已移除日期: '{original}' → '{query}'")
        
        return query
    
    def _format_reference(self, query: str, results: List[SearchResult]) -> str:
        """格式化搜索结果为参考资料"""
        if not results:
            return "【搜索结果】未找到相关信息。"
        
        lines = [
            "【搜索结果参考资料】",
            f"原始问题：{query}",
            "",
            f"【搜索结果详情】共 {len(results)} 条"
        ]
        
        # 最多显示 20 条结果
        for i, r in enumerate(results[:20]):
            lines.extend([
                f"\n--- 来源 {i+1} ---",
                f"标题: {r.title}",
                f"URL: {r.url}",
                f"内容: {r.content[:800]}"
            ])
        
        lines.extend([
            "",
            "=" * 50,
            "请根据以上搜索结果回答用户的问题。"
        ])
        
        # 显示来源
        if self.show_sources:
            lines.extend([
                "",
                "【重要】请在回复末尾添加参考来源：",
                "---",
                "参考来源："
            ])
            for i, r in enumerate(results[:10]):
                lines.append(f"{i+1}. {r.url}")
        
        return "\n".join(lines)
