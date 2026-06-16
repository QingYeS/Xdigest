"""
xhs_preview.py: 生成单文件静态预览页 HTML。
零外部依赖，双击可在浏览器打开，图片相对路径，JS 内联。

公开接口:
    generate_preview(rendered_plans, posts_by_id, output_path, run_date, session) -> Path

运行 `python xhs_preview.py --mock` 生成示例预览页供验收。
"""
from __future__ import annotations

import argparse
import html
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from xhs_composer import BANNED_PHRASES, DISCLAIMER, ContentCard, PostPlan, scan_banned


@dataclass
class RenderedPlan:
    """PostPlan 与已渲染的图片路径捆绑。"""
    plan: PostPlan
    cover_path: Path
    card_paths: List[Path]   # 按 plan.cards 顺序，一张卡一张图
    tail_path: Path


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _e(text: str) -> str:
    return html.escape(str(text), quote=True)


def _rel(img_path: Path, html_dir: Path) -> str:
    """html_dir 到 img_path 的相对 URL，正斜杠。"""
    return os.path.relpath(img_path, html_dir).replace("\\", "/")


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue",
                 "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #ebebeb;
    color: #1a1a1a;
    line-height: 1.6;
    font-size: 14px;
}
.page-header {
    background: #fff;
    border-bottom: 2px solid #dc2626;
    padding: 18px 40px;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
    display: flex;
    align-items: baseline;
    gap: 16px;
}
.page-header h1 { font-size: 17px; font-weight: 700; color: #111; white-space: nowrap; }
.page-header .meta { font-size: 12px; color: #888; }
.content { padding: 24px 40px 60px; max-width: 1280px; margin: 0 auto; }

/* ─ timing notice ─ */
.timing-notice {
    display: flex; align-items: center; gap: 8px;
    background: #fffbeb; border: 1px solid #fcd34d;
    border-radius: 8px; padding: 10px 16px;
    font-size: 13px; color: #92400e;
    margin-bottom: 12px;
}

/* ─ plan block ─ */
.plan-block {
    background: #fff;
    border: 1px solid #d9d9d9;
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 28px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}
.plan-block.needs-edit {
    border: 2px solid #dc2626;
    box-shadow: 0 0 0 3px rgba(220,38,38,0.08), 0 2px 8px rgba(0,0,0,0.05);
}
.warn-banner {
    background: #fef2f2;
    border-bottom: 1px solid #fecaca;
    padding: 10px 20px;
    font-size: 13px;
    color: #991b1b;
    font-weight: 600;
}
.plan-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid #f0f0f0;
    gap: 16px;
}
.plan-title { font-size: 15px; font-weight: 700; color: #111; line-height: 1.4; }
.plan-meta { font-size: 12px; color: #888; margin-top: 4px; }
.subline-preview { padding: 8px 20px; border-bottom: 1px solid #f0f0f0; font-size: 12px; color: #555; }
.subline-label { font-weight: 600; color: #888; margin-right: 8px; }
.subline-item { display: inline-block; margin-right: 12px; }
.subline-fallback { color: #dc2626; font-weight: 600; }
.btn-group { display: flex; gap: 8px; flex-shrink: 0; margin-top: 2px; }
.btn-copy {
    background: #f4f4f5; border: 1px solid #d4d4d8;
    border-radius: 6px; padding: 7px 14px;
    font-size: 12px; cursor: pointer;
    color: #52525b; white-space: nowrap;
    transition: background 0.12s, border-color 0.12s;
}
.btn-copy:hover { background: #e4e4e7; }
.btn-copy.copied { background: #dcfce7; border-color: #86efac; color: #166534; }
.copy-src { display: none; }

/* ─ two-column body ─ */
.plan-body {
    display: grid;
    grid-template-columns: 440px 1fr;
    min-height: 200px;
}

/* ─ left: phone ─ */
.phone-panel {
    padding: 24px 20px;
    border-right: 1px solid #f0f0f0;
    background: #f7f7f7;
    display: flex;
    flex-direction: column;
    gap: 16px;
}
.phone-frame {
    width: 390px;
    max-width: 100%;
    border: 3px solid #1a1a1a;
    border-radius: 40px;
    overflow: hidden;
    background: #fff;
    box-shadow: 0 8px 32px rgba(0,0,0,0.18);
}
.phone-notch {
    height: 28px;
    background: #1a1a1a;
    display: flex;
    align-items: center;
    justify-content: center;
}
.phone-notch-pill {
    width: 90px; height: 14px;
    background: #333;
    border-radius: 7px;
}
.phone-images { background: #111; }
.phone-img-wrap img { width: 100%; display: block; }
.img-label {
    background: rgba(0,0,0,0.65);
    color: #bbb;
    font-size: 10px;
    font-family: "SFMono-Regular", Consolas, monospace;
    padding: 3px 10px;
    text-align: center;
}
.phone-note {
    padding: 14px 16px 18px;
    background: #fff;
    border-top: 1px solid #ebebeb;
}
.note-section-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.9px;
    color: #bbb;
    font-weight: 700;
    margin-bottom: 5px;
}
.note-title {
    font-size: 14px;
    font-weight: 700;
    color: #111;
    line-height: 1.5;
    margin-bottom: 12px;
}
.note-body {
    font-size: 12px;
    color: #444;
    white-space: pre-wrap;
    line-height: 1.8;
    max-height: 280px;
    overflow-y: auto;
    border-top: 1px solid #f0f0f0;
    padding-top: 10px;
}

/* ─ right: source tweets ─ */
.source-panel {
    padding: 24px 20px;
    overflow-y: auto;
    max-height: 800px;
}
.source-panel-heading {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.9px;
    color: #999;
    font-weight: 700;
    margin-bottom: 14px;
    padding-bottom: 8px;
    border-bottom: 1px solid #f0f0f0;
}
.tweet-card {
    margin-bottom: 16px;
    border: 1px solid #e5e5e5;
    border-radius: 8px;
    overflow: hidden;
}
.tweet-card-id {
    background: #f9f9f9;
    padding: 5px 12px;
    font-size: 10px;
    color: #aaa;
    font-family: "SFMono-Regular", Consolas, monospace;
    border-bottom: 1px solid #eee;
}
.tweet-original {
    padding: 12px 14px;
    font-size: 13px;
    color: #222;
    line-height: 1.7;
    border-left: 3px solid #d1d5db;
    background: #fafafa;
    white-space: pre-wrap;
}
.tweet-translation {
    padding: 12px 14px;
    background: #f0f4ff;
    border-top: 1px solid #e0e7ff;
}
.tweet-trans-label {
    font-size: 10px;
    font-weight: 700;
    color: #6366f1;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 5px;
}
.tweet-trans-text {
    font-size: 13px;
    color: #374151;
    line-height: 1.7;
    white-space: pre-wrap;
}

/* ─ scan report ─ */
.scan-report {
    background: #fff;
    border: 1px solid #d9d9d9;
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}
.scan-report-header {
    padding: 14px 20px;
    border-bottom: 1px solid #f0f0f0;
    font-size: 14px;
    font-weight: 700;
    display: flex;
    align-items: baseline;
    gap: 10px;
}
.scan-summary { font-size: 12px; font-weight: 400; color: #888; }
.scan-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.scan-table th {
    padding: 8px 16px; text-align: left;
    background: #f9f9f9; border-bottom: 1px solid #eee;
    font-weight: 600; color: #555;
}
.scan-table td { padding: 8px 16px; border-bottom: 1px solid #f5f5f5; }
.scan-table tr:last-child td { border-bottom: none; }
.status-clean { color: #16a34a; font-weight: 500; }
.status-hit   { color: #dc2626; font-weight: 700; }

/* ─ ticker stance badges in source panel ─ */
.stance-row {
    display: flex; flex-wrap: wrap; gap: 6px;
    margin-top: 10px; padding-top: 10px;
    border-top: 1px dashed #e0e7ff;
}
.stance-row-label {
    font-size: 10px; color: #999; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.5px;
    align-self: center;
}
.stance-badge {
    font-size: 11px; padding: 2px 8px;
    border-radius: 10px; font-weight: 600;
}
.stance-bullish { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }
.stance-bearish { background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; }
.stance-neutral  { background: #f0f4ff; color: #3730a3; border: 1px solid #c7d2fe; }
"""

# ── JS ────────────────────────────────────────────────────────────────────────

_JS = """
function copyText(srcId, btn) {
    var text = document.getElementById(srcId).textContent;
    if (navigator && navigator.clipboard) {
        navigator.clipboard.writeText(text).then(function() {
            _showCopied(btn);
        }).catch(function() { _fallback(srcId, btn); });
    } else {
        _fallback(srcId, btn);
    }
}
function _fallback(srcId, btn) {
    var el = document.getElementById(srcId);
    el.style.display = 'block';
    var range = document.createRange();
    range.selectNodeContents(el);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    try { document.execCommand('copy'); _showCopied(btn); } catch(e) {}
    sel.removeAllRanges();
    el.style.display = 'none';
}
function _showCopied(btn) {
    btn.classList.add('copied');
    var orig = btn.textContent;
    btn.textContent = '已复制 ✓';
    setTimeout(function() {
        btn.classList.remove('copied');
        btn.textContent = orig;
    }, 2000);
}
"""


# ── 扫描报告 ──────────────────────────────────────────────────────────────────

def _collect_all_text(rendered_plans: List[RenderedPlan]) -> List[tuple]:
    """返回 [(位置标签, 文本), ...] 用于禁词扫描。"""
    items = []
    for i, rp in enumerate(rendered_plans):
        p = rp.plan
        lbl = f"帖{i+1}"
        items.append((f"{lbl}标题", p.title))
        items.append((f"{lbl}封面标题", p.cover_headline))
        items.append((f"{lbl}封面副标题", p.cover_subline))
        items.append((f"{lbl}正文", p.note))
        for j, card in enumerate(p.cards):
            items.append((f"{lbl}卡{j+1}标题", card.heading))
            for k, pt in enumerate(card.points):
                items.append((f"{lbl}卡{j+1}要点{k+1}", pt))
    return items


def _scan_report_html(rendered_plans: List[RenderedPlan]) -> str:
    all_text = _collect_all_text(rendered_plans)
    hit_map: Dict[str, List[str]] = {}

    for phrase in BANNED_PHRASES:
        hits = [label for label, text in all_text if phrase in text]
        if hits:
            hit_map[phrase] = hits

    n_hits = len(hit_map)
    if n_hits == 0:
        summary = f"共扫描 {len(BANNED_PHRASES)} 个禁词，全部通过"
        summary_cls = "status-clean"
    else:
        summary = f"共扫描 {len(BANNED_PHRASES)} 个禁词，{n_hits} 个命中"
        summary_cls = "status-hit"

    rows = []
    for phrase in BANNED_PHRASES:
        hits = hit_map.get(phrase)
        if hits:
            status_html = f'<span class="status-hit">✗ 命中（{len(hits)} 处）</span>'
            location = _e(", ".join(hits))
        else:
            status_html = '<span class="status-clean">✓ 未命中</span>'
            location = "—"
        rows.append(
            f"<tr>"
            f"<td><code>{_e(phrase)}</code></td>"
            f"<td>{status_html}</td>"
            f"<td>{location}</td>"
            f"</tr>"
        )

    return (
        '<div class="scan-report">'
        '<div class="scan-report-header">禁词扫描报告'
        f'<span class="scan-summary {summary_cls}">{_e(summary)}</span>'
        "</div>"
        '<table class="scan-table">'
        "<thead><tr><th>禁词</th><th>状态</th><th>出现位置</th></tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


# ── 单帖 HTML ─────────────────────────────────────────────────────────────────

def _plan_block_html(
    idx: int,
    rp: RenderedPlan,
    posts_by_id: Dict[str, dict],
    html_dir: Path,
) -> str:
    plan = rp.plan
    parts: List[str] = []

    # ── timing notice（分割帖第 2 帖起）
    if plan.part_no is not None and plan.part_no > 1:
        parts.append(
            '<div class="timing-notice">'
            "⏱️&nbsp; 建议与上一帖间隔 15-30 分钟发布"
            "</div>"
        )

    # ── plan block wrapper
    cls = "plan-block needs-edit" if plan.needs_human_edit else "plan-block"
    parts.append(f'<div class="{cls}">')

    # ── warning banner
    if plan.needs_human_edit:
        parts.append(
            '<div class="warn-banner">'
            "⚠️&nbsp; 此帖含未通过校验内容，请人工检查后再发布"
            "</div>"
        )

    # ── plan header
    part_str = f" &middot; 第 {plan.part_no} 帖" if plan.part_no is not None else ""
    n_cards = len(plan.cards)
    parts.append(
        f'<div class="plan-header">'
        f"<div>"
        f'<div class="plan-title">{_e(plan.title)}</div>'
        f'<div class="plan-meta">{_e(plan.session)}{part_str} &middot; {n_cards} 张内容卡</div>'
        f"</div>"
        f'<div class="btn-group">'
        f'<button class="btn-copy" onclick="copyText(\'t{idx}\', this)">复制标题</button>'
        f'<button class="btn-copy" onclick="copyText(\'c{idx}\', this)">复制正文</button>'
        f"</div>"
        f"</div>"
    )

    # ── hidden copy sources
    parts.append(f'<pre id="t{idx}" class="copy-src">{_e(plan.title)}</pre>')
    parts.append(f'<pre id="c{idx}" class="copy-src">{_e(plan.note)}</pre>')

    # ── subline preview
    subline_lines = (plan.cover_subline or "").splitlines()
    flags = list(getattr(plan, "cover_subline_flags", []))
    if subline_lines:
        subline_items = []
        for i, line in enumerate(subline_lines):
            is_fallback = flags[i] if i < len(flags) else False
            if is_fallback:
                subline_items.append(
                    f'<span class="subline-item subline-fallback" title="heading 含禁词，已降级">⚠ {_e(line)}</span>'
                )
            else:
                subline_items.append(f'<span class="subline-item">{_e(line)}</span>')
        parts.append(
            f'<div class="subline-preview">'
            f'<span class="subline-label">副标题</span>'
            + "".join(subline_items)
            + "</div>"
        )

    # ── two-column body
    parts.append('<div class="plan-body">')

    # ── left: phone mockup
    parts.append(
        '<div class="phone-panel">'
        '<div class="phone-frame">'
        '<div class="phone-notch"><div class="phone-notch-pill"></div></div>'
        '<div class="phone-images">'
    )

    def _img(path: Path, alt: str) -> str:
        rel = _rel(path, html_dir)
        return (
            f'<div class="phone-img-wrap">'
            f'<img src="{_e(rel)}" alt="{_e(alt)}">'
            f'</div>'
            f'<div class="img-label">{_e(path.name)}</div>'
        )

    parts.append(_img(rp.cover_path, "封面"))
    for j, cp in enumerate(rp.card_paths):
        parts.append(_img(cp, f"内容卡 {j + 1}"))
    parts.append(_img(rp.tail_path, "尾页"))

    parts.append("</div>")  # phone-images

    # note section inside phone frame
    parts.append(
        '<div class="phone-note">'
        '<div class="note-section-label">标题</div>'
        f'<div class="note-title">{_e(plan.title)}</div>'
        '<div class="note-section-label">正文</div>'
        f'<div class="note-body">{_e(plan.note)}</div>'
        "</div>"
    )

    parts.append("</div></div>")  # phone-frame, phone-panel

    # ── right: source tweets
    parts.append(
        '<div class="source-panel">'
        '<div class="source-panel-heading">原推对照 &middot; 人工核对</div>'
    )

    seen_ids: List[str] = []
    for card in plan.cards:
        if card.source_post_id not in seen_ids:
            seen_ids.append(card.source_post_id)

    # Build post_id → deduplicated tickers mapping
    ticker_by_post: Dict[str, List[dict]] = {}
    seen_ticker_keys: set = set()
    for card in plan.cards:
        for t in card.tickers:
            key = (card.source_post_id, t.get("symbol", ""))
            if key not in seen_ticker_keys:
                seen_ticker_keys.add(key)
                ticker_by_post.setdefault(card.source_post_id, []).append(t)

    _stance_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}

    for pid in seen_ids:
        post = posts_by_id.get(pid, {})
        content = post.get("content", "（原文不可用）")
        translation = post.get("translation", "（翻译不可用）")

        # Build stance badges for this post
        stances = ticker_by_post.get(pid, [])
        stance_html = ""
        if stances:
            badges = "".join(
                f'<span class="stance-badge stance-{_e(t.get("stance","neutral"))}">'
                f'${_e(t.get("symbol","?"))}: '
                f'{_stance_cn.get(t.get("stance","neutral"), t.get("stance",""))}'
                f'</span>'
                for t in stances
            )
            stance_html = (
                '<div class="stance-row">'
                '<span class="stance-row-label">Stance&nbsp;</span>'
                + badges
                + "</div>"
            )

        parts.append(
            '<div class="tweet-card">'
            f'<div class="tweet-card-id">source_post_id: {_e(pid)}</div>'
            f'<div class="tweet-original">{_e(content)}</div>'
            '<div class="tweet-translation">'
            '<div class="tweet-trans-label">中文翻译</div>'
            f'<div class="tweet-trans-text">{_e(translation)}</div>'
            + stance_html
            + "</div>"
            "</div>"
        )

    parts.append("</div>")  # source-panel
    parts.append("</div>")  # plan-body
    parts.append("</div>")  # plan-block

    return "\n".join(parts)


# ── 公开接口 ──────────────────────────────────────────────────────────────────

def generate_preview(
    rendered_plans: List[RenderedPlan],
    posts_by_id: Dict[str, dict],
    output_path: Path,
    run_date: date,
    session: str,
) -> Path:
    """
    生成单文件静态预览页 HTML，写入 output_path，返回该路径。

    Args:
        rendered_plans: 已渲染图片的 PostPlan 列表
        posts_by_id:    原推数据，key=source_post_id，value 含 content/translation
        output_path:    HTML 输出路径（图片应在同一目录）
        run_date:       运行日期，用于页面标题
        session:        "盘前" | "盘后" | "周报"
    """
    output_path = Path(output_path)
    html_dir = output_path.parent
    html_dir.mkdir(parents=True, exist_ok=True)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_str = run_date.strftime("%m.%d")
    n = len(rendered_plans)

    lines: List[str] = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f"<title>小红书预览 · {date_str} {_e(session)}</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        '<div class="page-header">',
        "<h1>小红书内容预览</h1>",
        f'<span class="meta">生成于 {_e(now_str)}'
        f" &nbsp;·&nbsp; 窗口: {_e(session)}"
        f" &nbsp;·&nbsp; {n} 帖</span>",
        "</div>",
        '<div class="content">',
    ]

    for i, rp in enumerate(rendered_plans):
        lines.append(_plan_block_html(i, rp, posts_by_id, html_dir))

    lines.append(_scan_report_html(rendered_plans))
    lines.append("</div>")  # content
    lines.append(f"<script>{_JS}</script>")
    lines.append("</body>")
    lines.append("</html>")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


# ── --mock 模式 ───────────────────────────────────────────────────────────────

def _run_mock() -> None:
    from xhs_renderer import render_cover, render_tail, render_tweet_cards

    run_date = date.today()
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = Path(os.getenv("XHS_OUTPUT_DIR", "xhs_output")) / f"mock_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[preview] output: {out_dir.resolve()}")

    # ── 原推数据（p1 故意加长以触发长推分页）
    posts_by_id = {
        "p1": {
            "id": "p1",
            "content": (
                "NVDA supply constraints continue to be severe. "
                "Data center demand is accelerating faster than TSMC can expand CoWoS capacity. "
                "I've been closely watching TSMC's CoWoS utilization rates, and they remain "
                "at near 100% for most of 2025. The H200 and B200 allocation queues are still "
                "6-9 months out for most hyperscalers. Even with N3P ramping and N2 on the "
                "horizon, there's no sign the packaging gap is closing — and that's the real "
                "bottleneck, not the logic node itself. CoWoS substrate expansion typically "
                "lags leading-edge logic by 18-24 months. So even if TSMC ramps logic capacity "
                "next year, packaging will remain the binding constraint. "
                "I think this structural shortage persists well into 2026."
            ),
            "translation": (
                "英伟达供给瓶颈依然严峻，短期内看不到改善迹象。"
                "数据中心需求的增速已远超台积电 CoWoS 封装产能的扩张速度。"
                "Serenity 密切跟踪台积电 CoWoS 利用率，2025 年大部分时间维持在接近 100%。"
                "H200 和 B200 的配额队列对大多数超大规模云厂商仍长达 6 至 9 个月。"
                "即便台积电 N3P 工艺持续爬坡、N2 节点已在路线图上，"
                "封装端的缺口仍未见收窄——这才是整个供应链的真正瓶颈，而非逻辑制程本身。"
                "从供应链角度来看，CoWoS 封装基板的扩产周期通常比主流制造工艺慢 18 至 24 个月。"
                "因此即便台积电明年逻辑产能提升，封装端仍将是约束整个供应链的核心环节。"
                "Serenity 判断这一结构性短缺将持续到 2026 年年底甚至更久。"
            ),
        },
        "p2": {
            "id": "p2",
            "content": (
                "Fed meeting minutes show real disagreement. Hawks want to hold, "
                "doves are pointing to softening labor data. "
                "I think we're in a wait-and-see mode for at least 2 more months."
            ),
            "translation": (
                "美联储会议记录显示内部存在明显分歧。鹰派主张维持利率，"
                "鸽派则指向就业数据走软。Serenity 认为至少还有两个月处于观望期。"
            ),
        },
        "p3": {
            "id": "p3",
            "content": (
                "AMD gained meaningful market share in enterprise AI inference. "
                "Still neutral on the stock — valuation is already pricing in a lot of good news."
            ),
            "translation": (
                "AMD 在企业级 AI 推理市场取得了可观的市占提升。"
                "Serenity 对该股保持中性立场，目前估值已基本反映了利好消息。"
            ),
        },
    }

    # ── 帖子 1：2 条推（p1 长推会触发分页 + p2 短推）
    card1 = ContentCard(
        source_post_id="p1",
        heading="NVDA 供给缺口短期难解",
        points=["数据中心需求持续加速增长", "台积电扩产计划明显滞后"],
        tickers=[{"symbol": "NVDA", "stance": "bullish"}],
        full_original=posts_by_id["p1"]["content"],
        full_translation=posts_by_id["p1"]["translation"],
    )
    card2 = ContentCard(
        source_post_id="p2",
        heading="美联储分歧加剧方向难判",
        points=["鹰派主张维持利率不变", "鸽派指向就业数据走软", "Serenity 认为观望期至少两个月"],
        full_original=posts_by_id["p2"]["content"],
        full_translation=posts_by_id["p2"]["translation"],
    )
    plan1 = PostPlan(
        title="白毛股神6.10盘前｜供给告急美联储同步撕裂【1】",
        cover_headline="供给告急美联储同步撕裂",
        cover_subline="两件事放一起才完整",
        cards=[card1, card2],
        note=(
            "今天盘前 Serenity 发了两条，我觉得放一起看才更有意思。\n\n"
            "英伟达那条，核心判断是：短缺不是暂时的，是结构性的。"
            "CoWoS 产能爬坡跟不上数据中心扩张速度，这个差距短期内难以消除。\n\n"
            "美联储那条说内部分歧比外面看到的还大。"
            "鸽派已经在看数据松动，鹰派还在撑着。"
            "Serenity 预测至少还有两个月不会动利率。\n\n"
            "两件事放一起有种共鸣：需求侧（AI 算力）在加速，"
            "而供给侧（产能和货币）还在被约束着。\n\n"
            "#美股  #英伟达  #NVDA  #美联储\n\n"
            + DISCLAIMER
        ),
        session="盘前",
        part_no=1,
    )

    # ── 帖子 2：分割续帖（AMD），演示 needs_human_edit 红框
    card3 = ContentCard(
        source_post_id="p3",
        heading="AMD 市占提升估值中性",
        points=["企业级 AI 推理市场份额增长", "Serenity 对估值保持中性立场"],
        tickers=[{"symbol": "AMD", "stance": "neutral"}],
        full_original=posts_by_id["p3"]["content"],
        full_translation=posts_by_id["p3"]["translation"],
    )
    plan2 = PostPlan(
        title="白毛股神6.10盘前｜AMD市占涨Serenity估值中性【2】",
        cover_headline="AMD市占涨Serenity估值中性",
        cover_subline="中性背后的赔率逻辑",
        cards=[card3],
        note=(
            "接上一帖，AMD 那条也值得单独说说。\n\n"
            "Serenity 对 AMD 在企业 AI 推理端的市占提升是认可的，"
            "这是真实发生的事。但 Serenity 并没有因此给出正面的估值判断——"
            "理由很直接：好消息已经被定价了，没有安全边际。\n\n"
            "中性不等于看差，只是赔率不够吸引。\n\n"
            "#美股  #AMD  #半导体\n\n"
            + DISCLAIMER
        ),
        session="盘前",
        part_no=2,
        needs_human_edit=True,
    )

    # ── 渲染图片（使用 render_tweet_cards 替换 render_card）
    rendered: List[RenderedPlan] = []
    for pi, (plan, cards) in enumerate(
        [(plan1, [card1, card2]), (plan2, [card3])]
    ):
        cover_path = out_dir / f"p{pi+1}_01_cover.png"
        render_cover(plan, cover_path, run_date=run_date)
        print(f"  cover: {cover_path.name}")

        card_paths: List[Path] = []
        for ci, card in enumerate(cards):
            tc_paths = render_tweet_cards(
                card, out_dir, f"p{pi+1}_c{ci+1:02d}",
                run_date=run_date, session=plan.session,
            )
            card_paths.extend(tc_paths)
            for p in tc_paths:
                print(f"  card:  {p.name}")

        tail_path = out_dir / f"p{pi+1}_tail.png"
        render_tail(tail_path)
        print(f"  tail:  {tail_path.name}")

        rendered.append(RenderedPlan(
            plan=plan,
            cover_path=cover_path,
            card_paths=card_paths,
            tail_path=tail_path,
        ))

    # ── 生成预览页
    html_path = generate_preview(
        rendered,
        posts_by_id,
        out_dir / "preview.html",
        run_date,
        "盘前",
    )
    print(f"\npreview HTML: {html_path.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="小红书内容预览页生成工具")
    parser.add_argument("--mock", action="store_true", help="生成示例预览页（含mock数据和渲染图片）")
    args = parser.parse_args()

    if args.mock:
        _run_mock()
    else:
        parser.print_help()
