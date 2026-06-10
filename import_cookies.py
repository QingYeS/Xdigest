#!/usr/bin/env python3
"""
把 Cookie-Editor 导出的 JSON 转换成 Playwright 格式并保存
用法：python3 import_cookies.py x_cookies_raw.json
"""
import json
import sys
from pathlib import Path
from config import COOKIES_FILE

SAMSITE_MAP = {"no_restriction": "None", "lax": "Lax", "strict": "Strict", "unspecified": "None"}

def convert(raw_path: str):
    with open(raw_path) as f:
        raw = json.load(f)

    converted = []
    for c in raw:
        converted.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "expires": c.get("expirationDate", -1),
            "httpOnly": c.get("httpOnly", False),
            "secure": c.get("secure", False),
            "sameSite": SAMSITE_MAP.get((c.get("sameSite") or "").lower(), "None"),
        })

    with open(COOKIES_FILE, "w") as f:
        json.dump(converted, f, indent=2)

    print(f"✓ 已转换 {len(converted)} 个 Cookie，保存至 {COOKIES_FILE}")

if __name__ == "__main__":
    raw = sys.argv[1] if len(sys.argv) > 1 else "x_cookies_raw.json"
    if not Path(raw).exists():
        print(f"找不到文件：{raw}")
        print("请先把 Cookie-Editor 导出的 JSON 保存为 x_cookies_raw.json")
        sys.exit(1)
    convert(raw)
