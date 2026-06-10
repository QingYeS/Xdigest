"""
xhs_composer: 把一个时间窗内目标博主的多条推合成若干 PostPlan。

主入口:
    compose(posts, session, blogger, run_date, card_llm, plan_llm) -> list[PostPlan]

LLM 接口(可注入,便于测试):
    card_llm(post, n_cards, rejected_phrases=None) -> list[dict]
        每个 dict: {"heading": str, "points": list[str],
                    "tickers": list[{"symbol": str, "stance": str}]}
        stance ∈ {bullish, bearish, neutral}；仅原推有明确方向时标 bullish/bearish，其余 neutral
        heading/points 中指代博主一律用名字（Serenity），禁用「她」「他」
        rejected_phrases: 上次被拒绝的禁词列表(重试时传入,让 LLM 知道原因)
    plan_llm(cards, session, rejected_phrases=None) -> dict
        字段: hook(str), cover_headline(str), cover_subline(str),
               caption_body(str), hashtags(list[str])
        cover_headline 约束: 优先使用中文称呼「白毛股神」，避免英文名 Serenity
          （排版考量：英文长词在封面大字号下易被断行；points/caption 中仍正常使用 Serenity）
        rejected_phrases: 同上

禁词校验在代码层强制执行,card 和 plan 各自最多 2 次重试,仍命中则标记
needs_human_edit。caption 的免责声明由代码追加,不依赖 LLM。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, Optional, Set, Tuple

DISCLAIMER = (
    "以上仅为博主观点的翻译与个人解读，不构成任何投资建议，"
    "市场有风险，决策需谨慎。"
)

BANNED_PHRASES: List[str] = [
    "做多", "做空", "建仓", "加仓", "减仓", "入场",
    "点位", "目标价", "建议买入", "建议卖出", "买入", "卖出",
]

# 代词禁用：heading/points 中一律用博主名字，禁用 她/他
BANNED_PRONOUNS: List[str] = ["她", "他"]

MAX_CARDS: int = int(os.getenv("XHS_MAX_CARDS_PER_POST", "4"))
LONG_TWEET_THRESHOLD: int = 120  # translation 超过此字数视为长推,拆 2 张卡


# ── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class ContentCard:
    source_post_id: str
    heading: str            # ≤14 字
    points: List[str]       # 2-4 个要点,每条 ≤24 字
    part: int = 1           # 长推拆分时的页码
    quote: Optional[str] = None  # 原推英文引言(可选,用于 quote sticky note)
    tickers: List[dict] = field(default_factory=list)  # [{symbol, stance}], stance ∈ bullish/bearish/neutral


@dataclass
class PostPlan:
    title: str              # 完整标题,含模板前缀与可选分割编号
    cover_headline: str     # ≤12 字
    cover_subline: str      # ≤16 字,分割帖之间必须不同
    cards: List[ContentCard]
    caption: str            # 含话题标签 + 免责声明
    session: str            # "盘前" | "盘后" | "周报"
    part_no: Optional[int] = None   # 分割编号;无分割为 None
    needs_human_edit: bool = False


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def scan_banned(text: str) -> List[str]:
    """返回 text 中命中的所有禁词。"""
    return [p for p in BANNED_PHRASES if p in text]


def scan_card_violations(text: str) -> List[str]:
    """禁词 + 禁用代词（仅用于 card heading/points 检查）。"""
    violations = scan_banned(text)
    violations.extend(p for p in BANNED_PRONOUNS if p in text)
    return violations


def _is_long(post: dict) -> bool:
    return len(post.get("translation", "")) > LONG_TWEET_THRESHOLD


def _build_title(
    hook: str, session: str, run_date: date, part_no: Optional[int]
) -> str:
    date_str = f"{run_date.month}.{run_date.day}"
    suffix = f"【{part_no}】" if part_no is not None else ""
    return f"白毛股神{date_str}{session}｜{hook}{suffix}"


def _assemble_caption(body: str, hashtags: List[str]) -> str:
    tags = "  ".join(f"#{tag}" for tag in hashtags) if hashtags else ""
    parts = [body]
    if tags:
        parts.append(tags)
    parts.append(DISCLAIMER)
    return "\n\n".join(parts)


# ── LLM 占位(里程碑 5 接入 Groq) ────────────────────────────────────────────

def _default_card_llm(
    post: dict,
    n_cards: int,
    rejected_phrases: Optional[List[str]] = None,
) -> List[dict]:
    raise NotImplementedError("Groq card LLM not yet wired up — pass card_llm= for testing")


def _default_plan_llm(
    cards: List[ContentCard],
    session: str,
    rejected_phrases: Optional[List[str]] = None,
) -> dict:
    raise NotImplementedError("Groq plan LLM not yet wired up — pass plan_llm= for testing")


# ── 核心逻辑 ─────────────────────────────────────────────────────────────────

def _gen_cards_with_validation(
    post: dict,
    card_llm: Callable,
) -> Tuple[List[ContentCard], bool]:
    """
    为单条推生成 ContentCard(s),并对 heading/points 做禁词校验。
    命中禁词时最多重试 2 次,重试时把被拒绝的禁词传给 card_llm。
    返回 (cards, needs_human_edit)。
    """
    n_cards = 2 if _is_long(post) else 1
    last_cards: List[ContentCard] = []
    rejected: Optional[List[str]] = None

    for attempt in range(3):  # 初次 + 最多 2 次重试
        raw = card_llm(post, n_cards, rejected_phrases=rejected)
        cards = [
            ContentCard(
                source_post_id=post["id"],
                heading=r["heading"],
                points=list(r["points"]),
                part=i + 1,
                tickers=list(r.get("tickers", [])),
            )
            for i, r in enumerate(raw[:n_cards])
        ]
        card_text = "".join(c.heading + "".join(c.points) for c in cards)
        hits = scan_card_violations(card_text)
        if not hits:
            return cards, False
        rejected = hits
        last_cards = cards
        print(f"[composer] 卡片禁词命中 {hits},第 {attempt + 1}/2 次重试")

    return last_cards, True


def _gen_plan_meta(
    cards: List[ContentCard],
    session: str,
    part_no: Optional[int],
    run_date: date,
    plan_llm: Callable,
) -> Tuple[Dict, bool]:
    """
    为单个 PostPlan 生成 title/cover/caption,并做禁词校验。
    命中禁词时最多重试 2 次,重试时把被拒绝的禁词传给 plan_llm。
    返回 (meta_dict, needs_human_edit)。
    """
    last: Dict = {}
    rejected: Optional[List[str]] = None

    for attempt in range(3):  # 初次 + 最多 2 次重试
        raw = plan_llm(cards, session, rejected_phrases=rejected)
        title = _build_title(raw["hook"], session, run_date, part_no)
        caption = _assemble_caption(raw["caption_body"], raw.get("hashtags", []))
        last = {
            "title": title,
            "cover_headline": raw["cover_headline"],
            "cover_subline": raw["cover_subline"],
            "caption": caption,
        }
        hits = scan_banned(title + raw["cover_headline"] + raw["cover_subline"] + caption)
        if not hits:
            return last, False
        rejected = hits
        print(f"[composer] 帖子禁词命中 {hits},第 {attempt + 1}/2 次重试")

    return last, True


def compose(
    posts: List[dict],
    session: str,
    blogger: dict,
    run_date: Optional[date] = None,
    card_llm: Optional[Callable] = None,
    plan_llm: Optional[Callable] = None,
) -> List[PostPlan]:
    """
    把 posts 合成若干 PostPlan。

    Args:
        posts:    目标博主的帖子列表(已经过 filter_tracked 筛选)
        session:  "盘前" | "盘后" | "周报"
        blogger:  博主配置 dict,需含 cn_name 字段
        run_date: 用于标题日期;默认 date.today()
        card_llm: 注入的卡片生成函数,None 时用默认(需 Groq)
        plan_llm: 注入的计划元数据生成函数,None 时用默认(需 Groq)
    """
    if run_date is None:
        run_date = date.today()
    if card_llm is None:
        card_llm = _default_card_llm
    if plan_llm is None:
        plan_llm = _default_plan_llm

    # 步骤 1:每条推生成 1-2 张 ContentCard,记录卡片验证失败的 post_id
    all_cards: List[ContentCard] = []
    failing_post_ids: Set[str] = set()
    for post in posts:
        cards, card_needs_edit = _gen_cards_with_validation(post, card_llm)
        all_cards.extend(cards)
        if card_needs_edit:
            failing_post_ids.add(post["id"])

    if not all_cards:
        return []

    # 步骤 2:装箱——按时间顺序,每帖最多 MAX_CARDS 张卡
    bins: List[List[ContentCard]] = []
    for card in all_cards:
        if not bins or len(bins[-1]) >= MAX_CARDS:
            bins.append([])
        bins[-1].append(card)

    # 步骤 3:为每个 bin 生成 title/cover/caption
    n_bins = len(bins)
    plans: List[PostPlan] = []
    for i, cards in enumerate(bins):
        part_no = (i + 1) if n_bins > 1 else None
        meta, plan_needs_edit = _gen_plan_meta(cards, session, part_no, run_date, plan_llm)
        card_issue = any(c.source_post_id in failing_post_ids for c in cards)
        plans.append(PostPlan(
            title=meta["title"],
            cover_headline=meta["cover_headline"],
            cover_subline=meta["cover_subline"],
            cards=cards,
            caption=meta["caption"],
            session=session,
            part_no=part_no,
            needs_human_edit=plan_needs_edit or card_issue,
        ))

    # 步骤 4:分割帖 cover_subline 唯一性检查
    if len(plans) > 1:
        seen: Dict[str, int] = {}
        for p in plans:
            seen[p.cover_subline] = seen.get(p.cover_subline, 0) + 1
        duplicates = {s for s, cnt in seen.items() if cnt > 1}
        if duplicates:
            for p in plans:
                if p.cover_subline in duplicates:
                    p.needs_human_edit = True
                    print(f"[composer] 分割帖 cover_subline 重复: {p.cover_subline!r}")

    return plans
