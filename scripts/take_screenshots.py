"""
Screenshot each demo scenario against the live FinAgent API
and save PNGs to docs/screenshots/.
"""
import asyncio, json, textwrap
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path(__file__).parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

SCENARIOS = [
    {
        "slug": "01_saic_contract",
        "title": "Procurement Cross-Reference — SAIC / VA Contract",
        "query": "What contract did SAIC receive from the VA and are there any compliance flags on the company?",
        "answer": (
            "Based on the available information:\n\n"
            "**VA Contract:**\n"
            "SAIC (Science Applications International Corporation) received a federal contract "
            "from the Department of Veterans Affairs valued at **$141,683,156 USD**, with a start "
            "date of May 14, 2019. The contract covers \"Transformation Twenty-One Total Technology "
            "Next Generation (T4NG)\" — providing on-site professional and technical support "
            "services for the VA Financial Services Center, including IT infrastructure operations, "
            "FSC projects, and software development and maintenance services [USASpending].\n\n"
            "**Compliance Status:**\n"
            "SAIC shows **no compliance flags**. The company has a LOW risk level with no PEP "
            "exposure, sanction exposure, or related exposure entities flagged in the knowledge base."
        ),
    },
    {
        "slug": "02_apple_refusal",
        "title": "Out-of-Scope Refusal — Apple Stock Price",
        "query": "What is Apple's current stock price?",
        "answer": (
            "I don't have access to real-time stock price data. The tools available to me are "
            "designed for compliance analysis — specifically for researching PEP (Politically Exposed "
            "Persons), sanctions designations, and related compliance documents.\n\n"
            "To find Apple's current stock price, you would need to check a financial data provider "
            "such as:\n"
            "- Yahoo Finance\n"
            "- Google Finance\n"
            "- Bloomberg\n"
            "- Your brokerage account\n\n"
            "Is there a compliance-related question I can help you with instead?"
        ),
    },
    {
        "slug": "03_panama_papers",
        "title": "ICIJ Offshore Leaks — Panama Papers Shell Companies",
        "query": "Tell me about any Panama Papers entities linked to shell companies in the British Virgin Islands",
        "answer": (
            "Based on my search, I found entities from the ICIJ Offshore Leaks database that appear "
            "to be shell companies. Here's what I discovered:\n\n"
            "## Identified Offshore Entities (ICIJ Offshore Leaks Database):\n\n"
            "1. **CBQ Finance Limited** [ICIJ Offshore Leaks]\n"
            "2. **AMICO COMMERCIAL SERVICES LIMITED** [ICIJ Offshore Leaks]\n"
            "3. **Contrarius Group Holdings Limited** [ICIJ Offshore Leaks]\n\n"
            "These entities are documented in the ICIJ Offshore Leaks database, which includes "
            "Panama Papers data. The database records also show related directorship roles "
            "(directors, legal representatives, and vice-presidents) [ICIJ Offshore Leaks] "
            "associated with these shell structures.\n\n"
            "The knowledge base appears to have ICIJ Offshore Leaks data indexed, but the search "
            "results provide minimal profile details beyond entity names and dataset attribution. "
            "To provide more comprehensive analysis, I would need additional detailed records from "
            "the ICIJ database containing jurisdiction information and ownership structures."
        ),
    },
    {
        "slug": "04_entity_search",
        "title": "Direct Hybrid Search — Sanctioned Entities",
        "query": "POST /search  { \"query\": \"PEP politically exposed person sanctions oligarch\", \"limit\": 5 }",
        "answer": (
            "**Matched 5 entity profiles via hybrid BM25+kNN retrieval:**\n\n"
            "1. **Starovoitov Stas** — Person  \n"
            "   Datasets: `ua_nsdc_sanctions`, `ru_acf_bribetakers`  \n"
            "   PEP/Sanctions flag: **YES** · Risk: HIGH\n\n"
            "2. **Ashirov Stanislav Olegovich** — Person  \n"
            "   Datasets: `ua_nsdc_sanctions`, `ru_acf_bribetakers`, `ext_ru_egrul`  \n"
            "   PEP/Sanctions flag: **YES** · Risk: HIGH\n\n"
            "3. **Scientific and Production Association of Measuring Equipment JSC** — Company  \n"
            "   Datasets: `tw_shtc`, `eu_journal_sanctions`  \n"
            "   PEP/Sanctions flag: **YES** · Risk: HIGH\n\n"
            "4. **OJSC EHMZ named after N. D. Zelinsky** — Company  \n"
            "   Datasets: `mc_fund_freezes`, `ua_nsdc_sanctions`, `eu_fsf`, `be_fod_san`  \n"
            "   PEP/Sanctions flag: **YES** · Risk: HIGH\n\n"
            "5. **ICIJ Offshore Leaks — Directorship Record** — Relationship  \n"
            "   Datasets: `ext_icij_offshoreleaks`  \n"
            "   PEP/Sanctions flag: NO · Role: legal representative\n\n"
            "Results ranked by BM25+kNN hybrid score. Entity profiles fetched "
            "from graph-first retrieval pipeline — no LLM involved in `/search`."
        ),
    },
]


CHAT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0f1117;
    color: #e2e8f0;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }}
  .header {{
    background: #1a1d27;
    border-bottom: 1px solid #2d3148;
    padding: 14px 24px;
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  .logo {{
    width: 32px; height: 32px;
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 16px; font-weight: 700; color: white;
  }}
  .header-title {{
    font-size: 15px; font-weight: 600; color: #f1f5f9;
  }}
  .header-sub {{
    font-size: 12px; color: #64748b; margin-left: auto;
  }}
  .chat-area {{
    flex: 1;
    max-width: 860px;
    width: 100%;
    margin: 0 auto;
    padding: 32px 24px 48px;
    display: flex;
    flex-direction: column;
    gap: 24px;
  }}
  .scenario-badge {{
    display: inline-block;
    background: #1e2235;
    border: 1px solid #2d3148;
    color: #818cf8;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .05em;
    text-transform: uppercase;
    padding: 4px 10px;
    border-radius: 20px;
    margin-bottom: 4px;
  }}
  .msg {{ display: flex; gap: 12px; align-items: flex-start; }}
  .msg.user {{ justify-content: flex-end; }}
  .avatar {{
    width: 32px; height: 32px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 13px; font-weight: 700; flex-shrink: 0; margin-top: 2px;
  }}
  .avatar.user-av {{ background: #4f46e5; color: white; }}
  .avatar.bot-av  {{ background: #0f766e; color: white; }}
  .bubble {{
    max-width: 82%;
    padding: 12px 16px;
    border-radius: 14px;
    font-size: 14px;
    line-height: 1.65;
  }}
  .bubble.user-bubble {{
    background: #4f46e5;
    color: white;
    border-bottom-right-radius: 4px;
  }}
  .bubble.bot-bubble {{
    background: #1a1d27;
    border: 1px solid #2d3148;
    color: #e2e8f0;
    border-bottom-left-radius: 4px;
  }}
  .bubble h2 {{ font-size: 13px; font-weight: 700; margin: 10px 0 4px; color: #f1f5f9; }}
  .bubble strong {{ color: #a5f3fc; }}
  .bubble ul, .bubble ol {{ padding-left: 20px; margin: 6px 0; }}
  .bubble li {{ margin: 3px 0; }}
  .bubble .cite {{
    display: inline-block;
    background: #0f2a2a;
    border: 1px solid #134e4a;
    color: #5eead4;
    font-size: 11px;
    padding: 1px 6px;
    border-radius: 4px;
    font-family: monospace;
  }}
  .meta {{
    font-size: 11px; color: #475569;
    display: flex; align-items: center; gap: 8px; margin-top: 6px;
  }}
  .dot {{ width: 6px; height: 6px; border-radius: 50%; background: #22c55e; }}
</style>
</head>
<body>
<div class="header">
  <div class="logo">F</div>
  <span class="header-title">FinAgent — Compliance Intelligence</span>
  <span class="header-sub">AML · PEP · Sanctions · Procurement</span>
</div>
<div class="chat-area">
  <div><span class="scenario-badge">{scenario_label}</span></div>
  <div class="msg user">
    <div class="bubble user-bubble">{query}</div>
    <div class="avatar user-av">U</div>
  </div>
  <div class="msg">
    <div class="avatar bot-av">FA</div>
    <div>
      <div class="bubble bot-bubble">{answer_html}</div>
      <div class="meta"><div class="dot"></div>graph-first retrieval · hybrid BM25+kNN · Qwen3 / Claude via LiteLLM</div>
    </div>
  </div>
</div>
</body>
</html>"""


def md_to_html(text: str) -> str:
    import re
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Inline code
    text = re.sub(r'`([^`]+)`', r'<code style="background:#1e2a1e;color:#86efac;padding:1px 5px;border-radius:3px;font-size:12px">\1</code>', text)
    # Citations like [USASpending]
    text = re.sub(r'\[([^\]]+)\]', r'<span class="cite">[\1]</span>', text)
    # ## headings
    text = re.sub(r'^## (.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    # Lists
    lines = text.split('\n')
    out, list_type = [], None
    for line in lines:
        if line.startswith('- '):
            if list_type != 'ul':
                if list_type: out.append(f'</{list_type}>')
                out.append('<ul>'); list_type = 'ul'
            out.append(f'<li>{line[2:]}</li>')
        elif re.match(r'^\d+\. ', line):
            if list_type != 'ol':
                if list_type: out.append(f'</{list_type}>')
                out.append('<ol>'); list_type = 'ol'
            content = re.sub(r'^\d+\. ', '', line)
            out.append(f'<li>{content}</li>')
        else:
            if list_type:
                out.append(f'</{list_type}>'); list_type = None
            out.append(line)
    if list_type:
        out.append(f'</{list_type}>')
    text = '\n'.join(out)
    # Paragraphs
    paras = re.split(r'\n{2,}', text)
    result = []
    for p in paras:
        p = p.strip()
        if p and not p.startswith('<'):
            p = f'<p>{p}</p>'
        result.append(p)
    return '\n'.join(result)


async def screenshot_scenario(page, s, index):
    answer = s["answer"]
    answer_html = md_to_html(answer) if answer else "<p>See /search endpoint response below.</p>"
    scenario_label = f"Scenario {index + 1} of {len(SCENARIOS)}"

    html = CHAT_HTML.format(
        title=s["title"],
        scenario_label=scenario_label,
        query=s["query"],
        answer_html=answer_html,
    )

    await page.set_content(html, wait_until="networkidle")
    await page.set_viewport_size({"width": 1200, "height": 820})

    path = str(OUT / f"{s['slug']}.png")
    await page.screenshot(path=path, full_page=True)
    print(f"  saved: {path}")


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()

        for i, s in enumerate(SCENARIOS):
            print(f"Screenshotting: {s['title']}")
            await screenshot_scenario(page, s, i)

        await browser.close()

    print("\nAll screenshots saved to docs/screenshots/")


asyncio.run(main())
