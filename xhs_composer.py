"""
xhs_composer: 把一个时间窗内目标博主的多条推合成若干 PostPlan。

主入口:
    compose(posts, session, blogger, run_date, card_llm, plan_llm) -> list[PostPlan]

LLM 接口(可注入,便于测试):
    card_llm(post, rejected_phrases=None) -> dict
        dict: {"heading": str, "points": list[str],
               "tickers": list[{"symbol": str, "stance": str}]}
        每条推固定生成 1 张 ContentCard；渲染溢出分页由 render_tweet_cards 处理。
        stance ∈ {bullish, bearish, neutral}；仅原推有明确方向时标 bullish/bearish，其余 neutral
        heading/points 中指代博主一律用名字（Serenity），禁用「她」「他」
        rejected_phrases: 上次被拒绝的禁词列表(重试时传入,让 LLM 知道原因)

    plan_llm(cards, session, prior_summaries=None, rejected_phrases=None) -> dict
        字段: hashtags(list[str])
        prior_summaries: 前面各帖 cover_subline 列表（分割帖续帖时传入）
        rejected_phrases: 同上

禁词校验在代码层强制执行,card 和 plan 各自最多 2 次重试,仍命中则标记
needs_human_edit。note 的免责声明由代码追加,不依赖 LLM。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

NOTE_BODY = (
    "白毛股神发推很随性，既有聊天也有观点。"
    "本笔记长po总结，短po直译，一天早/晚各发一次。"
    "尽量让大家看到Serenity在说什么，方便中文社区一起讨论。"
)

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

# 容量配置
LONG_TWEET_THRESHOLD: int = 120   # translation 超过此字数视为长推
MAX_TWEETS: int = int(os.getenv("XHS_MAX_TWEETS_PER_POST", "3"))   # 每帖推数量软上限
MAX_CARDS_HARD: int = 16          # 每帖内容卡硬上限 (18张图 - 封面 - 尾页)

_SESSION_LABEL: Dict[str, str] = {"盘前": "早", "盘后": "晚", "周报": "周"}


# ── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class ContentCard:
    source_post_id: str
    heading: str            # ≤18 字，完整陈述句
    points: List[str]       # 2-4 个要点,每条 ≤24 字
    part: int = 1           # 长推拆分时的页码
    quote: Optional[str] = None  # 原推英文引言(可选,用于 quote sticky note)
    tickers: List[dict] = field(default_factory=list)  # [{symbol, stance}]
    full_original: str = ""    # 对应推的英文原文(图文分工:图=摘要卡,文=原文对照)
    full_translation: str = "" # 对应推的全文直译


@dataclass
class PostPlan:
    title: str              # 完整标题,含模板前缀与可选分割编号
    cover_headline: str     # ≤12 字
    cover_subline: str      # 多行 bullet(每行以「- 」开头)；每行约 ≤32 字(临时上限,渲染版面校准后精调)；质量优先,分割帖之间整体必须不同
    cards: List[ContentCard]
    note: str               # 含话题标签 + 免责声明
    session: str            # "盘前" | "盘后" | "周报"
    part_no: Optional[int] = None   # 分割编号;无分割为 None
    needs_human_edit: bool = False
    cover_subline_flags: List[bool] = field(default_factory=list)
    # True = 该行 heading 含禁词已 fallback，需人工核查


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def scan_banned(text: str) -> List[str]:
    """返回 text 中命中的所有禁词。"""
    return [p for p in BANNED_PHRASES if p in text]


def scan_card_violations(text: str) -> List[str]:
    """禁词 + 禁用代词（仅用于 card heading/points 检查）。"""
    violations = scan_banned(text)
    violations.extend(p for p in BANNED_PRONOUNS if p in text)
    return violations


def _pick_ticker_from_card(card: "ContentCard") -> str:
    """返回该推的主体 ticker 字符串（如 '$AAOI'）；优先取 bullish/bearish 的，fallback 取第一个。"""
    tickers = card.tickers or []
    if not tickers:
        return ""
    primary = next(
        (t for t in tickers if t.get("stance") in ("bullish", "bearish")),
        tickers[0],
    )
    return f"${primary['symbol']}"


def _build_cover_subline(bin_cards: List["ContentCard"]) -> Tuple[str, List[bool]]:
    """从 bin_cards 的 heading 直接生成副标题（每推一行，按推顺序，不按卡）。
    heading 含禁词时 fallback 为「$TICKER 相关动态」或「相关动态」。
    返回 (cover_subline_str, flags: List[bool])，flags[i]=True 表示该行触发了降级。
    """
    seen_ids: List[str] = []
    post_to_card: Dict[str, "ContentCard"] = {}
    for c in bin_cards:
        if c.source_post_id not in post_to_card:
            post_to_card[c.source_post_id] = c
            seen_ids.append(c.source_post_id)

    lines: List[str] = []
    flags: List[bool] = []
    for pid in seen_ids:
        card = post_to_card[pid]
        if scan_card_violations(card.heading):
            ticker = _pick_ticker_from_card(card)
            text = f"{ticker} 相关动态" if ticker else "相关动态"
            lines.append(f"- {text}")
            flags.append(True)
        else:
            lines.append(f"- {card.heading}")
            flags.append(False)
    return "\n".join(lines), flags


def estimate_cards(post: dict) -> int:
    """一条推恒定对应 1 张 ContentCard；渲染溢出分页由 render_tweet_cards 处理。"""
    return 1


def _build_title(session: str, run_date: date, part_no: int, total_plans: int) -> str:
    date_str = run_date.strftime("%Y%m%d")
    label = _SESSION_LABEL.get(session, "晚")
    return f"白毛股神(Serenity) | {date_str}{label}【{part_no}/{total_plans}】"


def _assemble_note(
    hashtags: List[str],
    fixed_hashtags: Optional[List[str]] = None,
) -> str:
    fixed = list(fixed_hashtags) if fixed_hashtags else []
    extra = [t for t in hashtags if t not in fixed]
    all_tags = [t.replace(" ", "") for t in fixed + extra]
    tags = "  ".join(f"#{tag}" for tag in all_tags) if all_tags else ""
    parts = [NOTE_BODY, tags, DISCLAIMER] if tags else [NOTE_BODY, DISCLAIMER]
    return "\n\n".join(parts)


# ── LLM 占位(里程碑 5 接入 Groq) ────────────────────────────────────────────

def _default_card_llm(
    post: dict,
    rejected_phrases: Optional[List[str]] = None,
) -> dict:
    raise NotImplementedError("Groq card LLM not yet wired up — pass card_llm= for testing")


def _default_plan_llm(
    cards: List[ContentCard],
    session: str,
    prior_summaries: Optional[List[str]] = None,
    rejected_phrases: Optional[List[str]] = None,
) -> dict:
    raise NotImplementedError("Groq plan LLM not yet wired up — pass plan_llm= for testing")


# ── 核心逻辑 ─────────────────────────────────────────────────────────────────

def _gen_cards_with_validation(
    post: dict,
    card_llm: Callable,
) -> Tuple[List[ContentCard], bool]:
    """
    为单条推生成 1 张 ContentCard，并对 heading/points 做禁词校验。
    命中禁词时最多重试 2 次，重试时把被拒绝的禁词传给 card_llm。
    返回 ([card], needs_human_edit)。
    """
    last_card: Optional[ContentCard] = None
    rejected: Optional[List[str]] = None

    for attempt in range(3):  # 初次 + 最多 2 次重试
        raw = card_llm(post, rejected_phrases=rejected)
        card = ContentCard(
            source_post_id=post["id"],
            heading=raw["heading"],
            points=list(raw["points"]),
            part=1,
            tickers=list(raw.get("tickers", [])),
            full_original=post.get("content", ""),
            full_translation=post.get("translation", ""),
        )
        hits = scan_card_violations(card.heading + "".join(card.points))
        if not hits:
            return [card], False
        rejected = hits
        last_card = card
        print(f"[composer] card violation {hits}, retry {attempt + 1}/2")

    return [last_card], True


def _gen_plan_meta(
    cards: List[ContentCard],
    session: str,
    part_no: int,
    run_date: date,
    plan_llm: Callable,
    total_plans: int = 1,
    prior_summaries: Optional[List[str]] = None,
    cover_subline: str = "",
    fixed_hashtags: Optional[List[str]] = None,
) -> Tuple[Dict, bool]:
    """
    为单个 PostPlan 生成 title/cover/note,并做禁词校验。
    命中禁词时最多重试 2 次,重试时把被拒绝的禁词传给 plan_llm。
    cover_subline: 由代码层预生成（_build_cover_subline），不再从 plan_llm 读取。
    prior_summaries: 前面各帖的 cover_subline 列表（分割帖时传入，供 plan_llm 写续写 note 用）。
    fixed_hashtags: 从 blogger config 提取的固定 hashtag（display_name / cn_name），代码层注入。
    返回 (meta_dict, needs_human_edit)。
    """
    last: Dict = {}
    rejected: Optional[List[str]] = None

    for attempt in range(3):  # 初次 + 最多 2 次重试
        raw = plan_llm(
            cards,
            session,
            prior_summaries=prior_summaries,
            rejected_phrases=rejected,
        )
        title = _build_title(session, run_date, part_no, total_plans)
        note = _assemble_note(raw.get("hashtags", []), fixed_hashtags)
        date_str = f"{run_date.month}.{run_date.day}"
        cover_headline = f"Serenity {date_str}更新"
        last = {
            "title": title,
            "cover_headline": cover_headline,
            "cover_subline": cover_subline,
            "note": note,
        }
        # cover_subline 由代码层保证合规，不参与 LLM 重试；note 仍必须扫描
        hits = scan_banned(title + cover_headline + note)
        if not hits:
            return last, False
        rejected = hits
        print(f"[composer] plan violation {hits}, retry {attempt + 1}/2")

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

    装箱规则（以推为原子单位）:
    - 软上限: 每帖最多 MAX_TWEETS 条推（XHS_MAX_TWEETS_PER_POST，默认 3）
    - 硬上限: 单帖内容卡 ≤ MAX_CARDS_HARD（16）
    - 触发新帖条件（满足任一）:
        (a) 当前帖已达 MAX_TWEETS 条推
        (b) 再加下一条推的卡组会使内容卡超过 MAX_CARDS_HARD
    - 原子性: 同一条推的所有卡始终归属同一帖，不跨帖切断

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

    fixed_hashtags = [t for t in [blogger.get("display_name", ""), blogger.get("cn_name", "")] if t]

    # 步骤 1: 每条推生成卡组（tweet group = 该推的所有 ContentCard）
    # tweet_groups: [(post_id, cards, card_needs_edit), ...]
    TweetGroup = Tuple[str, List[ContentCard], bool]
    tweet_groups: List[TweetGroup] = []
    for post in posts:
        cards, card_needs_edit = _gen_cards_with_validation(post, card_llm)
        if cards:
            tweet_groups.append((post["id"], cards, card_needs_edit))

    if not tweet_groups:
        return []

    # 步骤 2: 装箱——以推组为单位，维护软/硬上限，保持原子性
    bins: List[List[TweetGroup]] = []
    for group in tweet_groups:
        _, group_cards, _ = group
        group_n = len(group_cards)
        current_tweets = len(bins[-1]) if bins else 0
        current_cards = sum(len(g[1]) for g in bins[-1]) if bins else 0

        start_new = (
            not bins
            or current_tweets >= MAX_TWEETS
            or current_cards + group_n > MAX_CARDS_HARD
        )
        if start_new:
            bins.append([])
        bins[-1].append(group)

    # 步骤 3: 为每个 bin 生成 title/cover/note（传递前帖摘要作衔接上下文）
    n_bins = len(bins)
    plans: List[PostPlan] = []
    for i, bin_groups in enumerate(bins):
        bin_cards = [c for _, grp_cards, _ in bin_groups for c in grp_cards]
        bin_has_fail = any(needs_edit for _, _, needs_edit in bin_groups)

        part_no = i + 1
        prior_summaries = [p.cover_subline for p in plans]  # plans generated so far

        subline_str, subline_flags = _build_cover_subline(bin_cards)
        meta, plan_needs_edit = _gen_plan_meta(
            bin_cards, session, part_no, run_date, plan_llm,
            total_plans=n_bins, prior_summaries=prior_summaries,
            cover_subline=subline_str, fixed_hashtags=fixed_hashtags,
        )
        plans.append(PostPlan(
            title=meta["title"],
            cover_headline=meta["cover_headline"],
            cover_subline=subline_str,
            cards=bin_cards,
            note=meta["note"],
            session=session,
            part_no=part_no,
            needs_human_edit=plan_needs_edit or bin_has_fail,
            cover_subline_flags=subline_flags,
        ))

    # 步骤 4: 分割帖 cover_subline 唯一性检查
    if len(plans) > 1:
        seen: Dict[str, int] = {}
        for p in plans:
            seen[p.cover_subline] = seen.get(p.cover_subline, 0) + 1
        duplicates = {s for s, cnt in seen.items() if cnt > 1}
        if duplicates:
            for p in plans:
                if p.cover_subline in duplicates:
                    p.needs_human_edit = True
                    print(f"[composer] duplicate cover_subline: {p.cover_subline!r}")

    return plans


# ── debug-pack 入口（python xhs_composer.py --debug-pack）────────────────────

def _debug_pack() -> None:
    """用占位 LLM 打印装箱结果，不消耗 API，供验证装箱逻辑。"""
    from datetime import datetime

    run_date = date.today()

    # 构造不同长度的 mock 推
    def _post(pid: str, n_chars: int) -> dict:
        return {
            "id": pid,
            "content": f"[EN] post {pid}",
            "translation": "测" * n_chars,
        }

    # 场景: 4条推 — 短(50)/长(135)/短(80)/超长(250)
    # estimate_cards: 50→1, 135→2, 80→1, 250→3  合计: 7张卡
    # MAX_TWEETS=3 → 第4条推超出推数软上限，触发分帖
    posts = [
        _post("p1", 50),    # 1 card
        _post("p2", 135),   # 2 cards
        _post("p3", 80),    # 1 card
        _post("p4", 250),   # 3 cards  ← 触发新帖(已有3条推)
    ]

    call_idx = [0]

    def stub_card_llm(post, rejected_phrases=None):
        return {"heading": f"{post['id']} 标题", "points": ["要点一", "要点二"]}

    def stub_plan_llm(cards, session, prior_summaries=None, rejected_phrases=None):
        call_idx[0] += 1
        pid_set = sorted({c.source_post_id for c in cards})
        return {
            "note_body": f"本帖摘要{'、'.join(pid_set)}",
            "hashtags": ["美股"],
        }

    plans = compose(posts, "盘前", {}, run_date=run_date,
                    card_llm=stub_card_llm, plan_llm=stub_plan_llm)

    sep = "-" * 56
    print(f"\nPack result  {run_date}  {len(plans)} plan(s)\n{sep}")
    for plan in plans:
        seen_ids: List[str] = []
        tweet_card_counts: Dict[str, int] = {}
        for card in plan.cards:
            pid = card.source_post_id
            if pid not in seen_ids:
                seen_ids.append(pid)
            tweet_card_counts[pid] = tweet_card_counts.get(pid, 0) + 1

        part_label = f"part {plan.part_no}" if plan.part_no else "single"
        edit_flag = " [needs_edit]" if plan.needs_human_edit else ""
        print(f"  [{part_label}]  {len(seen_ids)} tweets  {len(plan.cards)} cards{edit_flag}")
        char_lens = {"p1": 50, "p2": 135, "p3": 80, "p4": 250}
        for pid in seen_ids:
            n = tweet_card_counts[pid]
            est = estimate_cards({"translation": "x" * char_lens.get(pid, 50)})
            print(f"    {pid}: {n} card(s)  (estimate={est}, tlen={char_lens.get(pid,50)})")
        safe_title = plan.title.encode("ascii", "replace").decode()
        print(f"  title: {safe_title}")
        print(sep)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug-pack", action="store_true",
                        help="打印装箱结果（使用占位 LLM，不消耗 API）")
    args = parser.parse_args()
    if args.debug_pack:
        _debug_pack()
    else:
        parser.print_help()
