"""ICIJ Offshore Leaks connector.

Downloads the ICIJ Offshore Leaks bulk CSV (Panama Papers, Paradise Papers,
Pandora Papers) and converts graph records into synthetic narrative documents
suitable for vector indexing.

The CSV archive is ~250 MB and is cached at ICIJ_DATA_DIR (default: /tmp/icij).

Document types produced:
  - Offshore entities   (shell companies, trusts, foundations)
  - Officers            (individuals with offshore holdings)
  - Intermediaries      (law firms, agents who set up structures)
"""
from __future__ import annotations

import asyncio
import csv
import os
import zipfile
from pathlib import Path

import aiohttp

_BULK_URL  = "https://offshoreleaks-data.icij.org/offshoreleaks/csv/full-oldb.LATEST.zip"
_CACHE_DIR = Path(os.getenv("ICIJ_DATA_DIR", "/tmp/icij"))

_ENTITIES_CSV       = "nodes-entities.csv"
_OFFICERS_CSV       = "nodes-officers.csv"
_INTERMEDIARIES_CSV = "nodes-intermediaries.csv"
_EDGES_CSV          = "relationships.csv"


async def fetch_icij_documents(max_docs: int = 5_000) -> list[dict]:
    await _ensure_downloaded()

    entities      = _load_csv(_CACHE_DIR / _ENTITIES_CSV)
    officers      = _load_csv(_CACHE_DIR / _OFFICERS_CSV)
    intermediaries = _load_csv(_CACHE_DIR / _INTERMEDIARIES_CSV)
    edges         = _load_csv(_CACHE_DIR / _EDGES_CSV)

    # node_id → name lookup
    name_map: dict[str, str] = {}
    for row in entities + officers + intermediaries:
        nid  = row.get("node_id") or row.get("id", "")
        name = row.get("name", "")
        if nid and name:
            name_map[nid] = name

    # officer/intermediary → list of "REL_TYPE → target_name" strings
    connections: dict[str, list[str]] = {}
    for edge in edges:
        src = edge.get("START_ID", "") or edge.get("_start", "")
        dst = edge.get("END_ID", "")   or edge.get("_end", "")
        rel = edge.get("TYPE", "")     or edge.get("type", "")
        if src in name_map and dst in name_map:
            connections.setdefault(src, []).append(f"{rel} → {name_map[dst]}")

    # Allocate budget across three node types
    entity_cap       = max_docs // 2
    officer_cap      = max_docs // 3
    intermediary_cap = max_docs - entity_cap - officer_cap

    docs: list[dict] = []

    # ── Entities ───────────────────────────────────────────────────────────
    for row in entities[:entity_cap]:
        nid    = row.get("node_id") or row.get("id", "")
        name   = row.get("name", "")
        if not name:
            continue
        juri   = row.get("jurisdiction", "") or row.get("jurisdiction_description", "")
        incorp = row.get("incorporation_date", "")
        status = row.get("status", "")
        src    = row.get("sourceID", "ICIJ")
        conn_text = "\n".join(f"  - {c}" for c in connections.get(nid, [])[:10])
        docs.append({
            "document_id":  f"icij:entity:{nid}",
            "title":        f"Offshore entity — {name}",
            "text": (
                f"Offshore entity: {name}\n"
                f"Jurisdiction: {juri}\n"
                f"Incorporation date: {incorp}\n"
                f"Status: {status}\n"
                f"Leak source: {src}\n"
                f"Connections:\n{conn_text}"
            ),
            "author":       src,
            "jurisdiction": juri,
            "date":         incorp[:10] if incorp else "",
        })

    # ── Officers ───────────────────────────────────────────────────────────
    for row in officers[:officer_cap]:
        nid  = row.get("node_id") or row.get("id", "")
        name = row.get("name", "")
        if not name:
            continue
        conn_text = "\n".join(f"  - {c}" for c in connections.get(nid, [])[:10])
        countries = row.get("countries", "") or row.get("country_codes", "")
        docs.append({
            "document_id":  f"icij:officer:{nid}",
            "title":        f"Individual — {name}",
            "text": (
                f"Individual with offshore connections: {name}\n"
                f"Countries: {countries}\n"
                f"Connections:\n{conn_text}"
            ),
            "jurisdiction": countries,
            "date":         "",
        })

    # ── Intermediaries ─────────────────────────────────────────────────────
    for row in intermediaries[:intermediary_cap]:
        nid    = row.get("node_id") or row.get("id", "")
        name   = row.get("name", "")
        if not name:
            continue
        juri   = row.get("jurisdiction", "") or row.get("country_codes", "")
        src    = row.get("sourceID", "ICIJ")
        conn_text = "\n".join(f"  - {c}" for c in connections.get(nid, [])[:10])
        docs.append({
            "document_id":  f"icij:intermediary:{nid}",
            "title":        f"Intermediary — {name}",
            "text": (
                f"Offshore intermediary (law firm / agent / provider): {name}\n"
                f"Jurisdiction: {juri}\n"
                f"Leak source: {src}\n"
                f"Clients / structures set up:\n{conn_text}"
            ),
            "author":       src,
            "jurisdiction": juri,
            "date":         "",
        })

    return docs[:max_docs]


async def _ensure_downloaded() -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if (_CACHE_DIR / _ENTITIES_CSV).exists():
        return  # already cached

    print("Downloading ICIJ Offshore Leaks data (~250 MB)…")
    zip_path = _CACHE_DIR / "full-oldb.zip"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Accept": "application/zip,application/octet-stream,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://offshoreleaks.icij.org/",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(
            _BULK_URL,
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=600),
        ) as resp:
            resp.raise_for_status()
            with zip_path.open("wb") as fh:
                async for chunk in resp.content.iter_chunked(65536):
                    fh.write(chunk)

    _WANTED = {_ENTITIES_CSV, _OFFICERS_CSV, _INTERMEDIARIES_CSV, _EDGES_CSV}
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if Path(name).name in _WANTED:
                (_CACHE_DIR / Path(name).name).write_bytes(zf.read(name))

    zip_path.unlink(missing_ok=True)
    print("ICIJ data cached.")


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))
