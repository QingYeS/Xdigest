#!/usr/bin/env python3
"""截图调试：用持久化 Profile 检查页面是否正确加载"""
import asyncio
from scraper import CHROME_PROFILE, _get_context
from playwright.async_api import async_playwright

async def debug():
    async with async_playwright() as p:
        context = await _get_context(p, headless=True)
        page = await context.new_page()
        print("正在打开 x.com/home ...")
        await page.goto("https://x.com/home", wait_until="domcontentloaded")
        await page.wait_for_timeout(6000)
        print(f"当前 URL: {page.url}")
        await page.screenshot(path="debug_screenshot.png")
        print("截图已保存：debug_screenshot.png")
        count = await page.locator('article[data-testid="tweet"]').count()
        print(f"找到推文数量: {count}")
        tabs = await page.locator('[role="tab"]').all()
        print(f"Tab 标签: {[await t.inner_text() for t in tabs]}")
        await context.close()

asyncio.run(debug())
