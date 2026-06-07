"""SEC EDGAR connector.

Fetches recent 10-K / 10-Q / 8-K filings via EDGAR full-text search.
No API key required; rate-limited to 10 req/s per SEC fair-use policy.

Pagination: each _search() call fetches one page (up to _PAGE_SIZE hits).
fetch_sec_filings() loops through pages per term until max_docs is reached.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import aiohttp
from bs4 import BeautifulSoup

from core.config import settings
from observability.circuit_breakers import sec_breaker

_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
_FILING_URL  = "https://www.sec.gov"
_RATE        = asyncio.Semaphore(10)   # 10 concurrent requests max (SEC fair-use)
_PAGE_SIZE   = 20
_FORM_TYPES  = ["10-K", "10-Q", "8-K"]

# Small-mode terms (quick coverage)
_SEARCH_TERMS_SMALL = [
    "money laundering",
    "sanctions compliance",
    "politically exposed",
    "beneficial ownership",
    "anti-bribery",
]

# Full-mode adds deeper AML / enforcement / disclosure terms
_SEARCH_TERMS_FULL = _SEARCH_TERMS_SMALL + [
    "OFAC violation",
    "shell company",
    "wire fraud",
    "suspicious activity report",
    "know your customer",
    "counter-terrorism financing",
    "trade-based money laundering",
    "correspondent banking",
    "asset freeze",
    "deferred prosecution agreement",
]


async def fetch_sec_filings(
    days_back: int = 180,
    max_docs: int = 300,
) -> list[dict]:
    """Return a list of {document_id, title, text, date, source} dicts."""
    start = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end   = datetime.utcnow().strftime("%Y-%m-%d")

    terms = _SEARCH_TERMS_FULL if max_docs > 300 else _SEARCH_TERMS_SMALL

    # (url, title, date, author) — deduplicated by url
    seen_urls: dict[str, tuple[str, str, str, str]] = {}

    async with aiohttp.ClientSession(
        headers={"User-Agent": settings.sec_user_agent}
    ) as session:
        for term in terms:
            if len(seen_urls) >= max_docs:
                break
            offset = 0
            while len(seen_urls) < max_docs:
                hits = await _search(session, term, start, end, offset=offset)
                if not hits:
                    break
                for item in hits:
                    seen_urls.setdefault(item[0], item)
                if len(hits) < _PAGE_SIZE:
                    break   # last page for this term
                offset += _PAGE_SIZE

        filing_urls = list(seen_urls.values())[:max_docs]
        tasks   = [_fetch_filing(session, url, title, date, author)
                   for url, title, date, author in filing_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    return [r for r in results if isinstance(r, dict) and r.get("text")]


async def _search(
    session: aiohttp.ClientSession,
    query: str,
    start: str,
    end: str,
    offset: int = 0,
) -> list[tuple[str, str, str, str]]:
    params = {
        "q":         f'"{query}"',
        "dateRange": "custom",
        "startdt":   start,
        "enddt":     end,
        "forms":     ",".join(_FORM_TYPES),
        "from":      offset,
    }
    data: dict = {}
    async with _RATE:
        try:
            async with session.get(
                _SEARCH_URL, params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        except Exception:
            return []

    results: list[tuple[str, str, str, str]] = []
    for hit in data.get("hits", {}).get("hits", []):
        src       = hit.get("_source", {})
        file_date = src.get("file_date", "")
        entity    = src.get("entity_name", "")
        form      = src.get("form_type", "")
        accession = src.get("accession_no", "").replace("-", "")
        cik       = str(src.get("entity_id", "")).zfill(10)
        if accession and cik:
            url   = f"{_FILING_URL}/Archives/edgar/data/{int(cik)}/{accession}-index.htm"
            title = f"{entity} {form} {file_date}"
            results.append((url, title, file_date, entity))
    return results


async def _fetch_filing(
    session: aiohttp.ClientSession,
    index_url: str,
    title: str,
    date: str,
    author: str = "",
) -> dict | None:
    async with _RATE:
        try:
            async with session.get(
                index_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text(errors="replace")
        except Exception:
            return None

    soup     = BeautifulSoup(html, "lxml")
    doc_link = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.endswith(".htm") and "-index" not in href:
            doc_link = _FILING_URL + href if href.startswith("/") else href
            break

    if not doc_link:
        return None

    async with _RATE:
        try:
            async with session.get(
                doc_link, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    return None
                content = await resp.text(errors="replace")
        except Exception:
            return None

    text = _strip_html(content)[:60_000]
    if len(text) < 200:
        return None

    return {
        "document_id":  f"sec:{index_url.split('/')[-1]}",
        "title":        title,
        "text":         text,
        "date":         date,
        "author":       author,
        "jurisdiction": "US",
        "url":          index_url,
    }


def _strip_html(html: str) -> str:
    import re
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "table"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    return re.sub(r"\s{2,}", " ", text).strip()
