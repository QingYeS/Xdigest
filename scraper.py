from __future__ import annotations
import json
import re
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

_TCO_RE = re.compile(r'\s*https://t\.co/\S+', re.IGNORECASE)

from config import COOKIES_FILE, FINANCE_KEYWORDS

LOOKBACK_HOURS = 12

BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

# HomeLatestTimeline = Following 时间线（按时间排序）
# X 每次发版都会改 queryId，这里保留多个备用
QUERY_IDS = [
    "dFCRhpqUvbxPfq6lGSJdEQ",
    "s-skDAIxHmHDhMGKJGNMHA",
    "U0cdisy7QFIoTfu3-Ogmog",
]

_FEATURES = {
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}


def _load_cookies() -> dict:
    with open(COOKIES_FILE) as f:
        raw = json.load(f)
    return {c["name"]: c["value"] for c in raw}


def _headers(ct0: str) -> dict:
    return {
        "authorization": f"Bearer {BEARER}",
        "x-csrf-token": ct0,
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
        "content-type": "application/json",
        "referer": "https://x.com/home",
        "origin": "https://x.com",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }


def _auto_discover_query_id() -> str | None:
    """从 X 的 JS bundle 里自动发现当前 queryId"""
    print("  正在自动发现最新 queryId...")
    try:
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
        r = requests.get("https://x.com/home", headers={"user-agent": ua}, timeout=10)
        js_urls = re.findall(
            r'https://abs\.twimg\.com/responsive-web/client-web/[^"]+\.js', r.text
        )
        for url in js_urls[:8]:
            r2 = requests.get(url, timeout=10)
            m = re.search(
                r'queryId:"([^"]+)",operationName:"HomeLatestTimeline"', r2.text
            )
            if m:
                qid = m.group(1)
                print(f"  发现 queryId: {qid}")
                return qid
    except Exception as e:
        print(f"  自动发现失败: {e}")
    return None


def _extract_tweets(data: dict) -> list[dict]:
    tweets = []
    try:
        instructions = (
            data["data"]["home"]["home_timeline_urt"]["instructions"]
        )
        for instr in instructions:
            if instr.get("type") != "TimelineAddEntries":
                continue
            for entry in instr.get("entries", []):
                content = entry.get("content", {})
                if content.get("entryType") != "TimelineTimelineItem":
                    continue
                item = content.get("itemContent", {})
                if item.get("itemType") != "TimelineTweet":
                    continue
                result = item.get("tweet_results", {}).get("result", {})
                tweet = result.get("tweet", result)
                legacy = tweet.get("legacy", {})
                user_result = (
                    tweet.get("core", {})
                    .get("user_results", {})
                    .get("result", {})
                )
                # X API 新结构: screen_name/name 在 user_result["core"]
                user_core = user_result.get("core", {})
                tid = legacy.get("id_str", "")
                # Note Tweet（长文）的完整内容在 note_tweet 字段
                text = ""
                note = tweet.get("note_tweet", {})
                if note:
                    text = (note.get("note_tweet_results", {})
                                .get("result", {})
                                .get("text", ""))
                if not text:
                    text = legacy.get("full_text", "")
                text = _TCO_RE.sub("", text).strip()
                handle = user_core.get("screen_name", "")
                if tid and text:
                    tweets.append({
                        "id": tid,
                        "url": f"https://x.com/{handle}/status/{tid}",
                        "display_name": user_core.get("name", ""),
                        "handle": f"@{handle}",
                        "timestamp": legacy.get("created_at", ""),
                        "content": text,
                    })
    except (KeyError, TypeError):
        pass
    return tweets


def _extract_bottom_cursor(data: dict) -> str | None:
    """从响应中提取 Bottom 游标用于翻页"""
    try:
        instructions = data["data"]["home"]["home_timeline_urt"]["instructions"]
        for instr in instructions:
            if instr.get("type") != "TimelineAddEntries":
                continue
            for entry in instr.get("entries", []):
                content = entry.get("content", {})
                if content.get("entryType") == "TimelineTimelineCursor":
                    if content.get("cursorType") == "Bottom":
                        return content.get("value")
    except (KeyError, TypeError):
        pass
    return None


def _parse_tweet_time(created_at: str) -> datetime | None:
    if not created_at:
        return None
    try:
        return datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
    except Exception:
        return None


def _is_finance_related(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in FINANCE_KEYWORDS)


def _is_recent(created_at: str) -> bool:
    """只保留最近 LOOKBACK_HOURS 小时内的帖子"""
    if not created_at:
        return True  # 没有时间戳就保留
    try:
        dt = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
        return dt > cutoff
    except Exception:
        return True


def scrape_following_feed(**_) -> list[dict]:
    if not Path(COOKIES_FILE).exists():
        raise FileNotFoundError(f"找不到 {COOKIES_FILE}，请先运行 import_cookies.py")

    cookies = _load_cookies()
    ct0 = cookies.get("ct0", "")
    if not ct0:
        raise ValueError("ct0 cookie 缺失，请重新导出 Cookie")

    headers = _headers(ct0)
    variables = {
        "count": 100,
        "includePromotedContent": False,
        "latestControlAvailable": True,
        "requestContext": "launch",
        "withCommunity": True,
    }
    params = {
        "variables": json.dumps(variables),
        "features": json.dumps(_FEATURES),
    }

    query_ids = QUERY_IDS[:]

    # 先尝试已知 ID，失败再自动发现
    for attempt, qid in enumerate(query_ids):
        url = f"https://x.com/i/api/graphql/{qid}/HomeLatestTimeline"
        r = requests.get(url, headers=headers, cookies=cookies, params=params)
        print(f"  API 请求 [{qid[:8]}...]: HTTP {r.status_code}")

        if r.status_code == 200 and "data" in r.json():
            tweets = _extract_tweets(r.json())
            recent = [t for t in tweets if _is_recent(t["timestamp"])]
            finance = [t for t in recent if _is_finance_related(t["content"])]
            print(f"  获取 {len(tweets)} 条推文，12小时内 {len(recent)} 条，投资相关 {len(finance)} 条")
            return finance

        if r.status_code in (400, 404) and attempt == len(query_ids) - 1:
            # 所有已知 ID 都失败，尝试自动发现
            new_qid = _auto_discover_query_id()
            if new_qid and new_qid not in query_ids:
                query_ids.append(new_qid)

    raise RuntimeError(
        f"所有 queryId 均无效（最后状态码: {r.status_code}）\n"
        f"响应: {r.text[:300]}"
    )


def scrape_range(since: datetime, until: datetime, max_pages: int = 10) -> list[dict]:
    """
    抓取 since 到 until 时间段内的投资相关推文（带游标分页回溯）。
    since/until 必须是 timezone-aware datetime。
    """
    if not Path(COOKIES_FILE).exists():
        raise FileNotFoundError(f"找不到 {COOKIES_FILE}，请先运行 import_cookies.py")

    cookies = _load_cookies()
    ct0 = cookies.get("ct0", "")
    if not ct0:
        raise ValueError("ct0 cookie 缺失，请重新导出 Cookie")

    headers = _headers(ct0)
    query_ids = QUERY_IDS[:]

    # 发现有效 queryId（第一页顺带取回数据）
    first_data = None
    valid_qid = None
    for attempt, qid in enumerate(query_ids):
        variables = {
            "count": 100,
            "includePromotedContent": False,
            "latestControlAvailable": True,
            "requestContext": "launch",
            "withCommunity": True,
        }
        params = {"variables": json.dumps(variables), "features": json.dumps(_FEATURES)}
        url = f"https://x.com/i/api/graphql/{qid}/HomeLatestTimeline"
        r = requests.get(url, headers=headers, cookies=cookies, params=params)
        print(f"  API 请求 [{qid[:8]}...]: HTTP {r.status_code}")
        if r.status_code == 200 and "data" in r.json():
            valid_qid, first_data = qid, r.json()
            break
        if r.status_code in (400, 404) and attempt == len(query_ids) - 1:
            new_qid = _auto_discover_query_id()
            if new_qid and new_qid not in query_ids:
                query_ids.append(new_qid)

    if valid_qid is None:
        raise RuntimeError("所有 queryId 均无效")

    collected: list[dict] = []
    seen_ids: set[str] = set()
    total_fetched = 0

    def _process(data: dict):
        tweets = _extract_tweets(data)
        cursor = _extract_bottom_cursor(data)
        oldest = None
        for t in tweets:
            dt = _parse_tweet_time(t["timestamp"])
            if dt and (oldest is None or dt < oldest):
                oldest = dt
        return tweets, oldest, cursor

    cursor = None
    for page in range(1, max_pages + 1):
        if page == 1:
            tweets, oldest, cursor = _process(first_data)
        else:
            variables = {
                "count": 100,
                "includePromotedContent": False,
                "latestControlAvailable": True,
                "withCommunity": True,
                "cursor": cursor,
            }
            params = {"variables": json.dumps(variables), "features": json.dumps(_FEATURES)}
            url = f"https://x.com/i/api/graphql/{valid_qid}/HomeLatestTimeline"
            r = requests.get(url, headers=headers, cookies=cookies, params=params)
            print(f"  第{page}页 API: HTTP {r.status_code}")
            if r.status_code != 200 or "data" not in r.json():
                print(f"  翻页失败，停止")
                break
            tweets, oldest, cursor = _process(r.json())

        total_fetched += len(tweets)
        prev = len(collected)
        for t in tweets:
            dt = _parse_tweet_time(t["timestamp"])
            if dt and since <= dt <= until and t["id"] not in seen_ids:
                if _is_finance_related(t["content"]):
                    collected.append(t)
                    seen_ids.add(t["id"])

        oldest_str = oldest.strftime("%m-%d %H:%M UTC") if oldest else "未知"
        print(f"  第{page}页: {len(tweets)} 条，最早 {oldest_str}，窗口内新增 {len(collected) - prev} 条")

        if oldest and oldest < since:
            print(f"  已越过目标窗口起点，停止翻页")
            break
        if not cursor:
            print(f"  无更多游标，停止")
            break

    print(f"  共抓取 {total_fetched} 条，时间窗口内投资相关 {len(collected)} 条")
    return collected
