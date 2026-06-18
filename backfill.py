"""
backfill.py: 补抓指定时间段内的推文，完整链路（抓取→Groq分析→archive→XHS）。

用法:
    # 补昨晚盘后（自动推算 8am-8pm EST 窗口）
    python backfill.py --date 2026-06-17 --session 盘后

    # 补昨早盘前（前一天 8pm 到当天 8am）
    python backfill.py --date 2026-06-17 --session 盘前

    # 自定义时间（美东时间，24小时制）
    python backfill.py --since "2026-06-17 08:00" --until "2026-06-17 20:00"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from analyzer import analyze_posts
from archive import ARCHIVE_DIR, append_posts, load_range
from blogger_config import filter_tracked
from scraper import scrape_range
from xhs_pipeline import generate_xhs

# 美东夏令时 EDT = UTC-4（通用；若在标准时 EST=UTC-5 期间使用，时间会差 1h，可接受）
EDT = timezone(timedelta(hours=-4))


def _session_window(target_date: date, session: str):
    """根据日期和时段返回 (since, until) 的 EDT datetime。"""
    if session == "盘前":
        # 前一天 20:00 EDT 到当天 08:00 EDT
        since = datetime(target_date.year, target_date.month, target_date.day,
                         0, 0, tzinfo=EDT) - timedelta(hours=4)
        until = datetime(target_date.year, target_date.month, target_date.day,
                         8, 0, tzinfo=EDT)
    elif session == "盘后":
        # 当天 08:00 EDT 到 20:00 EDT
        since = datetime(target_date.year, target_date.month, target_date.day,
                         8, 0, tzinfo=EDT)
        until = datetime(target_date.year, target_date.month, target_date.day,
                         20, 0, tzinfo=EDT)
    else:
        raise ValueError(f"不支持的 session: {session}")
    return since, until


def _load_archive_ids(target_date: date) -> set[str]:
    """读取指定日期 archive 中已有的 post id，用于去重。"""
    path = ARCHIVE_DIR / f"{target_date.isoformat()}.jsonl"
    ids: set[str] = set()
    if not path.exists():
        return ids
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    ids.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    pass
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(
        description="补抓指定时间段的推文并生成小红书内容"
    )
    parser.add_argument("--date", metavar="YYYY-MM-DD",
                        help="目标日期（配合 --session 推算时间窗口）")
    parser.add_argument("--session", choices=["盘前", "盘后"],
                        help="时段（盘前=前日20:00~当日08:00 EDT，盘后=08:00~20:00 EDT）")
    parser.add_argument("--since", metavar="YYYY-MM-DD HH:MM",
                        help="自定义起始时间（美东时间，24h）")
    parser.add_argument("--until", metavar="YYYY-MM-DD HH:MM",
                        help="自定义结束时间（美东时间，24h）")
    parser.add_argument("--no-xhs", action="store_true",
                        help="只归档，不生成 XHS 图片")
    args = parser.parse_args()

    # 解析时间范围
    if args.since and args.until:
        try:
            since = datetime.strptime(args.since, "%Y-%m-%d %H:%M").replace(tzinfo=EDT)
            until = datetime.strptime(args.until, "%Y-%m-%d %H:%M").replace(tzinfo=EDT)
        except ValueError as e:
            print(f"[error] 时间格式错误: {e}，请用 'YYYY-MM-DD HH:MM'")
            sys.exit(1)
        target_date = until.date()
        session = "盘后" if until.hour >= 12 else "盘前"
    elif args.date and args.session:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            print(f"[error] --date 格式错误: {args.date!r}，应为 YYYY-MM-DD")
            sys.exit(1)
        session = args.session
        since, until = _session_window(target_date, session)
    else:
        parser.print_help()
        print("\n[error] 需要 (--date + --session) 或 (--since + --until)")
        sys.exit(1)

    print(f"[backfill] 目标窗口: {since.strftime('%Y-%m-%d %H:%M')} ~ "
          f"{until.strftime('%Y-%m-%d %H:%M')} EDT  (session={session})")

    # 抓取
    posts = scrape_range(since, until)
    if not posts:
        print("[backfill] 窗口内无符合条件的推文，退出")
        return

    # 过滤跟踪博主
    tracked = filter_tracked(posts)
    tracked_posts = [p for ps in tracked.values() for p in ps]
    if not tracked_posts:
        print("[backfill] 无跟踪博主推文，退出")
        return
    print(f"[backfill] 跟踪博主推文 {len(tracked_posts)} 条")

    # 去重（与已有 archive 对比）
    existing_ids = _load_archive_ids(target_date)
    new_posts = [p for p in tracked_posts if p["id"] not in existing_ids]
    if new_posts:
        print(f"[backfill] 去重后新增 {len(new_posts)} 条（已有 {len(existing_ids)} 条）")
        print("[backfill] 正在 Groq 分析...")
        analyzed = analyze_posts(new_posts)
        append_posts(analyzed, target_date=target_date)
    else:
        print(f"[backfill] 全部 {len(tracked_posts)} 条已在 archive，跳过分析和归档")

    if args.no_xhs:
        print("[backfill] --no-xhs，跳过 XHS 生成，完成")
        return

    # 从 archive 加载当日全量数据生成 XHS（确保日期正确）
    all_posts = load_range(target_date, target_date)
    if not all_posts:
        print("[backfill] archive 为空，无法生成 XHS")
        return
    out_path = generate_xhs(all_posts, session, run_date=target_date)
    print(f"[backfill] 完成，XHS 输出: {out_path}")


if __name__ == "__main__":
    main()
