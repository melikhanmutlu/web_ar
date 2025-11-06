import asyncio
from playwright.async_api import async_playwright
import sys

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        url = sys.argv[1]
        await page.goto(url)
        await page.screenshot(path="slicer_screenshot.png")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
