"""
xhs_renderer.py: 渲染小红书三类图片卡片（1080×1440 PNG）。

手写笔记本风格：米白底 + 点阵格 + 左侧红页边线 + 霞鹜文楷字体。

公开接口:
    render_cover(plan, out_path, run_date=None)  -> Path
    render_card(card, out_path, run_date=None, session="")  -> Path
    render_tweet_cards(card, out_dir, base_name, run_date=None, session="")  -> List[Path]
    render_tail(out_path, blogger=None)  -> Path

运行 `python xhs_renderer.py --demo` 可生成全套示例图。
"""
from __future__ import annotations

import argparse
import math
import os
import random
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from xhs_composer import DISCLAIMER, ContentCard, PostPlan

# ── 配色 ─────────────────────────────────────────────────────────────────────
BG          = (252, 250, 244, 255)
ACCENT      = (220,  38,  38, 255)
INK         = ( 23,  23,  23, 255)
SUBINK      = (110, 110, 110, 255)
DOT_COLOR   = (180, 178, 170, 100)
MARGIN_LINE = (220,  60,  60,  80)
TAPE_COLOR  = (255, 240, 180, 160)
SHADOW      = (  0,   0,   0,  40)

_SESSION_HIGHLIGHT: Dict[str, Tuple[int, int, int, int]] = {
    "盘前": (255, 245,  80, 160),
    "盘后": (255, 165,  50, 160),
    "周报": ( 90, 210, 110, 160),
}
_DEFAULT_HIGHLIGHT = (255, 245, 80, 160)

# A股惯例：红多（bullish）绿空（bearish）；neutral 蓝灰
_TICKER_COLORS: Dict[str, Dict] = {
    "bullish": {
        "bg":     (255, 235, 232, 255),
        "fg":     (178,  60,  50, 255),
        "border": (200, 100,  90, 255),
    },
    "bearish": {
        "bg":     (232, 243, 233, 255),
        "fg":     ( 56, 120,  70, 255),
        "border": (100, 160, 110, 255),
    },
    "neutral": {
        "bg":     (240, 244, 248, 255),
        "fg":     ( 80, 100, 120, 255),
        "border": (150, 165, 180, 255),
    },
}

# ── 尺寸 ─────────────────────────────────────────────────────────────────────
W, H        = 1080, 1440
MARGIN      = 80
CONTENT_X   = 160
DOT_SPACING = 56
DOT_R       = 2
MARGIN_X    = 140

# ── render_tweet_cards 常量 ───────────────────────────────────────────────────
MAX_CARDS_HARD: int = 16              # 单条推文分页上限，可被测试 monkeypatch
_FONT_SIZE_STEPS: List[int] = [52, 48, 44, 40]
_TEXT_LH_MAP: Dict[int, int] = {52: 74, 48: 69, 44: 63, 40: 57}
_TC_CONTENT_TOP: int = 120            # 内容区起始 y（顶部标签下方）
_TC_FOOTER_TOP: int = H - 90          # 页脚分隔线 y = 1350
_TC_TOTAL_H: int = _TC_FOOTER_TOP - _TC_CONTENT_TOP  # 1230
_TC_CONT_OVERHEAD: int = 80           # 续卡顶部小标题占用高度

# ── 字体候选 ─────────────────────────────────────────────────────────────────
_REPO_FONTS = Path(__file__).parent / "fonts"

_BOLD_CANDIDATES: List[str] = [
    os.getenv("XHS_FONT_BOLD", ""),
    str(_REPO_FONTS / "LXGWWenKai-Medium.ttf"),
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
]
_REGULAR_CANDIDATES: List[str] = [
    os.getenv("XHS_FONT_REGULAR", ""),
    str(_REPO_FONTS / "LXGWWenKai-Regular.ttf"),
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/msyh.ttc",
]

# ── Emoji 剥离 ────────────────────────────────────────────────────────────────
_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF"
    r"\U00002190-\U000021FF︀-️]"
)


def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


# ── ticker 工具 ───────────────────────────────────────────────────────────────
_TICKER_RE = re.compile(r"\$([A-Z]{1,5})")


def _extract_tickers(text: str) -> List[str]:
    return list(dict.fromkeys(_TICKER_RE.findall(text)))


def _filter_display_tickers(heading: str, tickers: List[dict]) -> List[dict]:
    """Remove tickers whose $SYMBOL already appears in heading text (redundant)."""
    in_heading = set(_extract_tickers(heading))
    return [t for t in tickers if t.get("symbol", "") not in in_heading]


# ── 字体加载 ─────────────────────────────────────────────────────────────────
_font_cache: Dict = {}
_bold_path: Optional[str] = None
_reg_path: Optional[str] = None


def _find_font(candidates: List[str]) -> Optional[str]:
    for p in candidates:
        if p and Path(p).exists():
            return p
    return None


def _resolve_paths() -> None:
    global _bold_path, _reg_path
    if _bold_path is None:
        _bold_path = _find_font(_BOLD_CANDIDATES)
    if _reg_path is None:
        _reg_path = _find_font(_REGULAR_CANDIDATES)


def _pf(path: Optional[str], size: int):
    from PIL import ImageFont
    key = (path, size)
    if key not in _font_cache:
        f = None
        if path:
            try:
                f = ImageFont.truetype(path, size)
            except Exception:
                pass
        _font_cache[key] = f or ImageFont.load_default()
    return _font_cache[key]


def _bold(size: int):
    _resolve_paths()
    return _pf(_bold_path, size)


def _reg(size: int):
    _resolve_paths()
    return _pf(_reg_path, size)


# ── 画布 & 背景 ───────────────────────────────────────────────────────────────

def _canvas():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(img)
    return img, draw


def _draw_dot_grid(draw) -> None:
    for x in range(0, W + DOT_SPACING, DOT_SPACING):
        for y in range(0, H + DOT_SPACING, DOT_SPACING):
            draw.ellipse(
                [x - DOT_R, y - DOT_R, x + DOT_R, y + DOT_R],
                fill=DOT_COLOR,
            )


def _draw_margin_line(draw) -> None:
    draw.rectangle([MARGIN_X, 0, MARGIN_X + 3, H], fill=MARGIN_LINE)


def _finalize(img) -> object:
    from PIL import Image
    bg = Image.new("RGB", img.size, (252, 250, 244))
    bg.paste(img, mask=img.split()[3])
    return bg


# ── 文字工具 ─────────────────────────────────────────────────────────────────

def wrap_mixed_text(draw, text: str, font, max_w: int) -> List[str]:
    """Universal word-aware wrap: English words and numbers stay atomic; CJK wraps by char.

    Used for all user-facing text (headlines, sublines, headings, points, quotes).
    Replaces the old character-level _wrap everywhere except DISCLAIMER in tail.
    """
    tokens: List[str] = []
    cur = ""
    for ch in text:
        if ch == "\n":
            if cur:
                tokens.append(cur)
                cur = ""
            tokens.append("\n")
        elif ord(ch) > 0x2E7F:   # CJK / fullwidth — wrap by char
            if cur:
                tokens.append(cur)
                cur = ""
            tokens.append(ch)
        elif ch == " ":
            if cur:
                tokens.append(cur)
                cur = ""
            tokens.append(" ")
        else:                     # ASCII letter/digit/punct — keep with adjacent ASCII
            cur += ch
    if cur:
        tokens.append(cur)

    lines: List[str] = []
    line = ""
    for tok in tokens:
        if tok == "\n":
            lines.append(line.rstrip())
            line = ""
            continue
        candidate = line + tok
        if draw.textlength(candidate.rstrip(), font=font) <= max_w:
            line = candidate
        else:
            stripped = line.rstrip()
            if stripped:
                lines.append(stripped)
            line = tok.lstrip() if tok != " " else ""
    stripped = line.rstrip()
    if stripped:
        lines.append(stripped)
    return lines or [""]


def _wrap(draw, text: str, font, max_w: int) -> List[str]:
    """CJK-only greedy char wrap. Used only for DISCLAIMER in tail."""
    lines: List[str] = []
    cur = ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
        elif draw.textlength(cur + ch, font=font) <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines or [""]


def _balanced_wrap(draw, text: str, font, max_w: int) -> List[str]:
    """均分断行。含英文/数字时直接用 wrap_mixed_text（字符切分会破坏单词）；
    纯中文时在 wrap_mixed_text 结果基础上按字符数均分。"""
    greedy = wrap_mixed_text(draw, text, font, max_w)
    if len(greedy) <= 1:
        return greedy
    # If text contains ASCII (English/numbers), balanced char-split would break words — skip
    if re.search(r"[A-Za-z0-9]", text):
        return greedy
    total = len(text.replace("\n", ""))
    per = math.ceil(total / len(greedy))
    result: List[str] = []
    remaining = text
    while remaining:
        result.append(remaining[:per])
        remaining = remaining[per:]
    for ln in result:
        if draw.textlength(ln, font=font) > max_w:
            return greedy
    return result


def _text_block(draw, lines: List[str], font, x: int, y: int, fill, lh: int) -> int:
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += lh
    return y


def _text_height(lines: List[str], lh: int) -> int:
    return lh * len(lines)


# ── 装饰元素 ─────────────────────────────────────────────────────────────────

def _draw_tape(img, cx: int, cy: int, width: int = 220, height: int = 42, angle: float = -3.5) -> None:
    from PIL import Image, ImageDraw
    tape = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    td = ImageDraw.Draw(tape)
    td.rectangle([0, 0, width - 1, height - 1], fill=TAPE_COLOR)
    rotated = tape.rotate(angle, expand=True)
    x = cx - rotated.width // 2
    y = cy - rotated.height // 2
    img.alpha_composite(rotated, (max(0, x), max(0, y)))


def _draw_highlight(img, draw, x: int, y: int, text_w: int, lh: int, session: str) -> None:
    from PIL import Image, ImageDraw
    color = _SESSION_HIGHLIGHT.get(session, _DEFAULT_HIGHLIGHT)
    strip_h = int(lh * 0.55)
    strip_y = y + lh - strip_h + 4
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([x - 4, strip_y, x + text_w + 4, strip_y + strip_h], fill=color)
    img.alpha_composite(overlay)


def _draw_checkmark(draw, cx: int, cy: int, size: int = 18) -> None:
    p1 = (cx,              cy + size // 2)
    p2 = (cx + size // 3,  cy + size)
    p3 = (cx + size,       cy)
    draw.line([p1, p2], fill=ACCENT, width=3)
    draw.line([p2, p3], fill=ACCENT, width=3)


def _draw_ticker_badge(draw, symbol: str, stance: str, x: int, y: int) -> int:
    """Draw a rounded-rect ticker badge; returns right-edge x."""
    colors = _TICKER_COLORS.get(stance, _TICKER_COLORS["neutral"])
    f = _bold(28)
    tw = int(draw.textlength(symbol, font=f))
    pad_x, pad_y = 14, 6
    bw = tw + pad_x * 2
    bh = 38
    x0, y0, x1, y1 = x, y, x + bw, y + bh
    draw.rounded_rectangle(
        [x0, y0, x1, y1], radius=8,
        fill=colors["bg"], outline=colors["border"], width=2,
    )
    draw.text((x0 + pad_x, y0 + pad_y), symbol, font=f, fill=colors["fg"])
    return x1 + 10


def _draw_quote_note(img, draw, quote: str, x: int, y: int, max_w: int) -> int:
    """Draw a sticky-note quote box with word-aware wrapping and adaptive font size."""
    from PIL import Image, ImageDraw

    pad = 36
    note_w = max_w
    # text starts after left pad + opening quote mark (approx 28px)
    text_x_off = pad + 28
    text_usable = note_w - pad - text_x_off

    # Adaptive font: 32pt first, drop to 26pt if > 5 lines
    f = _reg(32)
    lh = int(32 * 1.55)
    lines = wrap_mixed_text(draw, quote, f, text_usable)
    if len(lines) > 5:
        f = _reg(26)
        lh = int(26 * 1.55)
        lines = wrap_mixed_text(draw, quote, f, text_usable)

    # Hard cap at 6 lines + ellipsis
    if len(lines) > 6:
        lines = lines[:6]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=f) > text_usable:
            last = last[:-1]
        lines[-1] = (last or "") + "…"

    note_h = lh * len(lines) + pad * 2

    # Shadow layer
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    sd.rectangle([x + 6, y + 6, x + note_w + 6, y + note_h + 6], fill=SHADOW)
    img.alpha_composite(sh)

    # Note background
    nl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    nd = ImageDraw.Draw(nl)
    nd.rectangle([x, y, x + note_w, y + note_h], fill=(255, 253, 200, 220))
    img.alpha_composite(nl)

    # Opening quote mark
    draw.text((x + pad, y + pad - 8), "“", font=_reg(48), fill=(150, 140, 100, 255))

    # Text
    ty = y + pad
    for line in lines:
        draw.text((x + text_x_off, ty), line, font=f, fill=(80, 70, 50, 255))
        ty += lh

    return y + note_h + 16


# ── 封面 ──────────────────────────────────────────────────────────────────────

def render_cover(
    plan: PostPlan,
    out_path: Path,
    run_date: Optional[date] = None,
) -> Path:
    if run_date is None:
        run_date = date.today()

    img, draw = _canvas()
    _draw_dot_grid(draw)
    _draw_margin_line(draw)

    usable = W - CONTENT_X - MARGIN

    # 账号 + 日期标签
    label = _strip_emoji(f"白毛股神  {run_date.month}.{run_date.day}  {plan.session}")
    draw.text((CONTENT_X, 56), label, font=_reg(34), fill=SUBINK)

    # 计算 headline 字号与行数
    headline = _strip_emoji(plan.cover_headline)
    f_head = _bold(88)
    head_lines = _balanced_wrap(draw, headline, f_head, usable)
    if len(head_lines) > 2:
        f_head = _bold(72)
        head_lines = _balanced_wrap(draw, headline, f_head, usable)
    head_lh = int(f_head.size * 1.3)

    f_sub = _reg(52)
    sub_lines = _balanced_wrap(draw, _strip_emoji(plan.cover_subline), f_sub, usable)
    sub_lh = 72
    GAP = 28   # 头副标题间距（收紧 30%，原 40px）

    block_h = _text_height(head_lines, head_lh) + GAP + _text_height(sub_lines, sub_lh)
    y = (H - block_h) // 2 - 60   # 略微偏上

    # 胶带：垂直中心线对齐标题第一行顶边（一半压字一半在纸上）
    # 水平随机偏移 ±60px，旋转 3-5°
    content_cx = (CONTENT_X + W - MARGIN) // 2
    tape_cx = content_cx + random.randint(-60, 60)
    tape_angle = random.uniform(3.0, 5.0) * random.choice([-1, 1])
    _draw_tape(img, cx=tape_cx, cy=y, angle=tape_angle)

    # heading highlight（最后一行）
    last_line = head_lines[-1]
    last_w = int(draw.textlength(last_line, font=f_head))
    _draw_highlight(img, draw, CONTENT_X, y + head_lh * (len(head_lines) - 1), last_w, head_lh, plan.session)

    y = _text_block(draw, head_lines, f_head, CONTENT_X, y, INK, head_lh)
    y += GAP
    _text_block(draw, sub_lines, f_sub, CONTENT_X, y, SUBINK, sub_lh)

    # 底部署名
    f_foot = _reg(28)
    foot_y = H - 110
    draw.line([CONTENT_X, foot_y - 20, W - MARGIN, foot_y - 20], fill=(200, 198, 192, 255), width=1)
    draw.text((CONTENT_X, foot_y),      "白毛股神 / Serenity @aleabitoreddit", font=f_foot, fill=SUBINK)
    draw.text((CONTENT_X, foot_y + 42), "仅为个人解读  ·  非投资建议",          font=f_foot, fill=SUBINK)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _finalize(img).save(str(out_path), "PNG")
    return out_path


# ── 内容卡 ────────────────────────────────────────────────────────────────────

def render_card(
    card: ContentCard,
    out_path: Path,
    run_date: Optional[date] = None,
    session: str = "",
) -> Path:
    if run_date is None:
        run_date = date.today()

    img, draw = _canvas()
    _draw_dot_grid(draw)
    _draw_margin_line(draw)

    usable = W - CONTENT_X - MARGIN

    # 右上角：会话 + 日期
    f_tag = _reg(30)
    tag = f"{session}  {run_date.month}.{run_date.day}" if session else f"{run_date.month}.{run_date.day}"
    tw = int(draw.textlength(tag, font=f_tag))
    draw.text((W - MARGIN - tw, 36), tag, font=f_tag, fill=SUBINK)

    if card.part > 1:
        part_tag = f"第 {card.part} 张"
        ptw = int(draw.textlength(part_tag, font=f_tag))
        draw.text((W - MARGIN - ptw, 74), part_tag, font=f_tag, fill=SUBINK)

    # ── 预计算内容块高度（用于垂直居中）───────────────────────────────────────
    heading_text = _strip_emoji(card.heading)
    f_head = _bold(58)
    head_lines = _balanced_wrap(draw, heading_text, f_head, usable)
    if len(head_lines) > 3:
        f_head = _bold(52)
        head_lines = _balanced_wrap(draw, heading_text, f_head, usable)
    head_lh = int(f_head.size * 1.35)
    # Font sizes used in demo cards:
    # - 2pt card ("NVDA 供给缺口短期难解", fits 1 line at 58pt): heading=58pt, points=52pt
    # - 4pt card ("美联储内部分歧加剧走势难判", fits 1 line at 58pt): heading=58pt, points=52pt
    # The 52pt heading fallback fires only for headings that would exceed 3 wrapped lines
    # (requires ~43+ CJK chars at 58pt on 840px usable width — far beyond the ≤14-char spec).

    f_pt = _reg(52)
    pt_lh = 74
    pt_usable = usable - 52   # 52 = checkmark width + indent

    pt_block_h = 0
    for point in card.points:
        pt_lines = wrap_mixed_text(draw, _strip_emoji(point), f_pt, pt_usable)
        pt_block_h += pt_lh * len(pt_lines) + 28

    display_tickers = _filter_display_tickers(card.heading, card.tickers)
    ticker_row_h = 52 if display_tickers else 0

    # Quote height estimate (for block centering)
    quote_h = 0
    if card.quote:
        pad = 36
        text_x_off = pad + 28
        q_usable = usable - pad - text_x_off
        f_q_est = _reg(32)
        q_lh_est = int(32 * 1.55)
        q_est = wrap_mixed_text(draw, card.quote, f_q_est, q_usable)
        if len(q_est) > 5:
            q_lh_est = int(26 * 1.55)
        n_q = min(len(q_est), 6)
        quote_h = q_lh_est * n_q + pad * 2 + 16 + 20

    sep_h = 36
    block_h = (
        _text_height(head_lines, head_lh) + 32 +
        sep_h + ticker_row_h +
        pt_block_h + quote_h
    )
    y = max(100, (H - block_h) // 2 - 40)

    # ── Heading ──────────────────────────────────────────────────────────────
    last_line = head_lines[-1]
    last_w = int(draw.textlength(last_line, font=f_head))
    _draw_highlight(img, draw, CONTENT_X, y + head_lh * (len(head_lines) - 1), last_w, head_lh, session)
    y = _text_block(draw, head_lines, f_head, CONTENT_X, y, INK, head_lh)
    y += 32

    # 分隔线
    draw.line([CONTENT_X, y, W - MARGIN, y], fill=(200, 196, 188, 255), width=1)
    y += sep_h

    # ── Ticker badges（分隔线下、要点区上方）────────────────────────────────
    if display_tickers:
        tx = CONTENT_X
        for t in display_tickers:
            tx = _draw_ticker_badge(draw, f"${t['symbol']}", t.get("stance", "neutral"), tx, y)
        y += ticker_row_h

    # ── 要点列表 ─────────────────────────────────────────────────────────────
    for point in card.points:
        pt_lines = wrap_mixed_text(draw, _strip_emoji(point), f_pt, pt_usable)
        cy = y + pt_lh // 2 - 4
        _draw_checkmark(draw, CONTENT_X, cy - 9, size=20)
        _text_block(draw, pt_lines, f_pt, CONTENT_X + 52, y, INK, pt_lh)
        y += pt_lh * len(pt_lines) + 28

    # ── Quote 便利贴 ─────────────────────────────────────────────────────────
    if card.quote:
        y += 16
        y = _draw_quote_note(img, draw, _strip_emoji(card.quote), CONTENT_X, y, usable)

    # 底部署名
    f_foot = _reg(26)
    foot_y = H - 72
    draw.line([CONTENT_X, foot_y - 18, W - MARGIN, foot_y - 18], fill=(200, 196, 188, 255), width=1)
    draw.text((CONTENT_X, foot_y), "白毛股神 / Serenity @aleabitoreddit", font=f_foot, fill=SUBINK)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _finalize(img).save(str(out_path), "PNG")
    return out_path


# ── 长推分页辅助 ─────────────────────────────────────────────────────────────

def _measure_quote_h(draw, text: str, usable: int) -> int:
    """返回 _draw_quote_note 渲染 text 后 y 坐标的增量（包含底部 16px 间距）。"""
    pad = 36
    text_usable = usable - pad - (pad + 28)
    lh = int(32 * 1.55)
    lines = wrap_mixed_text(draw, _reg(32), text, text_usable) if False else \
            wrap_mixed_text(draw, text, _reg(32), text_usable)
    if len(lines) > 5:
        lh = int(26 * 1.55)
        lines = wrap_mixed_text(draw, text, _reg(26), text_usable)
    n = min(len(lines), 6)
    return lh * n + pad * 2 + 16


def render_tweet_cards(
    card: "ContentCard",
    out_dir: Path,
    base_name: str,
    run_date: Optional[date] = None,
    session: str = "",
) -> List[Path]:
    """将一条推文的完整内容（full_original + full_translation）渲染为 1 至多张 PNG。

    第 1 张：heading + 分隔线 + ticker 徽章 + full_original 便利贴 + full_translation 流式文本。
    续张：顶部小标题引用 + 「第 N 张」角标 + 续文本；不再显示 ticker 徽章。
    超过 MAX_CARDS_HARD 时截断并在末页追加省略说明。
    """
    from PIL import Image as _Image, ImageDraw as _ImageDraw  # noqa: F401

    if run_date is None:
        run_date = date.today()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 测量阶段（不写图）──────────────────────────────────────────────────
    img_m = _Image.new("RGBA", (W, H), BG)
    draw_m = _ImageDraw.Draw(img_m)
    usable = W - CONTENT_X - MARGIN

    # Heading
    heading_text = _strip_emoji(card.heading)
    f_head = _bold(58)
    head_lines = _balanced_wrap(draw_m, heading_text, f_head, usable)
    if len(head_lines) > 3:
        f_head = _bold(52)
        head_lines = _balanced_wrap(draw_m, heading_text, f_head, usable)
    head_lh = int(f_head.size * 1.35)

    display_tickers = _filter_display_tickers(card.heading, card.tickers)

    # 第 1 页固定开销：heading + gap + sep + tickers
    p1_overhead = (
        _text_height(head_lines, head_lh) + 32
        + 36
        + (52 if display_tickers else 0)
    )
    orig_text = _strip_emoji(card.full_original) if card.full_original else ""
    if orig_text:
        p1_overhead += _measure_quote_h(draw_m, orig_text, usable) + 20

    p1_avail = _TC_TOTAL_H - p1_overhead
    pc_avail = _TC_TOTAL_H - _TC_CONT_OVERHEAD

    full_trans = _strip_emoji(card.full_translation) if card.full_translation else ""

    # ── 选字号并分页 ────────────────────────────────────────────────────────
    result_lines: List[List[str]] = []
    chosen_fs = 40
    chosen_lh = _TEXT_LH_MAP[40]

    for fs in _FONT_SIZE_STEPS:
        lh = _TEXT_LH_MAP[fs]
        all_lines = wrap_mixed_text(draw_m, full_trans, _reg(fs), usable) if full_trans else []
        lpp1 = max(0, p1_avail // lh)
        lppc = max(1, pc_avail // lh)

        pages: List[List[str]] = []
        remaining = list(all_lines)
        pages.append(remaining[:lpp1])
        remaining = remaining[lpp1:]
        while remaining:
            pages.append(remaining[:lppc])
            remaining = remaining[lppc:]
        if not pages:
            pages = [[]]

        if len(pages) <= MAX_CARDS_HARD:
            result_lines = pages
            chosen_fs = fs
            chosen_lh = lh
            break
    else:
        # 最小字号仍超出上限 — 强制截断
        lh = _TEXT_LH_MAP[40]
        all_lines = wrap_mixed_text(draw_m, full_trans, _reg(40), usable) if full_trans else []
        lpp1 = max(0, p1_avail // lh)
        lppc = max(1, pc_avail // lh)
        pages = []
        remaining = list(all_lines)
        pages.append(remaining[:lpp1])
        remaining = remaining[lpp1:]
        while remaining and len(pages) < MAX_CARDS_HARD:
            pages.append(remaining[:lppc])
            remaining = remaining[lppc:]
        if remaining:
            pages[-1] = list(pages[-1]) + ["……（内容已截断）"]
        if not pages:
            pages = [[]]
        result_lines = pages
        chosen_fs = 40
        chosen_lh = lh

    f_txt = _reg(chosen_fs)
    lh = chosen_lh
    n_pages = len(result_lines)
    paths: List[Path] = []

    # ── 逐页渲染 ────────────────────────────────────────────────────────────
    for page_idx, page_text_lines in enumerate(result_lines):
        page_no = page_idx + 1
        suffix = f"_tc{page_no:02d}" if n_pages > 1 else "_tc"
        out_path = out_dir / f"{base_name}{suffix}.png"

        img, draw = _canvas()
        _draw_dot_grid(draw)
        _draw_margin_line(draw)

        # 右上角标签
        f_tag = _reg(30)
        tag = f"{session}  {run_date.month}.{run_date.day}" if session else f"{run_date.month}.{run_date.day}"
        tw = int(draw.textlength(tag, font=f_tag))
        draw.text((W - MARGIN - tw, 36), tag, font=f_tag, fill=SUBINK)

        if page_no > 1:
            part_tag = f"第 {page_no} 张"
            ptw = int(draw.textlength(part_tag, font=f_tag))
            draw.text((W - MARGIN - ptw, 74), part_tag, font=f_tag, fill=SUBINK)

        y = _TC_CONTENT_TOP

        if page_no == 1:
            # Heading + highlight
            last_line = head_lines[-1]
            last_w = int(draw.textlength(last_line, font=f_head))
            _draw_highlight(img, draw, CONTENT_X, y + head_lh * (len(head_lines) - 1), last_w, head_lh, session)
            y = _text_block(draw, head_lines, f_head, CONTENT_X, y, INK, head_lh)
            y += 32

            draw.line([CONTENT_X, y, W - MARGIN, y], fill=(200, 196, 188, 255), width=1)
            y += 36

            if display_tickers:
                tx = CONTENT_X
                for t in display_tickers:
                    tx = _draw_ticker_badge(draw, f"${t['symbol']}", t.get("stance", "neutral"), tx, y)
                y += 52

            if orig_text:
                y = _draw_quote_note(img, draw, orig_text, CONTENT_X, y, usable)
                y += 20
        else:
            # 续卡：小字 heading 引用（SUBINK，截断到单行）
            f_cont = _bold(42)
            cont_label = heading_text
            while cont_label and draw.textlength(cont_label + "…", font=f_cont) > usable - 80:
                cont_label = cont_label[:-1]
            if cont_label != heading_text:
                cont_label = cont_label + "…"
            draw.text((CONTENT_X, y), cont_label, font=f_cont, fill=SUBINK)
            y += _TC_CONT_OVERHEAD

        # 流式文本
        for line in page_text_lines:
            if y + lh > _TC_FOOTER_TOP:
                break
            draw.text((CONTENT_X, y), line, font=f_txt, fill=INK)
            y += lh

        # 页脚
        f_foot = _reg(26)
        foot_y = H - 72
        draw.line([CONTENT_X, foot_y - 18, W - MARGIN, foot_y - 18], fill=(200, 196, 188, 255), width=1)
        draw.text((CONTENT_X, foot_y), "白毛股神 / Serenity @aleabitoreddit", font=f_foot, fill=SUBINK)

        _finalize(img).save(str(out_path), "PNG")
        paths.append(out_path)

    return paths


# ── 尾页 ──────────────────────────────────────────────────────────────────────

def render_tail(
    out_path: Path,
    blogger: Optional[dict] = None,
) -> Path:
    if blogger is None:
        from blogger_config import TRACKED_BLOGGERS
        blogger = TRACKED_BLOGGERS[0]

    cn_name = blogger.get("cn_name", "白毛股神")
    handle  = blogger.get("handle", "@aleabitoreddit")
    display = blogger.get("display_name", "Serenity")

    img, draw = _canvas()
    _draw_dot_grid(draw)
    _draw_margin_line(draw)

    usable = W - CONTENT_X - MARGIN

    # Pre-compute heights for vertical centering
    f_thanks   = _reg(32)
    f_cn       = _bold(80)
    f_handle_f = _reg(36)
    f_disc_hdr = _bold(42)
    f_disc     = _reg(36)
    f_cta1     = _bold(52)
    f_cta2     = _reg(46)
    disc_lh    = 56
    disc_lines = _wrap(draw, DISCLAIMER, f_disc, usable)

    THANKS_H    = 40 + 20
    CNNAME_H    = 96 + 16
    HANDLE_H    = 43 + 60
    SEP1_H      = 1 + 40
    DISC_HDR_H  = 50 + 10
    DISC_TEXT_H = disc_lh * len(disc_lines) + 44
    SEP2_H      = 1 + 52
    CTA1_H      = 62 + 18
    CTA2_H      = 55

    total_h = (THANKS_H + CNNAME_H + HANDLE_H + SEP1_H +
               DISC_HDR_H + DISC_TEXT_H + SEP2_H + CTA1_H + CTA2_H)
    y = max(60, (H - total_h) // 2)

    draw.text((CONTENT_X, y), "感谢追踪  ·  内容来源", font=f_thanks, fill=SUBINK)
    y += THANKS_H

    draw.text((CONTENT_X, y), cn_name, font=f_cn, fill=INK)
    y += CNNAME_H

    draw.text((CONTENT_X, y), f"{display}  {handle}", font=f_handle_f, fill=SUBINK)
    y += HANDLE_H

    draw.line([CONTENT_X, y, W - MARGIN, y], fill=(200, 196, 188, 255), width=1)
    y += SEP1_H

    draw.text((CONTENT_X, y), "免责声明", font=f_disc_hdr, fill=ACCENT)
    y += DISC_HDR_H

    y = _text_block(draw, disc_lines, f_disc, CONTENT_X, y, INK, disc_lh)
    y += 44

    draw.line([CONTENT_X, y, W - MARGIN, y], fill=(200, 196, 188, 255), width=1)
    y += SEP2_H

    draw.text((CONTENT_X, y), "想看哪位博主？", font=f_cta1, fill=INK)
    y += CTA1_H

    draw.text((CONTENT_X, y), "评论区告诉我", font=f_cta2, fill=ACCENT)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _finalize(img).save(str(out_path), "PNG")
    return out_path


# ── Demo ──────────────────────────────────────────────────────────────────────

def _run_demo() -> None:
    demo_dir = Path(os.getenv("XHS_OUTPUT_DIR", "xhs_output")) / "_demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    demo_date = date(2026, 6, 10)

    blogger = {"handle": "@aleabitoreddit", "display_name": "Serenity", "cn_name": "白毛股神"}

    # 01 封面
    plan = PostPlan(
        title="白毛股神6.10盘前｜英伟达白毛还在硬刚",
        cover_headline="英伟达白毛还在硬刚",
        cover_subline="三大理由说明供给短缺远未结束",
        cards=[],
        caption="demo",
        session="盘前",
    )
    p = render_cover(plan, demo_dir / "01_cover.png", run_date=demo_date)
    print(f"封面          → {p}")

    # 02 2 要点卡（含 bullish ticker badge）
    card2pt = ContentCard(
        source_post_id="d1",
        heading="NVDA 供给缺口短期难解",
        points=["数据中心需求持续加速增长", "台积电扩产计划明显滞后"],
        tickers=[{"symbol": "NVDA", "stance": "bullish"}],
    )
    p = render_card(card2pt, demo_dir / "02_card_2pt.png", run_date=demo_date, session="盘前")
    print(f"2要点卡       → {p}")

    # 03 4 要点卡（基准，不改）
    card4pt = ContentCard(
        source_post_id="d2",
        heading="美联储内部分歧加剧走势难判",
        points=[
            "鹰派委员倾向年内仅降息一次",
            "鸽派认为就业数据已显示经济降温",
            "市场定价介于一次与两次降息之间",
            "Serenity 认为短期内方向难以明确判断",
        ],
    )
    p = render_card(card4pt, demo_dir / "03_card_4pt.png", run_date=demo_date, session="盘后")
    print(f"4要点卡(基准)  → {p}")

    # 04 超长 quote 卡
    card_lq = ContentCard(
        source_post_id="d_lq",
        heading="Serenity 对时间窗口的判断",
        points=["供给缺口预计持续至2027年上半年", "台积电扩产爬坡需18至24个月"],
        quote="I believe the supply gap will persist well beyond 2027, and frankly the market hasn't fully priced this in yet.",
    )
    p = render_card(card_lq, demo_dir / "04_card_longquote.png", run_date=demo_date, session="盘前")
    print(f"超长quote卡   → {p}")

    # 05 三种 stance 徽章卡
    card_stances = ContentCard(
        source_post_id="d_stances",
        heading="科技股三大信号",
        points=[
            "Serenity 看好英伟达硬件护城河",
            "英特尔转型进展仍不明朗",
            "AMD 估值中性等待机会",
        ],
        tickers=[
            {"symbol": "NVDA", "stance": "bullish"},
            {"symbol": "AMD",  "stance": "neutral"},
            {"symbol": "INTC", "stance": "bearish"},
        ],
    )
    p = render_card(card_stances, demo_dir / "05_card_stances.png", run_date=demo_date, session="盘前")
    print(f"三stance徽章  → {p}")

    # 06 尾页
    p = render_tail(demo_dir / "06_tail.png", blogger=blogger)
    print(f"尾页          → {p}")

    print(f"\n全套示例图已生成到:\n  {demo_dir.resolve()}")


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="xhs_renderer 工具")
    parser.add_argument("--demo", action="store_true", help="渲染全套示例图到 xhs_output/_demo/")
    args = parser.parse_args()
    if args.demo:
        _run_demo()
    else:
        parser.print_help()
