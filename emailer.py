from __future__ import annotations
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL

_RECIPIENTS = [r.strip() for r in RECIPIENT_EMAIL.split(",") if r.strip()]

CST = datetime.now().astimezone().tzinfo  # 系统本地时区


def _format_time(ts: str) -> str:
    if not ts:
        return ""
    try:
        # Twitter API format: "Fri May 29 10:30:00 +0000 2026"
        dt = datetime.strptime(ts, "%a %b %d %H:%M:%S %z %Y")
        return dt.astimezone(CST).strftime("%Y-%m-%d %H:%M %Z")
    except ValueError:
        pass
    try:
        # ISO format fallback
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(CST).strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        return ts


def _post_card(post: dict) -> str:
    time_str = _format_time(post.get("timestamp", ""))
    return f"""
<div style="background:#fff;border:1px solid #e1e8ed;border-radius:12px;padding:20px 24px;margin-bottom:24px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <div>
      <span style="font-weight:700;font-size:15px;color:#0f1419;">{post['display_name']}</span>
      <span style="color:#536471;font-size:14px;margin-left:6px;">{post['handle']}</span>
    </div>
    <div style="text-align:right;">
      <span style="color:#536471;font-size:13px;">{time_str}</span>
      <a href="{post['url']}" style="display:block;color:#1d9bf0;font-size:13px;text-decoration:none;margin-top:2px;">查看原文 →</a>
    </div>
  </div>

  <div style="background:#f7f9fa;border-left:3px solid #1d9bf0;border-radius:4px;padding:12px 16px;margin-bottom:16px;font-size:15px;color:#0f1419;line-height:1.6;white-space:pre-wrap;">{post['content']}</div>

  <table style="width:100%;border-collapse:collapse;">
    <tr>
      <td style="padding:10px 0;border-top:1px solid #eff3f4;vertical-align:top;width:90px;">
        <span style="background:#e8f5e9;color:#2e7d32;font-size:12px;font-weight:600;padding:3px 8px;border-radius:4px;">中文翻译</span>
      </td>
      <td style="padding:10px 0 10px 12px;border-top:1px solid #eff3f4;color:#0f1419;font-size:14px;line-height:1.6;">{post.get('translation','')}</td>
    </tr>
    <tr>
      <td style="padding:10px 0;border-top:1px solid #eff3f4;vertical-align:top;">
        <span style="background:#fff3e0;color:#e65100;font-size:12px;font-weight:600;padding:3px 8px;border-radius:4px;">发帖动机</span>
      </td>
      <td style="padding:10px 0 10px 12px;border-top:1px solid #eff3f4;color:#0f1419;font-size:14px;line-height:1.6;">{post.get('motivation','')}</td>
    </tr>
    <tr>
      <td colspan="2" style="padding:10px 0 4px;border-top:1px solid #eff3f4;vertical-align:top;">
        <span style="background:#e3f2fd;color:#1565c0;font-size:12px;font-weight:600;padding:3px 8px;border-radius:4px;">投资操作</span>
      </td>
    </tr>
    <tr>
      <td colspan="2" style="padding:0 0 10px;">
        {_format_investment(post.get('investment_action', {}))}
      </td>
    </tr>
  </table>
</div>"""


def _format_investment(action) -> str:
    if isinstance(action, str):
        return f'<span style="color:#0f1419;font-size:14px;">{action}</span>'
    if not isinstance(action, dict):
        return ""
    rows = [
        ("方向", action.get("direction", "")),
        ("标的", action.get("targets", "")),
        ("时间", action.get("timeframe", "")),
        ("入场", action.get("entry", "")),
        ("风险", action.get("risk", "")),
    ]
    cells = "".join(
        f'<tr><td style="color:#536471;font-size:12px;padding:3px 12px 3px 0;white-space:nowrap;">{k}</td>'
        f'<td style="color:#0f1419;font-size:13px;padding:3px 0;">{v}</td></tr>'
        for k, v in rows if v and v != "-"
    )
    summary = action.get("summary", "")
    return (
        f'<div style="font-size:14px;font-weight:600;color:#1565c0;margin-bottom:6px;">{summary}</div>'
        f'<table style="border-collapse:collapse;">{cells}</table>'
    )


def build_html(analyzed_posts: list[dict]) -> str:
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M %Z")
    cards = "".join(_post_card(p) for p in analyzed_posts)
    return f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:680px;margin:0 auto;padding:24px 16px;">
    <div style="background:linear-gradient(135deg,#1d9bf0,#0d47a1);border-radius:16px;padding:28px 32px;margin-bottom:28px;color:#fff;">
      <div style="font-size:24px;font-weight:700;margin-bottom:6px;">📈 X 投资动态摘要</div>
      <div style="opacity:.85;font-size:14px;">生成时间：{now}</div>
      <div style="margin-top:12px;background:rgba(255,255,255,.15);border-radius:8px;padding:10px 16px;font-size:15px;">
        本期共 <strong>{len(analyzed_posts)}</strong> 条投资/金融相关内容
      </div>
    </div>
    {cards}
    <div style="text-align:center;color:#8b98a5;font-size:12px;padding:16px 0 8px;">
      由 Claude AI 自动分析 · 仅供参考，不构成投资建议
    </div>
  </div>
</body>
</html>"""


def _send(subject: str, html: str) -> None:
    """对每个收件人单独发送，避免群发被过滤"""
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        for recipient in _RECIPIENTS:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = GMAIL_USER
            msg["To"] = recipient
            msg.attach(MIMEText(html, "html", "utf-8"))
            server.sendmail(GMAIL_USER, recipient, msg.as_string())


def send_digest(analyzed_posts: list[dict]) -> None:
    now = datetime.now(CST).strftime("%m/%d %H:%M")
    if not analyzed_posts:
        subject = f"📭 X 投资动态 · 最近12小时无新内容 · {now}"
        html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,sans-serif;background:#f0f2f5;padding:32px 16px;">
  <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;padding:32px;text-align:center;color:#536471;">
    <div style="font-size:48px;margin-bottom:16px;">📭</div>
    <div style="font-size:18px;font-weight:600;color:#0f1419;margin-bottom:8px;">最近 12 小时无新内容</div>
    <div style="font-size:14px;">你关注的账号在此期间没有发布投资相关内容</div>
    <div style="margin-top:20px;font-size:12px;color:#8b98a5;">检查时间：{now}</div>
  </div>
</body></html>"""
        _send(subject, html)
        print(f"✓ 无内容通知已发送至 {', '.join(_RECIPIENTS)}")
        return

    subject = f"📈 X 投资动态摘要 · {len(analyzed_posts)} 条 · {now}"
    html = build_html(analyzed_posts)
    _send(subject, html)
    print(f"✓ 邮件已发送至 {', '.join(_RECIPIENTS)}（共 {len(analyzed_posts)} 条帖子）")
