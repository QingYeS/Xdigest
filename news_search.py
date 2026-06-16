"""
用 DuckDuckGo 搜索帖子相关的最新新闻（免费，无需 API key）
"""
from __future__ import annotations
from ddgs import DDGS


def search_news(query: str, max_results: int = 3) -> list[dict]:
    """返回最多 max_results 条新闻，每条包含 title / body / url / date"""
    try:
        with DDGS() as ddg:
            results = list(ddg.news(
                keywords=query,
                region="wt-wt",
                safesearch="off",
                timelimit="d",   # 只取最近 24 小时
                max_results=max_results,
            ))
        return results
    except Exception:
        return []


def build_news_context(post_content: str) -> str:
    """从帖子内容提取关键词并搜索相关新闻，返回格式化的上下文字符串"""
    results = search_news(post_content[:200])
    if not results:
        return ""

    lines = ["【相关最新新闻】"]
    for r in results:
        date = r.get("date", "")[:10]
        title = r.get("title", "")
        body = r.get("body", "")[:120]
        lines.append(f"- [{date}] {title}：{body}")
    return "\n".join(lines)
