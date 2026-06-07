"""USASpending.gov connector.

Fetches federal contract awards for defence / tech / finance sectors.
No API key required.

Pagination: USASpending returns page_metadata.hasNext; _search() loops
through pages until the keyword quota is reached or no more pages exist.
"""
from __future__ import annotations

import asyncio

import aiohttp

from observability.circuit_breakers import procurement_breaker

_API  = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
_RATE = asyncio.Semaphore(5)

_KEYWORDS_SMALL = [
    "cybersecurity intelligence",
    "financial technology",
    "sanctions monitoring",
    "data analytics intelligence",
    "compliance screening",
]

_KEYWORDS_FULL = _KEYWORDS_SMALL + [
    "anti-money laundering",
    "fraud detection",
    "identity verification",
    "risk assessment financial",
    "threat intelligence",
    "financial crime investigation",
    "regulatory compliance",
    "know your customer",
    "beneficial ownership registry",
    "transaction monitoring",
]

_AWARD_TYPES = ["A", "B", "C", "D"]   # procurement contract types
_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Awarding Agency",
    "Award Amount",
    "Description",
    "Place of Performance State Code",
    "Start Date",
]


@procurement_breaker
async def fetch_contracts(max_docs: int = 500) -> list[dict]:
    keywords = _KEYWORDS_FULL if max_docs > 500 else _KEYWORDS_SMALL
    per_keyword = max(10, max_docs // len(keywords) + 10)

    docs: list[dict] = []
    async with aiohttp.ClientSession() as session:
        for keyword in keywords:
            if len(docs) >= max_docs:
                break
            batch = await _search_paginated(session, keyword, limit=per_keyword)
            docs.extend(batch)

    seen: set[str] = set()
    deduped: list[dict] = []
    for d in docs:
        if d["document_id"] not in seen:
            seen.add(d["document_id"])
            deduped.append(d)

    return deduped[:max_docs]


async def _search_paginated(
    session: aiohttp.ClientSession,
    keyword: str,
    limit: int = 100,
) -> list[dict]:
    results: list[dict] = []
    page = 1

    while len(results) < limit:
        payload = {
            "filters": {
                "keywords":        [keyword],
                "award_type_codes": _AWARD_TYPES,
            },
            "fields":  _FIELDS,
            "page":    page,
            "limit":   min(100, limit - len(results)),
            "sort":    "Award Amount",
            "order":   "desc",
        }
        async with _RATE:
            try:
                async with session.post(
                    _API, json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
            except Exception:
                break

        for award in data.get("results", []):
            award_id  = award.get("Award ID", "")
            recipient = award.get("Recipient Name", "Unknown")
            agency    = award.get("Awarding Agency", "")
            amount    = award.get("Award Amount", 0)
            start     = award.get("Start Date", "")
            desc      = award.get("Description", "")
            state     = award.get("Place of Performance State Code", "")
            if not award_id:
                continue
            results.append({
                "document_id":  f"procurement:{award_id}",
                "title":        f"{recipient} — {agency}",
                "text": (
                    f"Federal contract award.\n"
                    f"Vendor: {recipient}\n"
                    f"Awarding agency: {agency}\n"
                    f"Contract value: ${amount:,.0f} USD\n"
                    f"Start date: {start}\n"
                    f"Description: {desc}\n"
                    f"Keyword match: {keyword}"
                ),
                "author":       agency,
                "jurisdiction": state or "US",
                "date":         start[:10] if start else "",
            })

        meta = data.get("page_metadata", {})
        if not meta.get("hasNext", False):
            break
        page += 1

    return results
