# X Investment Digest

Automatically scrapes your X (Twitter) Following feed every 12 hours, filters investment/finance-related posts, analyzes them with AI, and delivers a formatted HTML email digest in Chinese.

**What you get in each email:**
- Original post content, author, and timestamp
- Chinese translation
- Analysis of why the author likely posted it (with real-time news context)
- Structured investment recommendation (direction, targets, timeframe, entry, risk)

Emails are sent at **8:00 AM and 8:00 PM** daily. If there's no relevant content, you still get a "nothing new" notification. If something breaks (e.g. expired cookies), you get an error alert with instructions.

---

## Project Structure

```
X/
├── main.py              # Entry point — orchestrates scrape → filter → analyze → send
├── scraper.py           # Calls X's internal GraphQL API with cookie auth
├── analyzer.py          # Groq LLM analysis (translation, motivation, investment action)
├── emailer.py           # Builds and sends HTML email via Gmail SMTP
├── news_search.py       # DuckDuckGo news search for real-time context
├── config.py            # Loads .env, defines finance keyword list
├── import_cookies.py    # Converts Cookie-Editor export → requests-compatible format
├── com.xdigest.plist    # macOS launchd schedule (8am / 8pm daily)
├── requirements.txt
├── .env.example         # Template for secrets
└── logs/                # stdout.log / stderr.log (auto-created)
```

---

## Prerequisites

- **macOS** (for launchd scheduling; the scraper itself works on any OS)
- **Python 3.10+** (tested with Anaconda `/opt/anaconda3/bin/python3`)
- **A Gmail account** with [App Password](https://myaccount.google.com/apppasswords) enabled (requires 2FA)
- **A Groq API key** — free tier at [console.groq.com](https://console.groq.com)
- **An X account** with the accounts you want to follow already set up

---

## Quick Start

### 1. Clone and install dependencies

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd X
pip install -r requirements.txt
```

### 2. Configure secrets

```bash
cp .env.example .env
```

Edit `.env` with your values:

```env
GMAIL_USER=your_sender@gmail.com
GMAIL_APP_PASSWORD=your_16_char_app_password
RECIPIENT_EMAIL=you@example.com,other@example.com
GROQ_API_KEY=gsk_...
```

`RECIPIENT_EMAIL` accepts a comma-separated list.

### 3. Export your X cookies

The scraper authenticates using cookies from your logged-in Chrome browser — no password needed.

1. Install the [Cookie-Editor](https://cookie-editor.com) Chrome extension
2. Go to [x.com](https://x.com) and make sure you're logged in
3. Click the Cookie-Editor icon → **Export** → **Export as JSON**
4. Save the file as `x_cookies_raw.json` in this project directory
5. Convert to the required format:

```bash
python3 import_cookies.py x_cookies_raw.json
```

This creates `x_cookies.json`. Cookies typically last **a few weeks**; you'll receive an email alert when they expire.

### 4. Run a manual test

```bash
python3 main.py
```

You should see output like:
```
[2026-06-10 08:00 EDT] 开始抓取 X Following Feed...
获取 88 条推文，12小时内 12 条，投资相关 5 条
去重后剩余 5 条新帖子
正在用 Groq 分析帖子...
  分析帖子 1/5: @somehandle
  ...
✓ 邮件已发送至 you@example.com（共 5 条帖子）
✓ 完成
```

### 5. Schedule with launchd (macOS)

First, update the hardcoded paths in `com.xdigest.plist` to match your username and Python path:

```bash
# Replace 'qing' with your macOS username
sed -i '' 's|/Users/qing/X|/Users/YOUR_USERNAME/X|g' com.xdigest.plist

# If your Python is not at /opt/anaconda3/bin/python3, update that too
which python3   # find your python path
```

Then install:

```bash
mkdir -p logs
cp com.xdigest.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.xdigest.plist
```

To uninstall:

```bash
launchctl unload ~/Library/LaunchAgents/com.xdigest.plist
rm ~/Library/LaunchAgents/com.xdigest.plist
```

---

## How It Works

1. **Scraper** calls X's internal `HomeLatestTimeline` GraphQL API using your session cookies — the same endpoint the X web app uses. No Playwright or browser automation involved.
2. Posts from the past 12 hours are filtered against a keyword list (English + Chinese finance terms).
3. A deduplication file (`seen_posts.json`) prevents the same post from being analyzed twice across runs.
4. Each new post is analyzed by **Groq** (`llama-3.3-70b-versatile`) with DuckDuckGo news context injected into the prompt.
5. Results are formatted as a styled HTML email and sent individually to each recipient.

> The X GraphQL `queryId` changes with each X deployment. The scraper has several hardcoded fallback IDs and will auto-discover the current one from X's JS bundle if all fail.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `FileNotFoundError: x_cookies.json` | Cookies not imported | Run `python3 import_cookies.py` |
| `ValueError: ct0 cookie missing` | Cookie export incomplete | Re-export from Cookie-Editor and re-import |
| HTTP 401 / 403 from X API | Session cookies expired | Re-export cookies from Chrome and re-import |
| `429 rate limit` from Groq | Too many requests | Analyzer auto-retries with backoff |
| Email not received | Gmail App Password wrong, or recipient in spam | Check `.env`, check spam folder |

---

## Finance Keywords

The filter covers ~80 English and Chinese terms including: `invest`, `stock`, `crypto`, `ETF`, `Fed`, `earnings`, `bull`, `bear`, `portfolio`, `inflation`, `投资`, `股票`, `加密`, `期权`, `美联储`, and more. Edit `FINANCE_KEYWORDS` in [config.py](config.py) to customize.

---

## License

MIT
