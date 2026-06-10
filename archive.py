"""
按天归档已分析帖子到 archive/YYYY-MM-DD.jsonl,供 weekly 模式读取。
每行一条完整帖子(含 translation/motivation/investment_action)。
同 id 不重复写入。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

ARCHIVE_DIR = Path("archive")


def append_posts(analyzed: list[dict]) -> None:
    if not analyzed:
        return
    ARCHIVE_DIR.mkdir(exist_ok=True)
    today_file = ARCHIVE_DIR / f"{date.today().isoformat()}.jsonl"

    existing_ids: set[str] = set()
    if today_file.exists():
        with open(today_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        existing_ids.add(json.loads(line)["id"])
                    except (json.JSONDecodeError, KeyError):
                        pass

    new_entries = [p for p in analyzed if p.get("id") not in existing_ids]
    if not new_entries:
        return

    with open(today_file, "a", encoding="utf-8") as f:
        for post in new_entries:
            f.write(json.dumps(post, ensure_ascii=False) + "\n")
    print(f"[archive] 写入 {len(new_entries)} 条 → {today_file}")


def prune(days: int = 7) -> None:
    if not ARCHIVE_DIR.exists():
        return
    cutoff = date.today() - timedelta(days=days)
    for path in ARCHIVE_DIR.glob("*.jsonl"):
        try:
            file_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if file_date < cutoff:
            path.unlink()
            print(f"[archive] 删除过期文件 {path.name}")


def load_range(start_date: date, end_date: date) -> list[dict]:
    posts: list[dict] = []
    if not ARCHIVE_DIR.exists():
        return posts
    current = start_date
    while current <= end_date:
        path = ARCHIVE_DIR / f"{current.isoformat()}.jsonl"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            posts.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        current += timedelta(days=1)
    return posts
