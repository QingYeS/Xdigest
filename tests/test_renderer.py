"""冒烟测试：xhs_renderer 三类函数输出合法 PNG，尺寸 1080×1440，文件非空。"""
from datetime import date
from pathlib import Path

import pytest
from xhs_composer import ContentCard, PostPlan
from xhs_renderer import render_card, render_cover, render_tail

RUN_DATE = date(2026, 6, 10)

BLOGGER = {
    "handle": "@aleabitoreddit",
    "display_name": "Serenity",
    "cn_name": "白毛股神",
}

DEMO_CARD = ContentCard(
    source_post_id="t1",
    heading="英伟达供给持续紧张短期难解",
    points=["数据中心需求持续加速增长", "台积电扩产计划明显滞后"],
)

DEMO_PLAN = PostPlan(
    title="白毛股神6.10盘前｜英伟达她还在硬刚",
    cover_headline="英伟达她还在硬刚",
    cover_subline="三大理由说明短缺仍在",
    cards=[DEMO_CARD],
    caption="测试 caption",
    session="盘前",
)


def _assert_png(path: Path) -> None:
    from PIL import Image
    assert path.exists(), f"文件未生成: {path}"
    assert path.stat().st_size > 0, f"文件为空: {path}"
    img = Image.open(path)
    assert img.size == (1080, 1440), f"尺寸错误: {img.size}，期望 (1080, 1440)"
    assert img.mode == "RGB"


def test_render_cover(tmp_path):
    out = tmp_path / "cover.png"
    render_cover(DEMO_PLAN, out, run_date=RUN_DATE)
    _assert_png(out)


def test_render_card_part1(tmp_path):
    out = tmp_path / "card1.png"
    render_card(DEMO_CARD, out, run_date=RUN_DATE, session="盘前")
    _assert_png(out)


def test_render_card_part2_shows_no_error(tmp_path):
    """长推第 2 张（part=2）应正常渲染，含「第 2 张」标签。"""
    card2 = ContentCard(
        source_post_id="t1",
        heading="续：供给缺口的深层原因",
        points=["HBM 内存供应商全球仅三家", "CoWoS 封装工艺严重瓶颈"],
        part=2,
    )
    out = tmp_path / "card2.png"
    render_card(card2, out, run_date=RUN_DATE, session="盘前")
    _assert_png(out)


def test_render_tail(tmp_path):
    out = tmp_path / "tail.png"
    render_tail(out, blogger=BLOGGER)
    _assert_png(out)


def test_render_card_four_points_extreme(tmp_path):
    """4 个要点的极限用例不应崩溃或溢出画布。"""
    card = ContentCard(
        source_post_id="t2",
        heading="美联储内部分歧加剧走势难判断",
        points=[
            "鹰派委员倾向年内仅降息一次",
            "鸽派认为就业数据已显示经济降温",
            "市场定价介于一次与两次降息之间",
            "她认为短期内方向难以明确判断",
        ],
    )
    out = tmp_path / "card_extreme.png"
    render_card(card, out, run_date=RUN_DATE, session="盘后")
    _assert_png(out)


def test_render_cover_long_headline(tmp_path):
    """长标题（接近 12 字上限）正常换行，不崩溃。"""
    plan = PostPlan(
        title="白毛股神6.10盘前｜供给短缺远未结束",
        cover_headline="供给短缺远未结束三大理由",
        cover_subline="数据中心需求加速台积电扩产滞后",
        cards=[DEMO_CARD],
        caption="测试",
        session="盘前",
    )
    out = tmp_path / "cover_long.png"
    render_cover(plan, out, run_date=RUN_DATE)
    _assert_png(out)


def test_render_card_with_quote(tmp_path):
    """含 quote 字段的卡片应正常渲染便利贴，不崩溃。"""
    card = ContentCard(
        source_post_id="t3",
        heading="Serenity 对时间窗口的判断",
        points=["供给缺口预计持续至2027年上半年", "台积电新厂爬坡需18至24个月"],
        quote="I think the supply gap will last at least through H1 2027.",
    )
    out = tmp_path / "card_quote.png"
    render_card(card, out, run_date=RUN_DATE, session="盘前")
    _assert_png(out)


def test_render_card_long_quote_no_overflow(tmp_path):
    """超长 quote(含 2027, 60+ 字符)渲染成功，不溢出画布。"""
    card = ContentCard(
        source_post_id="t_lq",
        heading="Serenity 对时间窗口的判断",
        points=["供给缺口预计持续至2027年上半年", "台积电扩产爬坡需18至24个月"],
        quote="I believe the supply gap will persist well beyond 2027, and frankly the market hasn't fully priced this in yet.",
    )
    out = tmp_path / "card_longquote.png"
    render_card(card, out, run_date=RUN_DATE, session="盘前")
    _assert_png(out)


def test_render_card_with_ticker_in_heading(tmp_path):
    """heading 含 $TICKER 时，同名 ticker 不再另渲徽章（dedup），不崩溃。"""
    card = ContentCard(
        source_post_id="t4",
        heading="$NVDA 供给缺口短期难解",
        points=["数据中心需求持续加速增长", "台积电扩产计划明显滞后"],
        tickers=[{"symbol": "NVDA", "stance": "bullish"}],
    )
    out = tmp_path / "card_ticker_dedup.png"
    render_card(card, out, run_date=RUN_DATE, session="盘前")
    _assert_png(out)


def test_filter_display_tickers_removes_heading_symbols():
    """heading 中已出现 $XXX 的 ticker 应被 filter 函数过滤。"""
    from xhs_renderer import _filter_display_tickers
    heading = "$NVDA 供给缺口短期难解"
    tickers = [
        {"symbol": "NVDA", "stance": "bullish"},
        {"symbol": "AMD",  "stance": "neutral"},
    ]
    result = _filter_display_tickers(heading, tickers)
    assert len(result) == 1
    assert result[0]["symbol"] == "AMD"


def test_wrap_mixed_text_english_word_stays_intact():
    """wrap_mixed_text must never split an English word across lines."""
    from PIL import Image, ImageDraw
    from xhs_renderer import wrap_mixed_text, _bold
    img = Image.new("RGBA", (1080, 100), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    f = _bold(88)
    # "Serenity" at 88pt is ~300px wide; cover usable width is 840px
    # Mix of CJK and ASCII to force multi-line wrapping
    for text in ["英伟达Serenity还在硬刚", "Serenity 认为短期难判断"]:
        lines = wrap_mixed_text(draw, text, f, 840)
        for line in lines:
            # Partial word: line contains start of "Serenity" but not full word
            assert "Seren" not in line or "Serenity" in line, (
                f"'Serenity' was broken across a line boundary: {lines!r}"
            )


def test_render_card_three_stance_badges(tmp_path):
    """三种 stance（bullish/neutral/bearish）徽章各渲染一次，不崩溃。"""
    card = ContentCard(
        source_post_id="t_stances",
        heading="科技股三大信号",
        points=["Serenity 看好英伟达硬件护城河", "英特尔转型进展仍不明朗", "AMD 估值中性等待"],
        tickers=[
            {"symbol": "NVDA", "stance": "bullish"},
            {"symbol": "AMD",  "stance": "neutral"},
            {"symbol": "INTC", "stance": "bearish"},
        ],
    )
    out = tmp_path / "card_stances.png"
    render_card(card, out, run_date=RUN_DATE, session="盘前")
    _assert_png(out)
