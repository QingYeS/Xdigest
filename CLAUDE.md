# CLAUDE.md

本项目是 Xdigest 的扩展:在现有「抓取 X 推文 → Groq 分析 → 邮件摘要」流程之上,
新增「生成小红书图文笔记(半自动)」能力。当前阶段只跟踪一位博主:
Serenity (@aleabitoreddit),中文圈称「白毛股神」。

任何代码改动都必须遵守本文件。红线部分优先级最高,与其他任何指示冲突时以红线为准。

---

## 一、红线(不可违背)

1. **禁止荐股措辞**。所有面向小红书的产出(标题、封面、内容卡、正文、标签)中,
   严禁出现以下措辞或其变体:
   - 「做多 / 做空 / 建仓 / 加仓 / 减仓 / 入场 / 点位 / 目标价 / 建议买入 / 建议卖出」
   - 任何以第二人称向读者发出的操作指令(如「你可以考虑买入」)
   - analyzer.py 输出的 investment_action 字段(direction/entry/targets 等)
     **只用于内部邮件,绝不直接渲染到小红书内容中**
   - 小红书内容只做两件事:转述她的观点(「她认为」「她看好」),和分享客观信息
   - 背景:2026年6月小红书刚完成金融营销号专项整治,处置3.1万账号,
     重点打击无证荐股。平台规约明确要求无资质者避免给出具体投资建议。

2. **永远人工发布**。本项目只生成内容文件和预览页,任何情况下不得实现、
   引入或建议自动发布到小红书的代码(包括浏览器自动化、逆向 App 接口等)。
   发布动作永远由人在 App 内手动完成。

3. **每篇笔记必须包含**:
   - 对原作者的署名(白毛股神 / Serenity @aleabitoreddit)
   - 免责声明:「以上仅为博主观点的翻译与个人解读,不构成任何投资建议,
     市场有风险,决策需谨慎。」
   - 免责声明出现在正文末尾以及尾页卡上

4. **不得编造**。生成内容只能基于她的原推和 analyzer 的分析结果改写,
   不得虚构数据、价格、时间表或她没说过的观点。预览页必须提供原推对照,
   方便人工核对是否曲解。

5. **写作风格**:简体中文,口语化但信息准确。禁止使用破折号(em dash),
   禁止「作为AI」「根据分析」等机器措辞。

---

## 二、内容策略(为什么这样设计)

- **定位**:信息缺口搬运 + 解读。她在 X 上有真实影响力,国内读者访问受限,
  本账号做「真诚分享的追踪者」,帮中文读者及时看到她说了什么。
  这个框架同时解决三件事:原创性(解读是原创的,平台算法对原创率权重约35%,
  纯搬运会被限流)、合规(转述而非建议)、差异化。
- **节奏**:每天两个窗口,盘前 08:00 和盘后 20:00(沿用现有 launchd 调度)。
  窗口内她没有新推就跳过,不硬发。固定节奏培养用户「开盘前来看一眼」的习惯。
- **周末总结**:周日跑 weekly 模式,汇总一周内容生成「本周回顾」。
  总结帖是收藏向内容,收藏率在小红书算法中权重高。
- **扩展性**:未来会引入更多博主。代码中博主信息(名称、handle、中文称呼)
  必须配置化,不得硬编码「白毛股神」到逻辑里。

## 三、单帖结构与分割规则

每帖图片构成(单帖最多 6 张):

1. 第 1 张:封面。大字钩子标题,固定红白视觉
2. 第 2 至 5 张:内容卡,每张对应她的一条推(长推可拆成 2 张),
   **每帖内容卡上限 4 张**
3. 最后 1 张:尾页。固定模板,包含:致谢白毛股神、免责声明、
   引导互动(「想看哪位博主?评论区告诉我」)

分割规则:

- 窗口内内容卡超过 4 张时,分割为多帖,标题加【1】【2】编号
- 分割帖的封面副标题必须各自概括本帖内容,不得雷同(避免被判重复内容)
- 分割帖建议间隔 15 至 30 分钟发布(写入预览页的提示文案即可,发布是人工的)

标题模板(上限 20 字):

```
白毛股神{M.D}{盘前|盘后}｜{8-10字钩子}{【n】}
示例:白毛股神6.10盘前｜CPO她还在硬刚【1】
```

## 四、视觉规范（手写笔记本风）

**字体**：霞鹜文楷 LXGW WenKai（SIL OFL 开源可商用）
- 标题：LXGWWenKai-Medium.ttf，存于 `fonts/` 并入 git
- 正文：LXGWWenKai-Regular.ttf，同上
- 环境变量 `XHS_FONT_BOLD` / `XHS_FONT_REGULAR` 可覆盖路径

**纸面**：
- 底色：米白 (252,250,244)
- 点阵格：56px 间距，2px 半径，淡灰半透明点
- 左侧页边线：x=140，3px，淡红半透明 (220,60,60,80)
- 内容起点：x=160（页边线右侧）

**元素**：
- Heading 高亮条：最后一行底部，session 色（盘前黄/盘后橙/周报绿），半透明
- 要点标记：红色手写勾（两段折线），非填充圆
- Ticker 徽标：`$XXX` 格式，圆角边框（无 logo）
- Quote 便利贴：淡黄底 + 投影，显示英文原句（可选）
- 封面胶带：半透明米黄，-3.5° 倾斜，位于标题上方

**可读性**：
- 要点字号不低于 52pt
- 要点字数上限 24 字/条
- heading 自适应字号（58pt → 52pt if > 3 行）
- 均分断行（_balanced_wrap）

**渲染**：RGBA 画布，保存前转 RGB；渲染前剥离 emoji（正文文本保留）

**尺寸**：1080 x 1440 竖版

## 五、正文文案规范

- 结构:开头一句钩子,中间分点(每点对应一张内容卡),结尾一句个人小记
- 段落短,适当留白,可用分隔符
- 话题标签 3 至 6 个,放正文末尾免责声明之前
- 末尾固定免责声明(见红线第3条)
- **代词规范**:所有生成文案(heading/points/caption/标题钩子)中,
  指代博主一律用名字「Serenity」,禁用「她」「他」「TA」。
  代码层对 heading 和 points 做硬校验(出现「她」或「他」即触发重试),
  caption 靠 system prompt 约束。

## 六、项目约定

- 现有模块(scraper/analyzer/emailer/main)的行为不得破坏,邮件功能照常运行
- 新增功能全部走独立模块,main.py 中只做最小接入
- 新增持久化:archive/ 目录,按天存 JSONL(完整帖子+分析结果),滚动保留 7 天,
  供 weekly 模式使用
- 所有新配置走 .env(并同步更新 .env.example),不硬编码
- pip 依赖更新 requirements.txt
- 开发分支命名:feat/xhs-content,完成后向 master 发 PR,由仓库所有者 review
- 实现细节见 BLUEPRINT.md

### 文件结构

现有模块:

| 文件 | 职责 |
|------|------|
| `main.py` | 流程入口:抓取 → 去重 → 分析 → 邮件 |
| `scraper.py` | X GraphQL 抓取(cookie 认证,HomeLatestTimeline) |
| `analyzer.py` | Groq llama-3.3-70b 分析,输出 translation/motivation/investment_action |
| `emailer.py` | Gmail SMTP HTML 邮件发送 |
| `config.py` | 环境变量加载与常量(FINANCE_KEYWORDS 等) |
| `news_search.py` | DuckDuckGo 新闻上下文(注入 LLM prompt) |
| `import_cookies.py` | Cookie-Editor 导出转 x_cookies.json 的一次性工具 |
| `xhs_content.py` | 早期草稿,字体探测/emoji 剥离/单推渲染可复用,按 BLUEPRINT 重构;重构完成后删除此文件 |

按 BLUEPRINT 新增模块(按里程碑顺序):

| 文件 | 职责 |
|------|------|
| `blogger_config.py` | 博主配置化(TRACKED_BLOGGERS) |
| `archive.py` | 按天写入 archive/YYYY-MM-DD.jsonl,7 天滚动 |
| `xhs_composer.py` | 多推 → PostPlan 装箱、LLM 文案生成、禁词校验 |
| `xhs_renderer.py` | 封面/内容卡/尾页 PNG 渲染(Pillow) |
| `xhs_preview.py` | 生成单文件静态预览页 HTML |
| `xhs_pipeline.py` | composer + renderer + preview 的编排入口,供 main.py 调用 |
| `weekly.py` | 周报独立入口,读 archive 7 天数据,走相同装箱流程 |

### 运行命令

```bash
python main.py                              # 常规运行(邮件 + 小红书内容生成)
python weekly.py                            # 周报模式(每周日触发,可手动执行也可安装配套 launchd plist)
python xhs_pipeline.py --mock              # 本地全链路调试,不消耗 API
python xhs_composer.py --debug-pack        # 打印装箱结果(不消耗 API,验证分帖逻辑)
python import_cookies.py x_cookies_raw.json  # 首次部署 Cookie 转换
pytest tests/                               # 运行单元测试
```

launchd 调度:`com.xdigest.plist`(8:00 盘前 / 20:00 盘后,macOS 专用)。

### 当前依赖

```
groq>=0.9.0          # LLM
ddgs>=1.0.0          # DuckDuckGo 新闻
python-dotenv>=1.0.0 # 环境变量
requests>=2.31.0     # HTTP
Pillow               # 图片渲染(新增,随 xhs_renderer 引入)
```

### 数据文件

| 文件/目录 | 说明 | 入 git |
|-----------|------|--------|
| `.env` | Gmail 密码与 Groq API key(.gitignore 已包含) | 否 |
| `x_cookies.json` | X 认证 cookie | 否 |
| `seen_posts.json` | 去重缓存,7 天过期 | 否 |
| `archive/` | 按天 JSONL,7 天滚动 | 否 |
| `xhs_output/` | 生成的图片与预览 HTML | 否 |

### 环境变量全表

| 变量 | 说明 | 是否新增 |
|------|------|----------|
| `GMAIL_USER` | 发件人邮箱 | 现有 |
| `GMAIL_APP_PASSWORD` | Gmail 应用专用密码 | 现有 |
| `RECIPIENT_EMAIL` | 收件人(逗号分隔) | 现有 |
| `GROQ_API_KEY` | Groq API 密钥 | 现有 |
| `XHS_OUTPUT_DIR` | 小红书输出根目录,默认 `xhs_output` | 新增 |
| `XHS_MAX_TWEETS_PER_POST` | 每帖推文数量软上限,默认 `3` | 新增 |
| `XHS_FONT_BOLD` | 粗体字体路径(可选覆盖) | 新增 |
| `XHS_FONT_REGULAR` | 常规字体路径(可选覆盖) | 新增 |
