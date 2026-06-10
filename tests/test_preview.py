"""
pytest tests for xhs_preview.generate_preview。

覆盖场景:
  1. 基本输出：HTML 含全部图片引用与免责声明
  2. needs_human_edit：HTML 含 needs-edit 样式与 warn-banner
  3. 分割帖：第 2 帖出现「15-30 分钟」提示
  4. 禁词报告：HTML 含全部 BANNED_PHRASES 中的词语
  5. 多图路径：多张内容卡的文件名均出现在 HTML 中
  6. 原推对照：source panel 含原文和翻译
"""
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from xhs_composer import BANNED_PHRASES, DISCLAIMER, ContentCard, PostPlan
from xhs_preview import RenderedPlan, generate_preview

RUN_DATE = date(2026, 6, 10)


def _make_png(path: Path) -> Path:
    Image.new("RGB", (1080, 1440), (252, 250, 244)).save(path, "PNG")
    return path


# ── 共用 fixtures ──────────────────────────────────────────────────────────────

CARD_T1 = ContentCard(
    source_post_id="t1",
    heading="NVDA 供给缺口短期难解",
    points=["需求加速增长", "产能扩张滞后"],
)

PLAN_BASIC = PostPlan(
    title="白毛股神6.10盘前｜英伟达供给白毛来看",
    cover_headline="英伟达供给白毛来看",
    cover_subline="两条干货",
    cards=[CARD_T1],
    caption=f"测试正文\n\n#美股\n\n{DISCLAIMER}",
    session="盘前",
)

POSTS = {
    "t1": {
        "id": "t1",
        "content": "NVDA supply is very tight right now.",
        "translation": "英伟达供给目前非常紧张。",
    }
}


# ── 1. 基本输出 ───────────────────────────────────────────────────────────────

def test_generate_preview_contains_images_and_disclaimer(tmp_path):
    cover = _make_png(tmp_path / "cover.png")
    card  = _make_png(tmp_path / "card.png")
    tail  = _make_png(tmp_path / "tail.png")

    rp = RenderedPlan(plan=PLAN_BASIC, cover_path=cover, card_paths=[card], tail_path=tail)
    out = tmp_path / "preview.html"
    result = generate_preview([rp], POSTS, out, RUN_DATE, "盘前")

    assert result == out
    assert out.exists()
    text = out.read_text(encoding="utf-8")

    assert "cover.png" in text
    assert "card.png"  in text
    assert "tail.png"  in text
    assert DISCLAIMER in text
    assert "白毛股神6.10盘前｜英伟达供给白毛来看" in text


# ── 2. needs_human_edit ───────────────────────────────────────────────────────

def test_generate_preview_needs_edit_shows_warning(tmp_path):
    cover = _make_png(tmp_path / "cover.png")
    tail  = _make_png(tmp_path / "tail.png")

    plan_edit = PostPlan(
        title="白毛股神6.10盘前｜测试",
        cover_headline="测试标题",
        cover_subline="副标题",
        cards=[CARD_T1],
        caption=f"正文\n\n{DISCLAIMER}",
        session="盘前",
        needs_human_edit=True,
    )
    rp = RenderedPlan(plan=plan_edit, cover_path=cover, card_paths=[], tail_path=tail)
    out = tmp_path / "preview.html"
    generate_preview([rp], {}, out, RUN_DATE, "盘前")

    text = out.read_text(encoding="utf-8")
    assert "needs-edit" in text
    assert "warn-banner" in text


# ── 3. 分割帖计时提示 ─────────────────────────────────────────────────────────

def test_generate_preview_split_post_timing_notice(tmp_path):
    cover = _make_png(tmp_path / "cover.png")
    tail  = _make_png(tmp_path / "tail.png")

    plan_p1 = PostPlan(
        title="白毛股神6.10盘前｜测试【1】",
        cover_headline="测试", cover_subline="第一帖",
        cards=[CARD_T1], caption=f"正文\n\n{DISCLAIMER}",
        session="盘前", part_no=1,
    )
    plan_p2 = PostPlan(
        title="白毛股神6.10盘前｜测试【2】",
        cover_headline="测试续", cover_subline="第二帖",
        cards=[CARD_T1], caption=f"正文续\n\n{DISCLAIMER}",
        session="盘前", part_no=2,
    )

    rps = [
        RenderedPlan(plan=plan_p1, cover_path=cover, card_paths=[], tail_path=tail),
        RenderedPlan(plan=plan_p2, cover_path=cover, card_paths=[], tail_path=tail),
    ]
    out = tmp_path / "preview.html"
    generate_preview(rps, {}, out, RUN_DATE, "盘前")

    text = out.read_text(encoding="utf-8")
    assert "15-30 分钟" in text


# ── 4. 禁词报告含全部禁词 ─────────────────────────────────────────────────────

def test_generate_preview_scan_report_lists_all_banned_phrases(tmp_path):
    cover = _make_png(tmp_path / "cover.png")
    tail  = _make_png(tmp_path / "tail.png")

    rp = RenderedPlan(plan=PLAN_BASIC, cover_path=cover, card_paths=[], tail_path=tail)
    out = tmp_path / "preview.html"
    generate_preview([rp], {}, out, RUN_DATE, "盘前")

    text = out.read_text(encoding="utf-8")
    for phrase in BANNED_PHRASES:
        assert phrase in text, f"禁词「{phrase}」未出现在扫描报告中"


# ── 5. 多张内容卡路径 ─────────────────────────────────────────────────────────

def test_generate_preview_multiple_card_images(tmp_path):
    cover  = _make_png(tmp_path / "cover.png")
    card_a = _make_png(tmp_path / "card_a.png")
    card_b = _make_png(tmp_path / "card_b.png")
    card_c = _make_png(tmp_path / "card_c.png")
    tail   = _make_png(tmp_path / "tail.png")

    rp = RenderedPlan(
        plan=PLAN_BASIC,
        cover_path=cover,
        card_paths=[card_a, card_b, card_c],
        tail_path=tail,
    )
    out = tmp_path / "preview.html"
    generate_preview([rp], {}, out, RUN_DATE, "盘前")

    text = out.read_text(encoding="utf-8")
    for name in ["card_a.png", "card_b.png", "card_c.png"]:
        assert name in text


# ── 6. 原推对照内容 ───────────────────────────────────────────────────────────

def test_generate_preview_source_tweets_in_right_panel(tmp_path):
    cover = _make_png(tmp_path / "cover.png")
    tail  = _make_png(tmp_path / "tail.png")

    rp = RenderedPlan(plan=PLAN_BASIC, cover_path=cover, card_paths=[], tail_path=tail)
    out = tmp_path / "preview.html"
    generate_preview([rp], POSTS, out, RUN_DATE, "盘前")

    text = out.read_text(encoding="utf-8")
    assert "NVDA supply is very tight right now." in text
    assert "英伟达供给目前非常紧张。" in text
    assert "t1" in text  # source_post_id shown
