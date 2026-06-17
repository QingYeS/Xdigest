"""
xhs_pipeline.py: composer + renderer + preview 的编排入口。

公开接口:
    generate_xhs(analyzed, session, *, mock=False) -> Path

运行:
    python xhs_pipeline.py --mock              # 本地全链路调试，不消耗 API
    python xhs_pipeline.py --mock --session 盘后
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, List, Optional

from blogger_config import filter_tracked, get_blogger


# ── JSON 解析工具 ─────────────────────────────────────────────────────────────

def _extract_json_array(text: str) -> list:
    """从 LLM 响应中提取第一个完整 JSON 数组（括号配对匹配，忽略后续内容）。"""
    start = text.find("[")
    if start == -1:
        raise ValueError(f"响应中未找到 JSON 数组: {text[:200]}")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError(f"JSON 数组括号不匹配: {text[:200]}")


def _extract_json_object(text: str) -> dict:
    """从 LLM 响应中提取第一个完整 JSON 对象（括号配对匹配，忽略后续内容）。"""
    start = text.find("{")
    if start == -1:
        raise ValueError(f"响应中未找到 JSON 对象: {text[:200]}")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError(f"JSON 对象括号不匹配: {text[:200]}")
from xhs_composer import ContentCard, PostPlan, compose
from xhs_preview import RenderedPlan, generate_preview
from xhs_renderer import render_cover, render_tail, render_tweet_cards


# ── Groq 系统 prompt ────────────────────────────────────────────────────────

_CARD_SYSTEM = """\
你是小红书内容创作助手，负责把英文推文改编成精炼的中文信息卡片。
严格规则（违反则内容无效）:
1. 指代博主一律用「Serenity」，绝对禁用「她」「他」「TA」
2. 禁止出现以下措辞: 做多、做空、建仓、加仓、减仓、入场、点位、目标价、建议买入、建议卖出、买入、卖出
3. 只转述博主观点（「Serenity 认为」「Serenity 看好」），不向读者发出操作建议
4. heading ≤ 18 字，必须是完整陈述句（主体 + 谓语/结论），禁止悬空短语
   禁例:「Serenity 对 $AXTI」（无谓语）「市场波动」（无主体无结论）
   正例:「Serenity 看好 $AXTI 国内唯一竞争地位」「$AAOI 受益供应链回流」
         「普涨行情源于伊朗局势降温」「Serenity: $NVDA 封装瓶颈短期难解」
   每条 point ≤ 24 字，points 共 2-4 条
5. tickers 只标原推中明确提及的标的，stance 仅限 bullish/bearish/neutral
6. points 必须忠实于原推，不增补博主没说的观点
   区分两种情况:
   - 博主明确表达的看法 → 「Serenity 认为……」「Serenity 看好……」
   - 博主陈述的事实或随口感叹 → 直接陈述事件，不安立场
   反例（硬安观点）: 原推只感叹「这市场太波动了」→ 不可写「Serenity 认为市场波动性高」
   正例（忠实还原）: 「Serenity 感叹市场波动剧烈」或「特朗普取消对伊朗攻击，大盘普涨」"""

_PLAN_SYSTEM = """\
你是小红书内容创作助手，负责为股票博主追踪帖子生成精准引流话题标签。
严格规则:
1. hashtags 生成 3-6 个，优先级顺序:
   ① 本帖涉及的全部股票代码（去掉$符号，如 NVDA、AXTI、AAOI）
   ② 本帖相关热词关键字（如 美联储、英伟达、AI算力、供应链、科技股、美股、港股，视内容选择）
   禁擦边 tag（#牛股 #翻倍 #暴涨 等）；不加 # 前缀；tag 文本不含空格；博主固定 hashtag 由系统注入，不必生成
2. 指代博主用「Serenity」或「白毛股神」，绝对禁用「她」「他」
3. 禁止荐股措辞: 做多/做空/建仓/买入/卖出/目标价等"""


# ── Groq LLM 工厂 ───────────────────────────────────────────────────────────

def _make_card_llm(client, model: str):
    def card_llm(post: dict, rejected_phrases=None) -> dict:
        reject_note = (
            f"\n\n上次生成命中禁词 {rejected_phrases}，请避免。"
            if rejected_phrases else ""
        )
        prompt = (
            f"请将以下推文改编为一张小红书信息卡片。\n\n"
            f"英文原文:\n{post.get('content', '')}\n\n"
            f"中文翻译:\n{post.get('translation', '')}\n\n"
            f"输出单个 JSON 对象，含:\n"
            '- "heading": 卡片标题(≤18字，完整陈述句，主体+结论，禁悬空如「Serenity 对 $AXTI」)\n'
            '- "points": 要点列表(2-4条，每条≤24字)\n'
            '- "tickers": [{"symbol":"XXX","stance":"bullish|bearish|neutral"}]'
            + reject_note
        )
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": _CARD_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.4,
                    max_tokens=1024,
                )
                raw = resp.choices[0].message.content.strip()
                return _extract_json_object(raw)
            except Exception as e:
                if "429" in str(e) or "rate" in str(e).lower():
                    wait = 20 * (attempt + 1)
                    print(f"    [xhs] card_llm 限速，等待 {wait}s")
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError("card_llm 多次重试后仍失败")

    return card_llm


def _primary_ticker(tickers: list) -> str:
    """返回该推的主体 ticker 字符串（如 '$AAOI'）。
    优先取 stance=bullish/bearish 的第一个，fallback 取 tickers[0]。"""
    if not tickers:
        return ""
    primary = next(
        (t for t in tickers if t.get("stance") in ("bullish", "bearish")),
        tickers[0],
    )
    return f"${primary['symbol']}"


def _make_plan_llm(client, model: str, blogger: dict):
    persona = blogger.get("note_persona", "")
    system_content = _PLAN_SYSTEM
    if persona:
        system_content += "\n\n写作人设（正文（投资笔记）必须按此人设写）:\n" + persona

    def plan_llm(cards, session: str, prior_summaries=None, rejected_phrases=None) -> dict:
        # 按 source_post_id 分组，取每推的第一张卡代表该推（副标题按推不按卡）
        post_groups: dict = {}
        for c in cards:
            if c.source_post_id not in post_groups:
                post_groups[c.source_post_id] = c
        card_summaries = "\n".join(
            f"推{i+1} [{_primary_ticker(c.tickers) or '无ticker'}]: {c.heading} — {'; '.join(c.points)}"
            for i, c in enumerate(post_groups.values())
        )
        prior_note = (
            f"\n\n前帖内容摘要（供正文（note）续写参考）: {prior_summaries}"
            if prior_summaries else ""
        )
        reject_note = (
            f"\n\n上次命中禁词 {rejected_phrases}，请避免。"
            if rejected_phrases else ""
        )
        prompt = (
            f"为以下 {len(post_groups)} 条推文生成发帖元数据。\n"
            f"发帖时段: {session}\n\n"
            f"各推文摘要（格式: 推N [主体ticker]: 标题 — 要点）:\n{card_summaries}"
            + prior_note + reject_note
            + '\n\n严格按 JSON 输出:\n'
            '{"hashtags":["..."]}'
        )
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.5,
                    max_tokens=800,
                )
                raw = resp.choices[0].message.content.strip()
                result = _extract_json_object(raw)
                return result
            except Exception as e:
                if "429" in str(e) or "rate" in str(e).lower():
                    wait = 20 * (attempt + 1)
                    print(f"    [xhs] plan_llm 限速，等待 {wait}s")
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError("plan_llm 多次重试后仍失败")

    return plan_llm


# ── 渲染单个 PostPlan ────────────────────────────────────────────────────────

def _render_plan(
    plan: PostPlan,
    out_dir: Path,
    plan_idx: int,
    blogger: dict,
    run_date: date,
    total_plans: int = 1,
) -> RenderedPlan:
    prefix = f"p{plan_idx:02d}"

    cover_path = out_dir / f"{prefix}_cover.png"
    render_cover(plan, cover_path, run_date=run_date, blogger=blogger, total_plans=total_plans)
    print(f"  [render] {cover_path.name}")

    card_paths: List[Path] = []
    for ci, card in enumerate(plan.cards):
        tc_paths = render_tweet_cards(
            card, out_dir, f"{prefix}_c{ci+1:02d}",
            run_date=run_date, session=plan.session, blogger=blogger,
        )
        card_paths.extend(tc_paths)
        for p in tc_paths:
            print(f"  [render] {p.name}")

    tail_path = out_dir / f"{prefix}_tail.png"
    render_tail(tail_path, blogger=blogger, run_date=run_date)
    print(f"  [render] {tail_path.name}")

    return RenderedPlan(
        plan=plan,
        cover_path=cover_path,
        card_paths=card_paths,
        tail_path=tail_path,
    )


# ── 公开接口 ─────────────────────────────────────────────────────────────────

def generate_xhs(
    analyzed: List[dict],
    session: str,
    *,
    mock: bool = False,
    card_llm: Optional[Callable] = None,
) -> Path:
    """
    编排入口：analyzed posts → composer → renderer → preview HTML。

    Args:
        analyzed: analyze_posts() 输出（含 id/content/translation/handle 等字段）
        session:  "盘前" | "盘后" | "周报"
        mock:     True 时使用内置 mock 数据，不调用 Groq

    Returns:
        输出目录 Path (xhs_output/{YYYYMMDD_HHMM}/)
    """
    if mock:
        return _run_mock(session)

    run_date = date.today()
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = Path(os.getenv("XHS_OUTPUT_DIR", "xhs_output")) / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[xhs] output: {out_dir.resolve()}")

    # 过滤到跟踪博主（双重保险，main.py 已过滤一次）
    tracked = filter_tracked(analyzed)
    if not tracked:
        print("[xhs] 无跟踪博主帖子，跳过生成")
        return out_dir

    # Groq 客户端（延迟导入，避免 mock 模式依赖）
    from groq import Groq
    from config import GROQ_API_KEY
    client = Groq(api_key=GROQ_API_KEY)
    model = "llama-3.3-70b-versatile"

    posts_by_id: dict = {p["id"]: p for ps in tracked.values() for p in ps}
    all_rendered: List[RenderedPlan] = []
    plan_idx = 1

    for handle, posts in tracked.items():
        blogger = get_blogger(handle) or {
            "handle": handle, "display_name": handle, "cn_name": handle,
        }
        print(f"[xhs] 装箱 {handle}（{len(posts)} 条）...")
        plans = compose(
            posts, session, blogger, run_date=run_date,
            card_llm=card_llm or _make_card_llm(client, model),
            plan_llm=_make_plan_llm(client, model, blogger),
        )
        print(f"[xhs] 生成 {len(plans)} 个 PostPlan")
        for plan in plans:
            rp = _render_plan(plan, out_dir, plan_idx, blogger, run_date, total_plans=len(plans))
            all_rendered.append(rp)
            plan_idx += 1

    html_path = generate_preview(
        all_rendered, posts_by_id,
        out_dir / "preview.html",
        run_date, session,
    )
    print(f"[xhs] preview: {html_path.resolve()}")
    return out_dir


# ── mock 模式 ─────────────────────────────────────────────────────────────────

def _run_mock(session: str = "盘前") -> Path:
    """使用内置数据跑完整链路，不消耗任何 API。"""
    run_date = date.today()
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = Path(os.getenv("XHS_OUTPUT_DIR", "xhs_output")) / f"mock_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[xhs-mock] output: {out_dir.resolve()}")

    blogger = {
        "handle": "@aleabitoreddit",
        "display_name": "Serenity",
        "cn_name": "白毛股神",
    }

    mock_posts = [
        {
            "id": "mock_p1",
            "handle": "@aleabitoreddit",
            "display_name": "Serenity",
            "content": (
                "NVDA supply constraints continue to be severe. "
                "Data center demand is accelerating faster than TSMC can expand CoWoS capacity. "
                "I've been closely watching TSMC's CoWoS utilization rates, and they remain "
                "at near 100% for most of 2025. The H200 and B200 allocation queues are still "
                "6-9 months out for most hyperscalers. Even with N3P ramping and N2 on the "
                "horizon, there's no sign the packaging gap is closing."
            ),
            "translation": (
                "英伟达供给瓶颈依然严峻，短期内看不到改善迹象。"
                "数据中心需求的增速已远超台积电 CoWoS 封装产能的扩张速度。"
                "Serenity 密切跟踪台积电 CoWoS 利用率，2025 年大部分时间维持在接近 100%。"
                "H200 和 B200 的配额队列对大多数超大规模云厂商仍长达 6 至 9 个月。"
                "即便台积电 N3P 工艺持续爬坡、N2 节点已在路线图上，"
                "封装端的缺口仍未见收窄——这才是整个供应链的真正瓶颈，而非逻辑制程本身。"
            ),
        },
        {
            "id": "mock_p2",
            "handle": "@aleabitoreddit",
            "display_name": "Serenity",
            "content": (
                "Fed meeting minutes show real disagreement. Hawks want to hold, "
                "doves are pointing to softening labor data. "
                "Serenity thinks we're in a wait-and-see mode for at least 2 more months."
            ),
            "translation": (
                "美联储会议记录显示内部存在明显分歧。鹰派主张维持利率，"
                "鸽派则指向就业数据走软。Serenity 认为至少还有两个月处于观望期。"
            ),
        },
    ]

    posts_by_id = {p["id"]: p for p in mock_posts}

    _call_idx = [0]

    def _stub_card_llm(post: dict, rejected_phrases=None) -> dict:
        return {
            "heading": "mock 卡标题",
            "points": ["Serenity 关注市场核心动向", "短期不确定性仍存"],
            "tickers": [],
        }

    def _stub_plan_llm(cards, session_: str, prior_summaries=None, rejected_phrases=None) -> dict:
        _call_idx[0] += 1
        return {
            "hashtags": ["美股", "Serenity", "白毛股神"],
        }

    plans = compose(
        mock_posts, session, blogger, run_date=run_date,
        card_llm=_stub_card_llm, plan_llm=_stub_plan_llm,
    )
    print(f"[xhs-mock] {len(plans)} 个 PostPlan")

    all_rendered: List[RenderedPlan] = []
    for i, plan in enumerate(plans):
        rp = _render_plan(plan, out_dir, i + 1, blogger, run_date, total_plans=len(plans))
        all_rendered.append(rp)

    html_path = generate_preview(
        all_rendered, posts_by_id,
        out_dir / "preview.html",
        run_date, session,
    )
    print(f"[xhs-mock] preview: {html_path.resolve()}")
    return out_dir


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="小红书内容生成管道")
    parser.add_argument("--mock", action="store_true", help="使用 mock 数据，不消耗 API")
    parser.add_argument("--session", default="盘前", choices=["盘前", "盘后", "周报"])
    args = parser.parse_args()
    if args.mock:
        generate_xhs([], args.session, mock=True)
    else:
        parser.print_help()
