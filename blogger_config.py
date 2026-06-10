"""博主配置化模块。博主信息在此统一维护,不硬编码到逻辑层。"""
from __future__ import annotations

from typing import Dict, List, Optional

TRACKED_BLOGGERS: List[Dict] = [
    {
        "handle": "@aleabitoreddit",
        "display_name": "Serenity",
        "cn_name": "白毛股神",
        "enabled": True,
    },
]


def filter_tracked(posts: List[dict]) -> Dict[str, List[dict]]:
    """返回 {handle: [posts]},只保留已启用的跟踪博主的帖子。"""
    enabled = {b["handle"] for b in TRACKED_BLOGGERS if b["enabled"]}
    result: Dict[str, List[dict]] = {}
    for post in posts:
        handle = post.get("handle", "")
        if handle in enabled:
            result.setdefault(handle, []).append(post)
    return result


def get_blogger(handle: str) -> Optional[Dict]:
    for b in TRACKED_BLOGGERS:
        if b["handle"] == handle:
            return b
    return None
