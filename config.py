import os
from dotenv import load_dotenv

load_dotenv()

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", GMAIL_USER)
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

COOKIES_FILE = os.path.join(os.path.dirname(__file__), "x_cookies.json")
SEEN_POSTS_FILE = os.path.join(os.path.dirname(__file__), "seen_posts.json")

FINANCE_KEYWORDS = {
    # English
    "invest", "stock", "market", "portfolio", "trade", "trading", "fund",
    "crypto", "bitcoin", "btc", "eth", "ethereum", "defi", "yield",
    "dividend", "earnings", "revenue", "profit", "bull", "bear",
    "rally", "correction", "recession", "inflation", "interest rate",
    "wealth", "financial", "finance", "money", "asset", "equity", "bond",
    "etf", "ipo", "venture", "capital", "hedge fund", "short", "long",
    "position", "leverage", "margin", "options", "futures", "derivatives",
    "roi", "return", "alpha", "beta", "volatility", "sp500", "nasdaq",
    "nyse", "fed", "fomc", "gdp", "cpi", "pce", "treasury",
    "valuation", "p/e", "pe ratio", "earnings per share", "eps",
    "buyback", "m&a", "acquisition", "ipo", "spac", "aum",
    "passive income", "cash flow", "net worth", "fire", "retire early",
    # Tickers commonly discussed
    "aapl", "tsla", "nvda", "msft", "amzn", "googl", "meta", "baba",
    "qqq", "spy", "voo", "ark", "coinbase", "solana", "sol",
    # Chinese
    "投资", "股票", "股市", "市场", "基金", "加密货币", "比特币", "以太坊",
    "财富", "金融", "理财", "收益", "利润", "牛市", "熊市", "套利",
    "仓位", "杠杆", "期权", "期货", "分红", "净值", "估值", "通胀",
    "降息", "加息", "美联储", "财务自由", "被动收入", "现金流",
    "打新", "定投", "量化", "做空", "做多", "止损", "止盈",
}
