from __future__ import annotations
import json
import re
import time
from groq import Groq

from config import GROQ_API_KEY
from news_search import build_news_context

_client = Groq(api_key=GROQ_API_KEY)

MODEL = "llama-3.3-70b-versatile"
MAX_POSTS_PER_RUN = 20

_SYSTEM = (
    "你是一位专业的投资分析师，精通全球金融市场、宏观经济和加密货币。"
    "你善于结合最新市场动态和新闻背景，对社交媒体帖子进行深度解读，"
    "并给出具体可操作的投资建议。"
)


def analyze_post(post: dict) -> dict:
    news_context = build_news_context(post["content"])

    prompt = f"""请分析以下来自 X(Twitter) 的帖子：

发布者：{post['display_name']} ({post['handle']})
发布时间：{post['timestamp']}
原文内容：
{post['content']}

{news_context}

请严格按以下 JSON 格式回复，不要输出其他内容：
{{
  "translation": "直接输出中文内容，不加任何前缀标签。短帖（500字以内）逐句直译；长帖提炼核心要点，分点列出，不超过300字",
  "motivation": "发帖动机分析（100字以内）：结合上方新闻背景，分析作者为什么在此时发这条帖子，包括其可能掌握的信息、情绪倾向、以及与当前市场事件的关联",
  "investment_action": {{
    "summary": "一句话总结投资建议",
    "direction": "做多 / 做空 / 观望 / 减仓",
    "targets": "具体标的（股票代码、加密货币、ETF等）",
    "timeframe": "短期（数日）/ 中期（数周）/ 长期（数月）",
    "entry": "可推断的入场时机或价位（如无法推断则写'待确认'）",
    "risk": "主要风险提示（50字以内）"
  }}
}}"""

    for attempt in range(3):
        try:
            resp = _client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=4096,
            )
            raw = resp.choices[0].message.content.strip()
            start = raw.find("{")
            end = raw.rfind("}") + 1
            result = json.loads(raw[start:end])
            # 去掉模型可能输出的"中文翻译："等前缀
            if "translation" in result:
                result["translation"] = re.sub(
                    r"^(中文翻译[：:]?\s*|翻译[：:]?\s*)", "", result["translation"]
                ).strip()
            return result
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate" in msg.lower():
                wait = 30 * (attempt + 1)
                print(f"    ⏳ 限速，等待 {wait} 秒...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("多次重试后仍失败")


def analyze_posts(posts: list[dict]) -> list[dict]:
    if len(posts) > MAX_POSTS_PER_RUN:
        print(f"  帖子数 {len(posts)} 超过上限，只分析最新 {MAX_POSTS_PER_RUN} 条")
        posts = posts[:MAX_POSTS_PER_RUN]

    results = []
    for i, post in enumerate(posts, 1):
        print(f"  分析帖子 {i}/{len(posts)}: {post['handle']}")
        try:
            analysis = analyze_post(post)
            results.append({**post, **analysis})
        except Exception as e:
            import traceback
            print(f"    ⚠ 分析失败: {e}")
            print(traceback.format_exc())
        finally:
            if i < len(posts):
                time.sleep(3)  # 避免触发 Groq TPM 限额
        if len(results) < i:  # 失败时补充占位
            results.append({
                **post,
                "translation": post["content"],
                "motivation": "分析失败",
                "investment_action": {
                    "summary": "分析失败", "direction": "-",
                    "targets": "-", "timeframe": "-",
                    "entry": "-", "risk": "-",
                },
            })
    return results
