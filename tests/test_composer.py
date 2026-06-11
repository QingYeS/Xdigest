"""
pytest tests for xhs_composer.py — all LLM calls are mocked.

覆盖场景:
  装箱:
    1. 5 条短推 → 4+1 两帖
    2. 1 条长推 → 单帖含 2 张卡
    3. 1 条短推 → 单帖含 1 张卡
  禁词校验(plan 级):
    4. plan_llm 首次返回禁词,第二次干净 → 重试成功
    5. plan_llm 三次全命中 → needs_human_edit=True
    6. scan_banned 工具函数正确识别各禁词
  禁词校验(card 级):
    7. card points 含禁词 → 触发 card 重试,重试成功后 needs_human_edit=False
       同时验证重试时 rejected_phrases 传给了 card_llm
  cover_subline 唯一性:
    8. 分割帖各自不同 subline → 不触发 needs_human_edit
    9. 分割帖 subline 重复 → 两帖均标记 needs_human_edit
  LLM 调用契约:
   10. plan_llm 重试时传入 rejected_phrases(含被拒禁词)
  caption/标题格式:
   11. caption 末尾必含免责声明
   12. 单帖标题无分割编号,part_no is None
   13. 分割帖 part_no 1/2,title 含【1】【2】
"""
from datetime import date
from typing import List, Optional

from xhs_composer import DISCLAIMER, BANNED_PRONOUNS, compose, scan_banned, scan_card_violations

# ── 固定数据 ──────────────────────────────────────────────────────────────────

BLOGGER = {"handle": "@aleabitoreddit", "display_name": "Serenity", "cn_name": "白毛股神"}
RUN_DATE = date(2026, 6, 10)

SHORT_TRANSLATION = "她认为英伟达势不可挡。"
LONG_TRANSLATION = "她认为" + "市场分析与前景展望" * 14  # > 120 字


def make_post(post_id: str, translation: str = SHORT_TRANSLATION) -> dict:
    return {
        "id": post_id,
        "handle": "@aleabitoreddit",
        "display_name": "Serenity",
        "content": f"content of {post_id}",
        "timestamp": "2026-06-10T08:00:00Z",
        "translation": translation,
        "motivation": "测试动机",
    }


CLEAN_META = {
    "hook": "她看好科技股",
    "cover_headline": "她看好科技股",
    "cover_subline": "美联储暂停后的机会",
    "caption_body": "盘前总结",
    "hashtags": ["美股", "科技股"],
}


def make_card_llm(heading: str = "测试标题"):
    """返回固定卡片内容的 mock card_llm。"""
    def fn(post: dict, n_cards: int, rejected_phrases: Optional[List[str]] = None):
        return [{"heading": f"{heading}{i+1}", "points": ["要点一", "要点二"]} for i in range(n_cards)]
    return fn


def make_plan_llm(responses: List[dict]):
    """按顺序返回 responses,最后一条重复使用。"""
    calls = [0]
    def fn(cards, session, rejected_phrases: Optional[List[str]] = None):
        idx = min(calls[0], len(responses) - 1)
        calls[0] += 1
        return responses[idx]
    return fn


# ── 1-3: 装箱逻辑 ─────────────────────────────────────────────────────────────

def test_bin_packing_5_short_posts_splits_to_4_plus_1():
    posts = [make_post(f"p{i}") for i in range(5)]
    plans = compose(
        posts, "盘前", BLOGGER,
        run_date=RUN_DATE,
        card_llm=make_card_llm(),
        plan_llm=make_plan_llm([CLEAN_META]),
    )
    assert len(plans) == 2
    assert len(plans[0].cards) == 4
    assert len(plans[1].cards) == 1


def test_long_tweet_generates_2_cards_single_plan():
    posts = [make_post("p1", translation=LONG_TRANSLATION)]
    plans = compose(
        posts, "盘后", BLOGGER,
        run_date=RUN_DATE,
        card_llm=make_card_llm(),
        plan_llm=make_plan_llm([CLEAN_META]),
    )
    assert len(plans) == 1
    assert len(plans[0].cards) == 2


def test_short_tweet_generates_1_card_single_plan():
    posts = [make_post("p1")]
    plans = compose(
        posts, "盘前", BLOGGER,
        run_date=RUN_DATE,
        card_llm=make_card_llm(),
        plan_llm=make_plan_llm([CLEAN_META]),
    )
    assert len(plans) == 1
    assert len(plans[0].cards) == 1


# ── 4-6: 禁词校验(plan 级) ────────────────────────────────────────────────────

def test_banned_phrase_retry_succeeds_on_second_attempt():
    dirty_meta = {**CLEAN_META, "hook": "做多NVDA要火"}
    plans = compose(
        [make_post("p1")], "盘前", BLOGGER,
        run_date=RUN_DATE,
        card_llm=make_card_llm(),
        plan_llm=make_plan_llm([dirty_meta, CLEAN_META]),
    )
    assert not plans[0].needs_human_edit
    assert "做多" not in plans[0].title


def test_banned_phrase_exhausts_retries_marks_needs_human_edit():
    dirty_meta = {**CLEAN_META, "hook": "做多NVDA要火"}
    plans = compose(
        [make_post("p1")], "盘前", BLOGGER,
        run_date=RUN_DATE,
        card_llm=make_card_llm(),
        plan_llm=make_plan_llm([dirty_meta]),
    )
    assert plans[0].needs_human_edit


def test_scan_banned_detects_all_phrases():
    assert scan_banned("她建议做多英伟达入场点位") == ["做多", "入场", "点位"]
    assert scan_banned("她认为市场有机会") == []


# ── 7: 禁词校验(card 级) + 重试原因传递(card) ────────────────────────────────

def test_card_banned_phrase_in_points_triggers_retry_with_reason():
    """
    card points 含禁词时:
    - 触发 card_llm 重试
    - 重试时 rejected_phrases 含被拒禁词(验证 item 3 的 card 侧)
    - 重试成功后 needs_human_edit=False
    """
    received_rejections = []
    call_count = [0]

    def dirty_then_clean(post, n_cards, rejected_phrases=None):
        received_rejections.append(rejected_phrases)
        call_count[0] += 1
        if call_count[0] == 1:
            return [{"heading": "市场分析", "points": ["建议做多 $NVDA", "另一要点"]}]
        return [{"heading": "市场分析", "points": ["Serenity 看好科技股", "另一要点"], "tickers": []}]

    plans = compose(
        [make_post("p1")], "盘前", BLOGGER,
        run_date=RUN_DATE,
        card_llm=dirty_then_clean,
        plan_llm=make_plan_llm([CLEAN_META]),
    )
    assert call_count[0] == 2                      # 重试发生了
    assert received_rejections[0] is None          # 初次调用无历史拒绝
    assert "做多" in received_rejections[1]         # 重试时传入了被拒禁词
    assert not plans[0].needs_human_edit           # 重试成功


# ── 8-9: cover_subline 唯一性 ────────────────────────────────────────────────

def test_split_plans_unique_sublines_are_not_flagged():
    meta_1 = {**CLEAN_META, "cover_subline": "美联储暂停后的机会"}
    meta_2 = {**CLEAN_META, "cover_subline": "科技股后市展望"}
    posts = [make_post(f"p{i}") for i in range(5)]
    plans = compose(
        posts, "盘前", BLOGGER,
        run_date=RUN_DATE,
        card_llm=make_card_llm(),
        plan_llm=make_plan_llm([meta_1, meta_2]),
    )
    assert plans[0].cover_subline != plans[1].cover_subline
    assert not plans[0].needs_human_edit
    assert not plans[1].needs_human_edit


def test_split_plans_duplicate_sublines_both_flagged_needs_human_edit():
    posts = [make_post(f"p{i}") for i in range(5)]
    plans = compose(
        posts, "盘前", BLOGGER,
        run_date=RUN_DATE,
        card_llm=make_card_llm(),
        plan_llm=make_plan_llm([CLEAN_META]),  # 两帖都拿到相同 subline
    )
    assert plans[0].needs_human_edit
    assert plans[1].needs_human_edit


# ── 10: plan_llm 重试时传入 rejected_phrases ────────────────────────────────

def test_plan_llm_receives_rejection_reason_on_retry():
    """
    plan_llm 重试时应接收到含被拒禁词的 rejected_phrases,
    而非无原因的盲目重试。
    """
    received_rejections = []

    def tracking_plan_llm(cards, session, rejected_phrases=None):
        received_rejections.append(rejected_phrases)
        if rejected_phrases is None:
            return {**CLEAN_META, "hook": "做多NVDA要火"}  # 首次返回脏数据
        return CLEAN_META                                    # 收到拒绝原因后返回干净数据

    plans = compose(
        [make_post("p1")], "盘前", BLOGGER,
        run_date=RUN_DATE,
        card_llm=make_card_llm(),
        plan_llm=tracking_plan_llm,
    )
    assert not plans[0].needs_human_edit           # 重试成功
    assert received_rejections[0] is None          # 初次调用无历史拒绝
    assert "做多" in received_rejections[1]         # 重试时传入了被拒禁词


# ── 11-13: caption/标题格式 ───────────────────────────────────────────────────

def test_caption_always_ends_with_disclaimer():
    plans = compose(
        [make_post("p1")], "盘前", BLOGGER,
        run_date=RUN_DATE,
        card_llm=make_card_llm(),
        plan_llm=make_plan_llm([CLEAN_META]),
    )
    assert plans[0].caption.endswith(DISCLAIMER)


def test_single_plan_title_has_no_part_number():
    plans = compose(
        [make_post("p1")], "盘前", BLOGGER,
        run_date=RUN_DATE,
        card_llm=make_card_llm(),
        plan_llm=make_plan_llm([CLEAN_META]),
    )
    assert "【" not in plans[0].title
    assert plans[0].part_no is None


def test_split_plans_have_sequential_part_numbers_in_titles():
    posts = [make_post(f"p{i}") for i in range(5)]
    plans = compose(
        posts, "盘前", BLOGGER,
        run_date=RUN_DATE,
        card_llm=make_card_llm(),
        plan_llm=make_plan_llm([CLEAN_META]),
    )
    assert plans[0].part_no == 1
    assert plans[1].part_no == 2
    assert "【1】" in plans[0].title
    assert "【2】" in plans[1].title


# ── 14-15: 代词校验 ──────────────────────────────────────────────────────────

def test_scan_card_violations_detects_pronouns():
    assert scan_card_violations("她认为英伟达前景乐观") == ["她"]
    assert scan_card_violations("他看好科技股走势") == ["他"]
    assert scan_card_violations("Serenity 认为市场有机会") == []


def test_card_pronoun_in_points_triggers_retry_succeeds():
    """card points 含「她」时触发重试，重试成功后 needs_human_edit=False。"""
    call_count = [0]

    def pronoun_then_clean(post, n_cards, rejected_phrases=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return [{"heading": "市场分析", "points": ["她认为英伟达前景乐观", "要点二"], "tickers": []}]
        return [{"heading": "市场分析", "points": ["Serenity 认为英伟达前景乐观", "要点二"], "tickers": []}]

    plans = compose(
        [make_post("p1")], "盘前", BLOGGER,
        run_date=RUN_DATE,
        card_llm=pronoun_then_clean,
        plan_llm=make_plan_llm([CLEAN_META]),
    )
    assert call_count[0] == 2
    assert not plans[0].needs_human_edit


# ── 16: 分割帖 plan_llm 按 bin 独立调用 ──────────────────────────────────────

def test_split_plans_plan_llm_called_per_bin_with_correct_cards():
    """
    装箱后每个 bin 独立调用一次 plan_llm，传入的 cards 正好是该 bin 的内容，
    两个 bin 的 source_post_id 集合不重叠。
    """
    received = []  # list of [source_post_id, ...]

    def tracking_plan_llm(cards, session, rejected_phrases=None):
        received.append([c.source_post_id for c in cards])
        return CLEAN_META

    posts = [make_post(f"p{i}") for i in range(5)]  # 5 posts -> bins 4+1
    plans = compose(
        posts, "盘前", BLOGGER,
        run_date=RUN_DATE,
        card_llm=make_card_llm(),
        plan_llm=tracking_plan_llm,
    )
    assert len(plans) == 2
    assert len(received) == 2                    # called once per bin
    assert len(received[0]) == 4                 # first bin: 4 cards
    assert len(received[1]) == 1                 # second bin: 1 card
    # no overlap: each source_post_id belongs to exactly one bin
    assert not set(received[0]) & set(received[1])


# ── 17: ticker stance 数据流 ─────────────────────────────────────────────────

def test_card_tickers_neutral_stance_flows_through():
    """无方向性表述时 stance=neutral 应从 LLM 输出直接传递到 ContentCard。"""
    def neutral_card_llm(post, n_cards, rejected_phrases=None):
        return [{"heading": "英伟达市场走势", "points": ["市场观望情绪浓厚", "短期方向不明朗"],
                 "tickers": [{"symbol": "NVDA", "stance": "neutral"}]}]

    plans = compose(
        [make_post("p1")], "盘前", BLOGGER,
        run_date=RUN_DATE,
        card_llm=neutral_card_llm,
        plan_llm=make_plan_llm([CLEAN_META]),
    )
    card = plans[0].cards[0]
    assert len(card.tickers) == 1
    assert card.tickers[0]["symbol"] == "NVDA"
    assert card.tickers[0]["stance"] == "neutral"
