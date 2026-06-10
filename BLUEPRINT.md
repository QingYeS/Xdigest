# BLUEPRINT.md - 小红书内容生成功能实现蓝图

给 Claude Code 的开发任务书。实现前先完整阅读 CLAUDE.md,红线优先级最高。

## 0. 现状

现有流程(不得破坏):

```
launchd (8:00/20:00) → main.py
  → scraper.scrape_following_feed()      # X GraphQL API, cookie 认证
  → 去重 (seen_posts.json, 7天过期)
  → analyzer.analyze_posts()             # Groq llama-3.3-70b, 输出 translation/motivation/investment_action
  → emailer.send_digest()                # Gmail SMTP, HTML 邮件
```

帖子数据结构(analyzer 输出后的每条):

```python
{
  "id": str, "content": str, "display_name": str, "handle": str,
  "timestamp": str,
  "translation": str,        # 中文翻译/要点
  "motivation": str,         # 发帖动机分析
  "investment_action": {     # 仅供邮件使用,禁止进小红书内容
    "summary", "direction", "targets", "timeframe", "entry", "risk"
  }
}
```

注意:当前抓的是整个 following feed 经金融关键词过滤的结果。
本功能只处理目标博主的推,需要按 handle 过滤(见 1.1)。

## 1. 新增模块

### 1.1 blogger_config.py(或并入 config.py)

博主配置化(CLAUDE.md 红线:不硬编码):

```python
TRACKED_BLOGGERS = [
    {
        "handle": "@aleabitoreddit",
        "display_name": "Serenity",
        "cn_name": "白毛股神",
        "enabled": True,
    },
]
```

提供 `filter_tracked(posts) -> dict[handle, list[post]]`。

### 1.2 archive.py

- `append_posts(analyzed: list[dict])`:按天写入 `archive/YYYY-MM-DD.jsonl`,
  每行一条完整的帖子+分析。同 id 不重复写。
- `prune(days=7)`:删除 7 天前的文件。
- `load_range(start_date, end_date) -> list[dict]`:weekly 模式读取用。
- main.py 每次运行在分析完成后调用 append + prune。

### 1.3 xhs_composer.py(核心,改造自现有草稿 xhs_content.py)

职责:把一个时间窗的多条推合成 1 个或多个「帖子计划(PostPlan)」。

```python
@dataclass
class ContentCard:
    source_post_id: str
    heading: str          # 卡片标题, ≤14字
    points: list[str]     # 2-4 个要点, 每条 ≤28字
    part: int = 1         # 长推拆分时的页码

@dataclass
class PostPlan:
    title: str            # 含模板: 白毛股神{M.D}{盘前|盘后}｜{钩子}{【n】}
    cover_headline: str   # ≤12字
    cover_subline: str    # ≤16字, 分割帖之间必须不同
    cards: list[ContentCard]   # 1-4 张
    caption: str          # 正文文案(含标签+免责声明)
    session: str          # "盘前" | "盘后" | "周报"
    part_no: int | None   # 分割编号, 无分割为 None
```

流程:

1. `compose(posts, session) -> list[PostPlan]`
2. 第一次 LLM 调用:对每条推生成 1-2 张 ContentCard 的文案
   (长推判定:translation 超过约 120 字或要点超过 4 个时拆 2 张)
3. 装箱:按时间顺序把卡片装入帖子,每帖上限 4 张卡,溢出则开新帖
4. 第二次 LLM 调用:对每个帖子生成 title 钩子、cover 文案、caption 正文
5. 校验(代码层硬校验,不依赖 LLM 自觉):
   - 禁词扫描:做多/做空/建仓/入场/点位/目标价/买入/卖出 等
     (维护 BANNED_PHRASES 列表),命中则带着错误信息重新生成,最多 2 次,
     仍失败则该帖标记 needs_human_edit 并在预览页醒目提示
   - 标题 ≤20 字;分割帖 cover_subline 两两不同
   - caption 末尾必须含免责声明(代码追加,不靠 LLM)

LLM prompt 要点(写进 prompt 的系统约束):

- 人设:真诚的追踪者,帮中文读者看懂她说了什么,不是投顾
- 只能转述(「她认为」「她觉得」「她看好」),不得替读者做判断
- 禁止虚构数据;只能使用 translation/motivation 中已有的信息
- 口语化、短句、可少量 emoji;禁止破折号;禁止机器措辞

### 1.4 xhs_renderer.py(改造自草稿中的 _render_card)

- `render_cover(plan) -> png`
- `render_card(card) -> png`:heading + 要点列表的结构化排版
- `render_tail() -> png`:固定尾页(致谢 + 免责 + 评论区互动引导),
  内容不变可缓存一张复用
- 视觉规范见 CLAUDE.md 第四节;字体探测逻辑沿用草稿
  (macOS PingFang / Linux Noto CJK,XHS_FONT_* 环境变量可覆盖)
- 渲染前对所有上图文本调用 strip_emoji(草稿中已有实现)

### 1.5 xhs_preview.py

生成 `xhs_output/{YYYY-MM-DD_HHMM}/preview.html`,纯静态、零依赖、
双击可开(图片用相对路径,JS 内联)。

页面结构(单文件 HTML):

- 顶部:运行时间、窗口(盘前/盘后/周报)、帖子数量
- 每个 PostPlan 一个区块,左右两栏:
  - 左栏「手机模拟框」(宽约 390px,圆角边框):
    依次展示封面图、内容卡(可横向滑动或纵向排列)、尾页图、
    标题文本、caption 全文
  - 右栏「原推对照」:每张内容卡对应的原推(英文原文 + translation),
    标注 source_post_id,供人工核对是否曲解、是否编造
- 每个帖子区块的操作:
  - 「复制标题」「复制正文」按钮(navigator.clipboard,内联 JS)
  - 图片本身右键即可另存,图下标注文件名
  - needs_human_edit 的帖子整块红色边框 + 顶部警告条
- 分割帖之间显示提示:「建议与上一帖间隔 15-30 分钟发布」
- 页面底部:本次运行的禁词扫描报告(扫了哪些词、是否命中)

### 1.6 weekly.py

- 入口:`python3 weekly.py`(单独的 launchd plist,周日上午跑,
  plist 模板一并提供但安装由人决定)
- 读 archive 近 7 天 → 按主题聚类(LLM 一次调用,输出 3-5 个主题线索,
  每个主题含涉及的推 id 列表)→ 走 composer 同样的装箱与校验逻辑
  生成「白毛股神本周回顾」PostPlan → 渲染 → 预览页
- 周报封面副标题固定格式:{M.D}-{M.D} 一周回顾

## 2. main.py 接入(最小改动)

```python
# run() 内, send_digest(analyzed) 之后:
from blogger_config import filter_tracked
from archive import append_posts, prune
from xhs_pipeline import generate_xhs   # composer+renderer+preview 的编排入口

append_posts(analyzed)
prune()
tracked = filter_tracked(analyzed)
if tracked:
    session = "盘前" if datetime.now(LOCAL_TZ).hour < 12 else "盘后"
    generate_xhs(tracked, session)
```

xhs 流程的任何异常不得影响邮件流程(整体 try/except,失败打日志即可)。

## 3. 配置与依赖

.env 新增(同步 .env.example):

```
XHS_OUTPUT_DIR=xhs_output      # 输出根目录
XHS_MAX_CARDS_PER_POST=4       # 每帖内容卡上限
XHS_FONT_BOLD=                 # 可选, 字体覆盖
XHS_FONT_REGULAR=
```

requirements.txt 新增:Pillow

.gitignore 新增:xhs_output/、archive/

## 4. 测试要求

- composer:禁词校验单测(构造含「做多 $NVDA」的 LLM 假输出,断言被拦截);
  装箱逻辑单测(5 张卡 → 分成 4+1 两帖;长推 → 2 张卡)
- renderer:冒烟测试用 mock 数据出图,不依赖 Groq(草稿已有此模式,保留)
- preview:生成后用断言检查 HTML 含全部图片引用与免责声明文本
- 全链路:提供 `python3 xhs_pipeline.py --mock` 用 fixtures 里的样例数据
  跑通 composer → renderer → preview,便于不消耗 API 的本地调试

## 5. 里程碑(按序实现,每步可独立验证)

1. archive.py + main.py 接入(先把数据存起来)
2. composer 的卡片生成与装箱 + 禁词校验(纯逻辑可先用 mock LLM);完成后删除 xhs_content.py
3. renderer 三类图(cover/card/tail)
4. preview.html
5. main.py 全链路接通 + --mock 模式
6. weekly.py
7. 文档:README 增补「小红书内容生成」章节(说明半自动定位与人工发布流程)

## 6. 现有草稿

repo 外有一版早期草稿 xhs_content.py(单推单笔记的旧设计),其中可复用:
字体探测、emoji 剥离、卡片渲染基础、懒加载 Groq client。
按本蓝图的多卡/装箱/合规校验架构重构,不要按旧设计实现。
