"""临时验证脚本:测试 archive.py 的四个场景,跑完自动清理。"""
import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from archive import append_posts, prune, load_range, ARCHIVE_DIR

TODAY = date.today()

FAKE_POSTS = [
    {
        "id": "test_001",
        "handle": "@aleabitoreddit",
        "display_name": "Serenity",
        "content": "Nvidia is unstoppable.",
        "timestamp": "Wed Jun 10 08:00:00 +0000 2026",
        "translation": "她认为英伟达势不可挡。",
        "motivation": "分享对英伟达的看好情绪",
        "investment_action": {"summary": "仅供内部", "direction": "做多"},
    },
    {
        "id": "test_002",
        "handle": "@aleabitoreddit",
        "display_name": "Serenity",
        "content": "Fed pause is priced in.",
        "timestamp": "Wed Jun 10 09:00:00 +0000 2026",
        "translation": "她认为市场已消化了美联储暂停加息的预期。",
        "motivation": "评论美联储政策影响",
        "investment_action": {"summary": "仅供内部", "direction": "观望"},
    },
    {
        "id": "test_003",
        "handle": "@aleabitoreddit",
        "display_name": "Serenity",
        "content": "Oil breaking down.",
        "timestamp": "Wed Jun 10 10:00:00 +0000 2026",
        "translation": "她指出油价正在走弱。",
        "motivation": "提示大宗商品下行风险",
        "investment_action": {"summary": "仅供内部", "direction": "做空"},
    },
]


def assert_eq(label: str, expected, actual) -> None:
    assert expected == actual, f"FAIL [{label}]: expected {expected!r}, got {actual!r}"
    print(f"  PASS  {label}")


def run():
    today_file = ARCHIVE_DIR / f"{TODAY.isoformat()}.jsonl"

    # ── 准备:确保今天的文件不存在(幂等) ──────────────────────────────
    if today_file.exists():
        today_file.unlink()

    print("场景 1: 首次写入 3 条假帖子")
    append_posts(FAKE_POSTS)
    assert today_file.exists(), f"FAIL: {today_file} 不存在"
    lines = [l for l in today_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert_eq("行数 == 3", 3, len(lines))
    for i, line in enumerate(lines):
        parsed = json.loads(line)
        assert_eq(f"第{i+1}行是合法 JSON(有 id 字段)", True, "id" in parsed)
    print()

    print("场景 2: 相同数据再次 append(去重)")
    append_posts(FAKE_POSTS)
    lines2 = [l for l in today_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert_eq("去重后仍然只有 3 行", 3, len(lines2))
    print()

    print("场景 3: prune() 删除 8 天前文件、保留今天文件")
    stale_date = TODAY - timedelta(days=8)
    stale_file = ARCHIVE_DIR / f"{stale_date.isoformat()}.jsonl"
    stale_file.touch()
    prune()
    assert_eq("8天前文件已被删除", False, stale_file.exists())
    assert_eq("今天文件仍然存在", True, today_file.exists())
    print()

    print("场景 4: load_range(7天前, 今天) 返回 3 条")
    posts = load_range(TODAY - timedelta(days=7), TODAY)
    assert_eq("load_range 返回条数 == 3", 3, len(posts))
    print()

    print("清理测试文件...")
    shutil.rmtree(ARCHIVE_DIR)
    print(f"  已删除 {ARCHIVE_DIR}/")

    print("\n全部断言通过 ✓")


if __name__ == "__main__":
    run()
