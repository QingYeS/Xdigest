"""
regenerate_xhs.py: 调试入口 — 从 archive 读已分析的帖子，跳过抓取和 Groq 分析，
直接重跑 xhs 流程（组装 → 渲染 → 预览）。

ContentCard sidecar 缓存 (archive/YYYY-MM-DD.cards.jsonl)：
  第一次运行时 card_llm 正常调用，结果写入 sidecar。
  后续运行命中缓存则跳过 card_llm，只重跑 plan_llm，节省 token。
  --refresh-cards 强制忽略缓存、重跑 card_llm 并覆写 sidecar。

用法:
    python regenerate_xhs.py --date 2026-06-11 --session 盘后
    python regenerate_xhs.py --date 2026-06-11 --session 盘后 --only 2065105141238489398
    python regenerate_xhs.py --date 2026-06-11 --session 盘后 --only XXX --refresh-cards
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from archive import ARCHIVE_DIR, load_range
from xhs_composer import ContentCard
from xhs_pipeline import _make_card_llm, generate_xhs


# ── Sidecar 读写 ──────────────────────────────────────────────────────────────

def _sidecar_path(run_date: date) -> Path:
    return ARCHIVE_DIR / f"{run_date.isoformat()}.cards.jsonl"


def _load_sidecar(run_date: date) -> dict:
    """从 sidecar 加载缓存，返回 {post_id: [ContentCard, ...]}。"""
    path = _sidecar_path(run_date)
    result = {}
    if not path.exists():
        return result
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                post_id = entry["post_id"]
                # tickers 字段类型为 List[dict]（非嵌套 dataclass），ContentCard(**d) 直接可用
                result[post_id] = [ContentCard(**c) for c in entry["cards"]]
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"[sidecar] 跳过损坏行: {e}")
    return result


def _write_sidecar(run_date: date, cache: dict) -> None:
    """全量覆写 sidecar，写完做 round-trip 验证。"""
    ARCHIVE_DIR.mkdir(exist_ok=True)
    path = _sidecar_path(run_date)
    with open(path, "w", encoding="utf-8") as f:
        for post_id, cards in cache.items():
            entry = {"post_id": post_id, "cards": [asdict(c) for c in cards]}
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Round-trip 验证：读回比对，确保序列化/反序列化无损
    loaded = _load_sidecar(run_date)
    for post_id, orig_cards in cache.items():
        rt_dicts = [asdict(c) for c in loaded.get(post_id, [])]
        orig_dicts = [asdict(c) for c in orig_cards]
        if rt_dicts != orig_dicts:
            print(f"[sidecar] 警告: post_id={post_id} round-trip 不一致!")
            return
    print(f"[sidecar] 写入 {path.name}，共 {len(cache)} 条，round-trip OK")


# ── 带缓存的 card_llm 工厂 ────────────────────────────────────────────────────

def _make_cached_card_llm(real_card_llm, cache: dict, run_date: date, refresh: bool):
    """
    包装真实 card_llm，增加 sidecar 缓存逻辑：
    - 第一次调用（rejected_phrases=None）且缓存命中：直接返回 raw dicts，跳过真实调用
    - 第一次调用且缓存未命中：调用真实 card_llm，保存 ContentCards 到 sidecar
    - 重试调用（rejected_phrases 不为 None）：透传真实 card_llm，不读写缓存
      （避免将含禁词的内容存入缓存）
    """
    def cached(post, rejected_phrases=None):
        post_id = post["id"]
        is_retry = rejected_phrases is not None

        if not is_retry and not refresh and post_id in cache:
            print(f"[sidecar] 命中缓存 post_id={post_id}，跳过 card_llm")
            c = cache[post_id][0]
            return {"heading": c.heading, "points": c.points, "tickers": c.tickers}

        raw = real_card_llm(post, rejected_phrases=rejected_phrases)

        # 只在第一次调用时写入缓存，重试调用不覆写
        if not is_retry:
            card = ContentCard(
                source_post_id=post_id,
                heading=raw["heading"],
                points=list(raw["points"]),
                part=1,
                tickers=list(raw.get("tickers", [])),
                full_original=post.get("content", ""),
                full_translation=post.get("translation", ""),
            )
            cache[post_id] = [card]
            _write_sidecar(run_date, cache)

        return raw

    return cached


# ── 主入口 ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="从 archive 重跑 xhs 生成流程（跳过抓取和 Groq 分析）"
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        metavar="YYYY-MM-DD",
        help="读取哪天的 archive（默认今天）",
    )
    parser.add_argument(
        "--session",
        default="盘后",
        choices=["盘前", "盘后", "周报"],
        help="发帖时段（默认 盘后）",
    )
    parser.add_argument(
        "--only",
        metavar="POST_ID",
        default=None,
        help="只重跑指定 post_id 的帖子",
    )
    parser.add_argument(
        "--refresh-cards",
        action="store_true",
        help="忽略 sidecar 缓存，强制重跑 card_llm 并覆写缓存",
    )
    args = parser.parse_args()

    try:
        run_date = date.fromisoformat(args.date)
    except ValueError:
        print(f"[error] --date 格式错误: {args.date!r}，应为 YYYY-MM-DD")
        sys.exit(1)

    posts = load_range(run_date, run_date)
    if not posts:
        print(f"[regenerate] archive/{args.date}.jsonl 不存在或为空，退出")
        sys.exit(0)

    print(f"[regenerate] 读取 {args.date} archive，共 {len(posts)} 条")

    if args.only:
        posts = [p for p in posts if p.get("id") == args.only]
        if not posts:
            print(f"[regenerate] 未找到 post_id={args.only!r}，退出")
            sys.exit(1)
        print(f"[regenerate] --only 过滤后剩余 {len(posts)} 条")

    # 加载 sidecar（--refresh-cards 时保留其他 post 的缓存条目，仅对当前 post 强制重跑）
    cache = _load_sidecar(run_date)
    if cache:
        hit_ids = [p["id"] for p in posts if p["id"] in cache]
        if args.refresh_cards:
            print(f"[sidecar] --refresh-cards，忽略 {len(hit_ids)} 条缓存，强制重跑 card_llm")
        elif hit_ids:
            print(f"[sidecar] {len(hit_ids)} 条命中缓存，将跳过 card_llm")
        else:
            print(f"[sidecar] 无命中，card_llm 正常调用")
    else:
        print(f"[sidecar] 无 sidecar 文件，card_llm 正常调用")

    from groq import Groq
    from config import GROQ_API_KEY
    client = Groq(api_key=GROQ_API_KEY)
    model = "llama-3.3-70b-versatile"

    cached_card_llm = _make_cached_card_llm(
        _make_card_llm(client, model),
        cache,
        run_date,
        refresh=args.refresh_cards,
    )

    out_dir = generate_xhs(posts, args.session, card_llm=cached_card_llm)
    print(f"[regenerate] 完成，输出目录: {out_dir}")


if __name__ == "__main__":
    main()
