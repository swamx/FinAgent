"""
Screenshot Grafana dashboards and LiteLLM UI.
Saves PNGs to docs/screenshots/.
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path(__file__).parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

GRAFANA   = "http://localhost:3100"
LITELLM   = "http://localhost:4000"
LITELLM_KEY = "sk-finagent-local"

GRAFANA_DASHBOARDS = [
    ("finagent-overview",   "/d/finagent-overview/finagent-e28094-overview",                          "05_grafana_overview"),
    ("finagent-flow",       "/d/finagent-flow/finagent-e28094-request-flow",                          "06_grafana_flow"),
    ("finagent-retrieval",  "/d/finagent-retrieval/finagent-e28094-retrieval-quality-hrt",            "07_grafana_retrieval"),
    ("finagent-evals",      "/d/finagent-evals/finagent-e28094-evals3a-hallucination-2b-ragas",       "08_grafana_evals"),
]


async def screenshot_grafana(page):
    for name, path, slug in GRAFANA_DASHBOARDS:
        print(f"  Grafana: {name}")
        url = f"{GRAFANA}{path}?kiosk=tv&refresh=5s&from=now-3h&to=now"
        await page.goto(url, wait_until="networkidle", timeout=30000)
        # Dismiss any login prompt — otel-lgtm runs anonymous
        await page.wait_for_timeout(3000)
        # Hide any top nav / panels still loading
        await page.evaluate("""() => {
            // collapse any open dropdowns
            document.querySelectorAll('.dropdown-menu').forEach(el => el.style.display='none');
        }""")
        await page.set_viewport_size({"width": 1440, "height": 900})
        out = str(OUT / f"{slug}.png")
        await page.screenshot(path=out, full_page=False)
        print(f"    saved: {out}")


async def screenshot_litellm(page):
    print("  LiteLLM: login")
    await page.goto(f"{LITELLM}/ui", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(3000)

    # LiteLLM login: username=admin, password=MASTER_KEY
    try:
        await page.fill('input[name="username"]', "admin", timeout=5000)
        await page.fill('input[name="password"]', LITELLM_KEY, timeout=5000)
    except Exception:
        # Fallback: fill visible inputs in order
        inputs = await page.query_selector_all("input:visible")
        if len(inputs) >= 2:
            await inputs[0].fill("admin")
            await inputs[1].fill(LITELLM_KEY)
        elif len(inputs) == 1:
            await inputs[0].fill(LITELLM_KEY)

    try:
        await page.click('button:has-text("Login")', timeout=5000)
    except Exception:
        await page.keyboard.press("Enter")

    # Wait for dashboard to load
    await page.wait_for_timeout(5000)

    # Dismiss LiteLLM feedback popup if present
    try:
        await page.click("text=Don't ask me again", timeout=3000)
        await page.wait_for_timeout(500)
    except Exception:
        pass

    await page.set_viewport_size({"width": 1440, "height": 900})

    out = str(OUT / "09_litellm_dashboard.png")
    await page.screenshot(path=out, full_page=False)
    print(f"    saved: {out}")

    # Models page
    try:
        await page.click('text=Models', timeout=4000)
        await page.wait_for_timeout(2000)
        out2 = str(OUT / "10_litellm_models.png")
        await page.screenshot(path=out2, full_page=False)
        print(f"    saved: {out2}")
    except Exception:
        pass

    # Usage / logs page
    try:
        await page.click('text=Usage', timeout=4000)
        await page.wait_for_timeout(2000)
        out3 = str(OUT / "11_litellm_usage.png")
        await page.screenshot(path=out3, full_page=False)
        print(f"    saved: {out3}")
    except Exception:
        pass


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()

        print("Grafana dashboards...")
        await screenshot_grafana(page)

        print("LiteLLM UI...")
        await screenshot_litellm(page)

        await browser.close()
    print("\nDone.")


asyncio.run(main())
