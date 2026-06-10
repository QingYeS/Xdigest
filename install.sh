#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON=/opt/anaconda3/bin/python3

echo "=== X 投资摘要系统安装 ==="

# 安装依赖
echo "1. 安装 Python 依赖..."
$PYTHON -m pip install -r "$DIR/requirements.txt" -q

# 安装 Playwright 浏览器
echo "2. 安装 Playwright Chromium..."
$PYTHON -m playwright install chromium

# 创建日志目录
mkdir -p "$DIR/logs"

# 检查 .env 文件
if [ ! -f "$DIR/.env" ]; then
  cp "$DIR/.env.example" "$DIR/.env"
  echo ""
  echo "⚠  请先编辑 $DIR/.env，填入 Gmail 和 Anthropic API Key"
  echo "   然后重新运行此脚本"
  exit 0
fi

# 首次 X 登录
echo ""
echo "3. 首次登录 X（会打开浏览器窗口）..."
$PYTHON "$DIR/setup.py"

# 注册 launchd 定时任务
echo ""
echo "4. 注册定时任务（每天 00:00 / 08:00 / 16:00）..."
PLIST="$HOME/Library/LaunchAgents/com.xdigest.plist"
cp "$DIR/com.xdigest.plist" "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "✅ 安装完成！"
echo "   · 日志路径：$DIR/logs/"
echo "   · 手动测试运行：$PYTHON $DIR/main.py"
echo "   · 停止定时任务：launchctl unload ~/Library/LaunchAgents/com.xdigest.plist"
