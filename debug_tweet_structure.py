#!/usr/bin/env python3
"""打印第一条推文的原始 JSON 结构，用于调试字段路径"""
import json
import requests
from scraper import _load_cookies, _headers, _auto_discover_query_id, QUERY_IDS, _FEATURES

cookies = _load_cookies()
ct0 = cookies.get("ct0", "")
headers = _headers(ct0)
variables = {"count": 5, "includePromotedContent": False, "latestControlAvailable": True, "requestContext": "launch", "withCommunity": True}
params = {"variables": json.dumps(variables), "features": json.dumps(_FEATURES)}

qid = _auto_discover_query_id() or QUERY_IDS[0]
r = requests.get(f"https://x.com/i/api/graphql/{qid}/HomeLatestTimeline", headers=headers, cookies=cookies, params=params)

data = r.json()
try:
    entries = data["data"]["home"]["home_timeline_urt"]["instructions"][0]["entries"]
    for entry in entries[:3]:
        content = entry.get("content", {})
        if content.get("entryType") != "TimelineTimelineItem":
            continue
        item = content.get("itemContent", {})
        result = item.get("tweet_results", {}).get("result", {})
        tweet = result.get("tweet", result)
        print("=== tweet keys:", list(tweet.keys()))
        core = tweet.get("core", {})
        print("=== core keys:", list(core.keys()))
        user_result = core.get("user_results", {}).get("result", {})
        print("=== user_result keys:", list(user_result.keys()))
        legacy = user_result.get("legacy", {})
        print("=== user legacy keys:", list(legacy.keys())[:10])
        print("=== screen_name:", legacy.get("screen_name"))
        print("=== name:", legacy.get("name"))
        print()
        break
except Exception as e:
    print(f"Error: {e}")
    print(json.dumps(data, indent=2)[:2000])
