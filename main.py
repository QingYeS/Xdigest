#!/usr/bin/env python3
"""
X 投资动态摘要主程序
每次运行：调用 X 内部 API → 过滤投资相关 → 去重 → Groq 分析 → 发送邮件
"""
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import smtplib
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from scraper import scrape_following_feed
from analyzer import analyze_posts
from emailer import send_digest
from archive import append_posts, prune
from blogger_config import filter_tracked
from xhs_pipeline import generate_xhs
from config import SEEN_POSTS_FILE, GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL, FILTER_SOURCE_GLOBALLY

LOCAL_TZ = datetime.now().astimezone().tzinfo  # 系统本地时区
SEEN_EXPIRY_DAYS = 7


def _load_seen() -> dict:
    if Path(SEEN_POSTS_FILE).exists():
        with open(SEEN_POSTS_FILE) as f:
            return json.load(f)
    return {}


def _save_seen(seen: dict) -> None:
    with open(SEEN_POSTS_FILE, "w") as f:
        json.dump(seen, f, indent=2)


def _prune_seen(seen: dict) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=SEEN_EXPIRY_DAYS)
    return {
        k: v for k, v in seen.items()
        if datetime.fromisoformat(v) > cutoff
    }


def run(no_email: bool = False, force: bool = False):
    print(f"[{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M %Z')}] 开始抓取 X Following Feed...")

    posts = scrape_following_feed()

    if FILTER_SOURCE_GLOBALLY:
        tracked = filter_tracked(posts)
        posts = [p for ps in tracked.values() for p in ps]
        print(f"  全局过滤后剩余 {len(posts)} 条 (TRACKED_BLOGGERS)")

    if force:
        new_posts = posts
        print(f"--force 模式：跳过去重，处理全部 {len(new_posts)} 条帖子")
    else:
        seen = _prune_seen(_load_seen())
        new_posts = [p for p in posts if p["id"] not in seen]
        print(f"去重后剩余 {len(new_posts)} 条新帖子")

    if not new_posts:
        if not no_email:
            send_digest([])
        return

    print("正在用 Groq 分析帖子...")
    analyzed = analyze_posts(new_posts)

    if not no_email:
        send_digest(analyzed)

    try:
        append_posts(analyzed)
        prune()
    except Exception as archive_err:
        print(f"[archive] 写入失败(不影响邮件): {archive_err}")

    try:
        session_str = "盘前" if datetime.now(LOCAL_TZ).hour < 12 else "盘后"
        out_path = generate_xhs(analyzed, session_str)
        print(f"[xhs] 输出: {out_path}")
    except Exception as xhs_err:
        print(f"[xhs] 生成失败(不影响邮件): {xhs_err}")

    if not force:
        now_iso = datetime.now(timezone.utc).isoformat()
        for p in new_posts:
            seen[p["id"]] = now_iso
        _save_seen(seen)
    print("✓ 完成")


def _send_error_alert(error: Exception):
    now = datetime.now(LOCAL_TZ).strftime("%m/%d %H:%M %Z")
    msg_text = traceback.format_exc()
    is_auth = any(k in str(error).lower() for k in ["401", "403", "cookie", "auth", "unauthorized"])
    hint = (
        "❗ 可能是 X 的 Cookie 已过期，请重新从 Chrome 导出并运行：<br>"
        "<code>python3 /Users/qing/X/import_cookies.py</code>"
        if is_auth else
        f"错误详情：<pre style='font-size:12px;'>{msg_text}</pre>"
    )
    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,sans-serif;background:#f0f2f5;padding:32px 16px;">
  <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:16px;padding:32px;">
    <div style="font-size:36px;margin-bottom:12px;">⚠️</div>
    <div style="font-size:18px;font-weight:700;color:#c62828;margin-bottom:8px;">X 摘要系统运行出错</div>
    <div style="font-size:14px;color:#536471;margin-bottom:16px;">检查时间：{now}</div>
    <div style="font-size:14px;color:#0f1419;line-height:1.7;">{hint}</div>
  </div>
</body></html>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"⚠️ X 摘要系统出错 · {now}"
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
    print(f"✓ 错误通知已发送至 {RECIPIENT_EMAIL}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-email", action="store_true", help="跳过邮件发送（调试用）")
    parser.add_argument("--force", action="store_true", help="跳过去重，强制处理所有帖子，不写 seen_posts（调试用）")
    args = parser.parse_args()
    try:
        run(no_email=args.no_email, force=args.force)
    except Exception as e:
        print(f"❌ 运行出错: {e}")
        try:
            _send_error_alert(e)
        except Exception as mail_err:
            print(f"发送错误通知失败: {mail_err}")
