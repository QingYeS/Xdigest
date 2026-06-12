"""main.py 行为测试：--no-email / --force / FILTER_SOURCE_GLOBALLY 开关。"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

# Stub out packages that aren't installed in the test environment.
# Must happen before any import chain reaches them.
for _mod in ("groq", "requests", "ddgs"):
    sys.modules.setdefault(_mod, MagicMock())

import main  # noqa: E402  (must come after sys.modules stubs)


def test_no_email_skips_send_digest_when_no_new_posts():
    """no_email=True 且无新帖时，send_digest 不应被调用。"""
    with patch.object(main, "scrape_following_feed", return_value=[]), \
         patch.object(main, "_load_seen", return_value={}), \
         patch.object(main, "_save_seen"), \
         patch.object(main, "send_digest") as mock_send:
        main.run(no_email=True)
        mock_send.assert_not_called()


def test_no_email_skips_send_digest_with_new_posts():
    """no_email=True のとき、新帖分析後も send_digest は呼ばれない。"""
    fake_post = {"id": "123", "content": "NVDA is bullish", "timestamp": ""}
    fake_analyzed = [{"id": "123", "analysis": {}}]

    with patch.object(main, "scrape_following_feed", return_value=[fake_post]), \
         patch.object(main, "_load_seen", return_value={}), \
         patch.object(main, "_save_seen"), \
         patch.object(main, "analyze_posts", return_value=fake_analyzed), \
         patch.object(main, "append_posts"), \
         patch.object(main, "prune"), \
         patch.object(main, "send_digest") as mock_send:
        main.run(no_email=True)
        mock_send.assert_not_called()


def test_default_run_calls_send_digest():
    """no_email=False（默认）のとき、send_digest は通常通り呼ばれる。"""
    fake_post = {"id": "456", "content": "AMD gains", "timestamp": ""}
    fake_analyzed = [{"id": "456", "analysis": {}}]

    with patch.object(main, "FILTER_SOURCE_GLOBALLY", False), \
         patch.object(main, "scrape_following_feed", return_value=[fake_post]), \
         patch.object(main, "_load_seen", return_value={}), \
         patch.object(main, "_save_seen"), \
         patch.object(main, "analyze_posts", return_value=fake_analyzed), \
         patch.object(main, "append_posts"), \
         patch.object(main, "prune"), \
         patch.object(main, "send_digest") as mock_send:
        main.run(no_email=False)
        mock_send.assert_called_once_with(fake_analyzed)


def test_force_skips_dedup_processes_all_posts():
    """--force 时跳过去重：_load_seen 不被调用，所有帖子都进入分析。"""
    # scraper 返回两条帖，其中 id=111 假设已在 seen 中
    posts = [
        {"id": "111", "content": "NVDA supply", "timestamp": ""},
        {"id": "222", "content": "AMD gains", "timestamp": ""},
    ]
    fake_analyzed = [{"id": "111"}, {"id": "222"}]

    with patch.object(main, "FILTER_SOURCE_GLOBALLY", False), \
         patch.object(main, "scrape_following_feed", return_value=posts), \
         patch.object(main, "_load_seen") as mock_load, \
         patch.object(main, "_save_seen") as mock_save, \
         patch.object(main, "analyze_posts", return_value=fake_analyzed) as mock_analyze, \
         patch.object(main, "append_posts"), \
         patch.object(main, "prune"), \
         patch.object(main, "send_digest"):
        main.run(no_email=True, force=True)

    mock_load.assert_not_called()          # 不读 seen_posts
    mock_save.assert_not_called()          # 不写 seen_posts
    # analyze_posts 拿到的是全部两条，而不是去重后的子集
    called_posts = mock_analyze.call_args[0][0]
    assert {p["id"] for p in called_posts} == {"111", "222"}


def test_force_does_not_write_seen_posts():
    """--force 时即使处理了帖子，也不修改 seen_posts.json。"""
    fake_post = {"id": "999", "content": "SPY outlook", "timestamp": ""}
    fake_analyzed = [{"id": "999"}]

    with patch.object(main, "scrape_following_feed", return_value=[fake_post]), \
         patch.object(main, "_load_seen"), \
         patch.object(main, "_save_seen") as mock_save, \
         patch.object(main, "analyze_posts", return_value=fake_analyzed), \
         patch.object(main, "append_posts"), \
         patch.object(main, "prune"), \
         patch.object(main, "send_digest"):
        main.run(no_email=True, force=True)

    mock_save.assert_not_called()


# ── FILTER_SOURCE_GLOBALLY 测试 ───────────────────────────────────────────────

import blogger_config  # noqa: E402


_SERENITY_POST = {"id": "s1", "handle": "@aleabitoreddit", "content": "NVDA", "timestamp": ""}
_ELON_POST     = {"id": "e1", "handle": "@elonmusk",       "content": "TSLA", "timestamp": ""}


def test_filter_source_globally_excludes_non_tracked():
    """FILTER_SOURCE_GLOBALLY=True 时,非跟踪博主的帖子不进入 analyze_posts。"""
    fake_analyzed = [{"id": "s1"}]

    with patch.object(main, "FILTER_SOURCE_GLOBALLY", True), \
         patch.object(main, "scrape_following_feed", return_value=[_SERENITY_POST, _ELON_POST]), \
         patch.object(main, "_load_seen", return_value={}), \
         patch.object(main, "_save_seen"), \
         patch.object(main, "analyze_posts", return_value=fake_analyzed) as mock_analyze, \
         patch.object(main, "append_posts"), \
         patch.object(main, "prune"), \
         patch.object(main, "send_digest"):
        main.run(no_email=True)

    called_posts = mock_analyze.call_args[0][0]
    handles = {p["handle"] for p in called_posts}
    assert handles == {"@aleabitoreddit"}
    assert "@elonmusk" not in handles


def test_filter_source_globally_false_passes_all_posts():
    """FILTER_SOURCE_GLOBALLY=False 时,所有金融推都进入 analyze_posts。"""
    all_posts = [_SERENITY_POST, _ELON_POST]
    fake_analyzed = [{"id": "s1"}, {"id": "e1"}]

    with patch.object(main, "FILTER_SOURCE_GLOBALLY", False), \
         patch.object(main, "scrape_following_feed", return_value=all_posts), \
         patch.object(main, "_load_seen", return_value={}), \
         patch.object(main, "_save_seen"), \
         patch.object(main, "analyze_posts", return_value=fake_analyzed) as mock_analyze, \
         patch.object(main, "append_posts"), \
         patch.object(main, "prune"), \
         patch.object(main, "send_digest"):
        main.run(no_email=True)

    called_posts = mock_analyze.call_args[0][0]
    assert {p["id"] for p in called_posts} == {"s1", "e1"}


def test_filter_source_globally_excludes_disabled_blogger():
    """enabled=False 的博主即使在 TRACKED_BLOGGERS 中也应被排除。"""
    disabled_bloggers = [
        {"handle": "@aleabitoreddit", "display_name": "Serenity", "cn_name": "白毛股神", "enabled": False},
    ]

    with patch.object(main, "FILTER_SOURCE_GLOBALLY", True), \
         patch.object(blogger_config, "TRACKED_BLOGGERS", disabled_bloggers), \
         patch.object(main, "scrape_following_feed", return_value=[_SERENITY_POST]), \
         patch.object(main, "_load_seen", return_value={}), \
         patch.object(main, "_save_seen"), \
         patch.object(main, "analyze_posts") as mock_analyze, \
         patch.object(main, "send_digest"):
        main.run(no_email=True)

    mock_analyze.assert_not_called()


# ── xhs_pipeline 接入测试 ─────────────────────────────────────────────────────

def test_main_calls_generate_xhs_after_analyze():
    """run() 应在 analyze_posts 之后调用 generate_xhs，传入分析结果和 session。"""
    fake_post = {"id": "s3", "handle": "@aleabitoreddit", "content": "NVDA", "timestamp": ""}
    fake_analyzed = [{"id": "s3", "handle": "@aleabitoreddit"}]

    with patch.object(main, "FILTER_SOURCE_GLOBALLY", False), \
         patch.object(main, "scrape_following_feed", return_value=[fake_post]), \
         patch.object(main, "_load_seen", return_value={}), \
         patch.object(main, "_save_seen"), \
         patch.object(main, "analyze_posts", return_value=fake_analyzed), \
         patch.object(main, "append_posts"), \
         patch.object(main, "prune"), \
         patch.object(main, "send_digest"), \
         patch.object(main, "generate_xhs") as mock_xhs:
        main.run(no_email=True)

    mock_xhs.assert_called_once()
    called_analyzed, called_session = mock_xhs.call_args[0]
    assert called_analyzed == fake_analyzed
    assert called_session in ("盘前", "盘后")


def test_xhs_exception_does_not_block_send_digest():
    """generate_xhs 抛异常时，send_digest 应照常被调用。"""
    fake_post = {"id": "s4", "handle": "@aleabitoreddit", "content": "AMD", "timestamp": ""}
    fake_analyzed = [{"id": "s4", "handle": "@aleabitoreddit"}]

    with patch.object(main, "FILTER_SOURCE_GLOBALLY", False), \
         patch.object(main, "scrape_following_feed", return_value=[fake_post]), \
         patch.object(main, "_load_seen", return_value={}), \
         patch.object(main, "_save_seen"), \
         patch.object(main, "analyze_posts", return_value=fake_analyzed), \
         patch.object(main, "append_posts"), \
         patch.object(main, "prune"), \
         patch.object(main, "send_digest") as mock_send, \
         patch.object(main, "generate_xhs", side_effect=RuntimeError("渲染失败")):
        main.run(no_email=False)

    mock_send.assert_called_once_with(fake_analyzed)
