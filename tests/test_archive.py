"""pytest tests for archive.py — uses tmp_path to avoid touching real archive/."""
import json
from datetime import date, timedelta

import archive as archive_mod
from archive import append_posts, load_range, prune

TODAY = date.today()

FAKE_POSTS = [
    {
        "id": "t1",
        "handle": "@aleabitoreddit",
        "display_name": "Serenity",
        "content": "Nvidia is unstoppable.",
        "timestamp": "2026-06-10T08:00:00Z",
        "translation": "她认为英伟达势不可挡。",
        "motivation": "测试",
    },
    {
        "id": "t2",
        "handle": "@aleabitoreddit",
        "display_name": "Serenity",
        "content": "Fed pause is priced in.",
        "timestamp": "2026-06-10T09:00:00Z",
        "translation": "她认为市场已消化了美联储暂停加息的预期。",
        "motivation": "测试",
    },
    {
        "id": "t3",
        "handle": "@aleabitoreddit",
        "display_name": "Serenity",
        "content": "Oil breaking down.",
        "timestamp": "2026-06-10T10:00:00Z",
        "translation": "她指出油价正在走弱。",
        "motivation": "测试",
    },
]


def test_write_creates_file_with_3_valid_json_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_mod, "ARCHIVE_DIR", tmp_path)
    append_posts(FAKE_POSTS)
    today_file = tmp_path / f"{TODAY.isoformat()}.jsonl"
    assert today_file.exists()
    lines = [l for l in today_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 3
    for line in lines:
        data = json.loads(line)
        assert "id" in data


def test_dedup_same_data_appended_twice_stays_3_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_mod, "ARCHIVE_DIR", tmp_path)
    append_posts(FAKE_POSTS)
    append_posts(FAKE_POSTS)
    today_file = tmp_path / f"{TODAY.isoformat()}.jsonl"
    lines = [l for l in today_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 3


def test_prune_removes_8day_old_file_keeps_today(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_mod, "ARCHIVE_DIR", tmp_path)
    append_posts(FAKE_POSTS)
    stale_date = TODAY - timedelta(days=8)
    stale_file = tmp_path / f"{stale_date.isoformat()}.jsonl"
    stale_file.touch()
    prune()
    assert not stale_file.exists()
    assert (tmp_path / f"{TODAY.isoformat()}.jsonl").exists()


def test_load_range_returns_3_posts(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_mod, "ARCHIVE_DIR", tmp_path)
    append_posts(FAKE_POSTS)
    posts = load_range(TODAY - timedelta(days=7), TODAY)
    assert len(posts) == 3
