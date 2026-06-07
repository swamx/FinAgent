"""GDELT news connector.

Queries the GDELT Doc 2.0 API for financial crime / sanctions news articles.
No API key required.  Returns article metadata and text snippets.

In full mode (fetch_full_text=True) the actual article body is fetched;
GDELT is strict about rate limits so concurrency is kept very low.
"""
from __future__ import annotations

import asyncio
import hashlib
import re

import aiohttp

from observability.circuit_breakers import news_breaker

_GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_RATE      = asyncio.Semaphore(3)   # GDELT is strict

_QUERIES_SMALL = [
    "money laundering sanctions compliance",
    "AML financial crime enforcement",
    "politically exposed person corruption",
    "offshore account tax evasion",
    "OFAC sanctions violation fine",
    "beneficial ownership shell company investigation",
]

_QUERIES_FULL = _QUERIES_SMALL + [
    "wire fraud financial crime prosecution",
    "asset forfeiture proceeds of crime",
    "kleptocracy stolen assets recovery",
    "trade-based money laundering smuggling",
    "cryptocurrency crypto money laundering",
    "sanctions evasion Russia Iran North Korea",
    "SEC enforcement insider trading fraud",
    "FCPA bribery foreign officials",
    "counter-terrorism financing hawala",
    "deferred prosecution agreement bank",
]


@news_breaker
async def fetch_news_articles(
    max_docs: int = 500,
    fetch_full_text: bool = False,
) -> list[dict]:
    queries = _QUERIES_FULL if max_docs > 500 else _QUERIES_SMALL

    docs: list[dict] = []
    async with aiohttp.ClientSession() as session:
        for query in queries:
            if len(docs) >= max_docs:
                break
            batch = await _query_gdelt(
                session, query,
                max_records=250,
                fetch_full_text=fetch_full_text,
            )
            docs.extend(batch)

    seen: set[str] = set()
    deduped: list[dict] = []
    for d in docs:
        if d["document_id"] not in seen:
            seen.add(d["document_id"])
            deduped.append(d)

    return deduped[:max_docs]


async def _query_gdelt(
    session: aiohttp.ClientSession,
    query: str,
    max_records: int = 100,
    fetch_full_text: bool = False,
) -> list[dict]:
    params = {
        "query":      query,
        "mode":       "artlist",
        "maxrecords": min(max_records, 250),
        "format":     "json",
        "sort":       "HybridRel",
    }
    async with _RATE:
        try:
            async with session.get(
                _GDELT_API, params=params,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json(content_type=None)
        except Exception:
            return []

    articles = data.get("articles", [])
    docs: list[dict] = []
    fetch_tasks = []

    for art in articles:
        url     = art.get("url", "")
        title   = art.get("title", "")
        domain  = art.get("domain", "")
        country = art.get("sourcecountry", "")
        date    = art.get("seendate", "")[:8]
        if date and len(date) == 8:
            date = f"{date[:4]}-{date[4:6]}-{date[6:]}"

        if fetch_full_text:
            fetch_tasks.append((url, title, date, domain, country, query))
        else:
            docs.append({
                "document_id":  f"news:{_url_id(url)}",
                "title":        title,
                "text":         f"{title}\n\nRelated to: {query}\nSource: {url}",
                "author":       domain,
                "jurisdiction": country,
                "date":         date,
                "url":          url,
            })

    if fetch_full_text and fetch_tasks:
        results = await asyncio.gather(
            *[_fetch_article(session, url, title, date, domain, country, q)
              for url, title, date, domain, country, q in fetch_tasks],
            return_exceptions=True,
        )
        docs.extend(r for r in results if isinstance(r, dict) and r.get("text"))

    return docs


async def _fetch_article(
    session: aiohttp.ClientSession,
    url: str,
    title: str,
    date: str,
    author: str,
    jurisdiction: str,
    query: str,
) -> dict | None:
    async with _RATE:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text(errors="replace")
        except Exception:
            return None

    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s{2,}", " ", text).strip()[:20_000]
    if len(text) < 100:
        return None

    return {
        "document_id":  f"news:{_url_id(url)}",
        "title":        title,
        "text":         text,
        "author":       author,
        "jurisdiction": jurisdiction,
        "date":         date,
        "url":          url,
    }


def _url_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16]
