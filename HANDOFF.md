# 交接说明 — 小红书内容生成功能(feat/xhs-content 分支)

> 给接手开发的 Claude Code agent。本分支由协作者(Jinge)开发,在原 Xdigest
> 邮件项目上新增「小红书图文笔记生成」功能。请先读完本文,再动手。
> 当前阶段:结构与视觉已完成,**文案质量待打磨**(这是接下来的主要工作)。
> 暂不 merge 到 master,直接在本分支继续开发。

---

## 0. 接手第一步(按顺序做)

```bash
git fetch origin
git checkout feat/xhs-content
pip install -r requirements.txt   # 新增了 Pillow 等依赖,必须装
pytest tests/                     # 确认全绿(约 50+ 测试),验证环境 OK
```

**关键验证**:确认没有破坏原有邮件功能。
```bash
python main.py --no-email --force   # 跑全链路但不发邮件,看是否正常生成
```
注意:上面这条 `--force` 会重新分析所有帖子,**只在首次环境验证时跑一次即可,
不要反复跑**(原因见下方 token 纪律)。
若 import 阶段报错(尤其 `str | None` 之类 TypeError),检查 Python 版本:
本功能需要 Python ≥ 3.9,且部分文件依赖 `from __future__ import annotations`,
请勿删除这些 import。

---

## ⚠️ Token 使用纪律(务必遵守)

**Groq 用的是免费层,每日额度有限,且 Developer 升级通道目前官方关闭、无法升级。**
因此调试时必须有计划地用额度,否则当天额度很快耗尽,陷入限流(60→120→180s
退避后失败),一整天无法继续。

铁律:
1. **测试只用 1-2 条推作为实例,绝不全量跑。** 调文案 prompt 时,看 1-2 条
   样本的生成效果就足以判断好坏,没有必要每次跑全部帖子。
2. **优先用"不重新分析"的方式调试**(见第 5 节):从 archive 读已分析好的帖子,
   跳过最贵的 analyzer 调用。
3. **`--force` 会重新分析全部帖子,是最烧额度的操作**,仅用于首次环境验证,
   日常调试不要用。
4. 撞到限流退避(看到 `等待 60s/120s/180s`)说明额度快尽了,**立即停手**,
   不要硬等,改天额度重置后再继续,或减少调用量。

---

## 1. 这个功能是什么

在现有「抓 X → Groq 分析 → 发邮件」流程之上,新增「生成小红书图文笔记」。

- **半自动**:只生成图片 + 本地预览页(`xhs_output/<时间戳>/preview.html`),
  **永不自动发布**。人工 review 后手动发到小红书。
- **追踪对象**:目前只有一位博主 Serenity(@aleabitoreddit,中文称「白毛股神」)。
  配置在 `blogger_config.py` 的 `TRACKED_BLOGGERS`,未来加博主改这里即可。
- **内容形态**:图片卡 = 她单条推的完整中文翻译(全量)+ 英文原文节选;
  正文 note = 「投资笔记」人设的原创解读(LLM 按 blogger_config 的 `note_persona`
  写,只返回 `note_body` + `hashtags`,标题/封面均由代码模板生成)。
  视觉是手写笔记本风(霞鹜文楷字体 + 点阵纸 + 荧光笔 + ticker 徽章 + 便利贴)。

---

## 2. 对原有邮件功能的影响(重要)

- **邮件发送功能完好**,`send_digest` 仍在 `main.py` 中、在 xhs 之前执行,
  xhs 流程包在 try/except 里,xhs 失败不影响邮件。
- **一处行为变更**:新增全局 source 过滤 `FILTER_SOURCE_GLOBALLY`(默认 True),
  邮件内容从「全部金融推」变为「仅 TRACKED_BLOGGERS 的推」。
  这是有意设计(账号专注追踪特定博主)。如需恢复旧行为(邮件看全部金融推),
  在 `.env` 设 `FILTER_SOURCE_GLOBALLY=false`。

---

## 3. 已完成 / 已定稿(勿随意改动)

这些经过反复迭代和真实数据验证,已定稿:

- **结构**:推组装箱(每帖 ≤3 条推、≤18 张图)、长推自动分页、单推卡片原子不可分、
  超限自动分帖(标题加【1】【2】、正文有衔接句)
- **视觉**:手写笔记本风(配色/字体/荧光笔按盘前黄·盘后橙·周报绿/红色对勾/
  ticker 三态着色:看多淡红·看空淡绿·中性蓝灰,A股惯例红涨绿跌,不加颜色说明)
- **合规红线**(不可违背,详见 CLAUDE.md):
  - 禁止荐股措辞(做多/做空/入场/点位等),analyzer 的 investment_action 只进邮件
    不进小红书内容
  - 永远人工发布,不实现任何自动发布代码
  - 每篇含署名 + 免责声明;不得编造(译文严格对应原文)
  - 代词用「Serenity」,禁用「她/他」(博主性别未知)
- **翻译**:全量直译,真实数据验证忠实无幻觉
- **标题纯模板化**:`PostPlan.title` 已改为代码生成,格式固定为
  `白毛股神(Serenity)po文翻译 | 截止至 {M.D} {时间} EST{【N】}`;
  `SESSION_TIME_EST` 常量在 `xhs_composer.py` 顶部,不经 LLM。
  已真实验证多帖分割(【1】【2】【3】)和盘前/盘后时间映射。
- **正文字段重命名(caption → note)**:`PostPlan.caption` → `PostPlan.note`,
  `plan_llm` JSON schema 字段 `caption_body` → `note_body`,全量代码及测试已同步
  (63 tests passed)。CSS 类名 `phone-note`/`note-body` 等也已更新。
- **plan_llm schema 瘦身**:清除了 `hook`/`cover_headline`/`cover_subline` 三个
  早已由代码生成、LLM 输出被忽略的字段;schema 仅剩 `{"note_body":"...","hashtags":["..."]}`,
  system prompt 规则相应重编号。
- **正文「投资笔记」人设**:plan_llm 系统提示加入按 `note_persona` 注入的博主专属
  写作风格,LLM 正文不再"机器味",已真实运行验证输出(如「看来大神还是很看好 $XFAB」)。

---

## 4. 待打磨(当前状态与后续方向)

**标题 hook 问题已解决**:标题现在纯模板生成,不再依赖 LLM,
空泛标题问题从根本上消除。

当前文案质量的主要待打磨点:

### 正文(note)口吻
「投资笔记」人设已注入,但 note_persona 细节和 system prompt 措辞仍有调整空间。
判断标准:正文读起来像「认真追踪白毛股神的普通投资者分享」,不像内容营销机器人。
可以在不消耗额外 card_llm 额度的情况下只重跑 plan_llm(从 archive 重读已分析帖)。

### 内容卡 heading 与 points 措辞
card_llm 生成的 heading 有时过于笼统(如「市场分析」),points 偶有重叠。
打磨方向:heading 用具体 ticker/事件,points 信息密度高、不重复。
注意 heading 和 points 均有禁词 + 代词硬校验(「她/他」会触发重试)。

### hashtag 质量
plan_llm 生成的 hashtag 目前基本合规,但与内容相关性有时偏弱。
可以在 system prompt 里加示例引导,不需要改结构。

---

## 5. 调试时的重要注意事项

**核心纪律:测试用最少的调用,只跑实例,不跑全量**(详见上方「Token 使用纪律」)。
调文案只需 1-2 条推就能看出效果,务必有计划地用 Groq 每日额度。

- **Groq 免费层限流是主要障碍**:免费层 6K TPM,本项目长 prompt 一次吃半个额度,
  反复跑容易撞限流(出现 60→120→180s 退避后失败)。Developer 升级通道目前
  官方关闭,无法升级,只能在免费额度内有计划地用。
  应对:**调试时用单条推**(给调试入口加 `--only <post_id>` 参数,只跑一条看效果),
  这是当前最重要的省额度手段。
- **从 archive 重生成(已实现)**:`regenerate_xhs.py` 从 `archive/<日期>.jsonl` 读
  已分析好的帖子,跳过抓取和 analyzer(最贵的一步),只重跑 xhs 内容生成。
  用法:`python regenerate_xhs.py --date 2026-06-11 --session 盘后`。
  调文案 prompt 时优先用这个,基本不消耗 analyzer token。
- **Windows 上 `conda run` 中文问题(已知 bug)**:
  `conda run -n xdigest python <script>.py` 传入中文参数或输出含中文时,
  conda 内部 `print(response.stdout)` 触发 `UnicodeEncodeError: 'charmap' codec`
  (Windows cp1252 编码限制)。**解决方案**:直接用完整 Python 路径调用:
  `C:\Users\Jinge\anaconda3\envs\xdigest\python.exe <script>.py`,
  中文命令行参数同样失效,改用文件传参或脚本内部硬编码日期/session。
- **判断生成质量,1-2 条有代表性的推(如一条长推 + 一条短推)就够**,
  不需要每次都看全部 8 条的输出。

---

## 6. 关键文件速查

| 文件 | 职责 |
|------|------|
| `main.py` | 入口:抓取→去重→分析→邮件→xhs(--no-email/--force 开关) |
| `xhs_pipeline.py` | xhs 编排入口 generate_xhs();含 card_llm / plan_llm 调用与 prompt |
| `xhs_composer.py` | 装箱、数据类、禁词/代词校验;`SESSION_TIME_EST` 常量与 `_build_title()` |
| `xhs_renderer.py` | PNG 渲染(Pillow + LXGW 字体) |
| `xhs_preview.py` | 静态预览页 HTML(手机模拟 + 原推对照 + 复制按钮) |
| `blogger_config.py` | TRACKED_BLOGGERS 配置 + filter_tracked() + note_persona |
| `archive.py` | 按天存 analyzer 输出,7天滚动 |
| `regenerate_xhs.py` | 从 archive 重新生成 xhs 内容(跳过抓取和分析,调试利器) |
| `CLAUDE.md` | 项目约定 + 合规红线(权威,优先级最高) |

命令:
- `python main.py` — 正常运行(邮件 + xhs)
- `python main.py --no-email` — 不发邮件(测试用)
- `python main.py --no-email --force` — 跳过去重(反复测试,但会重新分析烧 token)
- `python regenerate_xhs.py --date 2026-06-11 --session 盘后` — 从 archive 重生成 xhs(不烧 analyzer token)
- `pytest tests/` — 单元测试

---

## 7. 协作约定

- 开发继续在 `feat/xhs-content` 分支,**暂不 merge**,等文案打磨到可发布再整体
  merge 进 master(保持 master 始终干净可用)。
- 一次只改一处、做完验证(尤其看图、看真实生成输出)再继续,不要一口气改多处。
- 改动 CLAUDE.md 红线相关内容前请先与协作者确认。
- 该分支历史里有一条早期误提交 `f952141 "ready to merge"`(空 message),
  最终 merge 时建议用 squash 合并。
- 写作避免破折号(em dash)和 AI 腔。
