from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IngestMode:
    sec_max_docs: int
    sec_days_back: int
    court_max_docs: int
    icij_max_docs: int
    procurement_max_docs: int
    news_max_docs: int
    news_full_text: bool
    embed_batch_size: int
    max_concurrent: int


SMALL = IngestMode(
    sec_max_docs=300,
    sec_days_back=180,
    court_max_docs=200,
    icij_max_docs=3_000,
    procurement_max_docs=500,
    news_max_docs=500,
    news_full_text=False,
    embed_batch_size=128,
    max_concurrent=32,
)

FULL = IngestMode(
    sec_max_docs=5_000,
    sec_days_back=1_825,    # 5 years
    court_max_docs=5_000,
    icij_max_docs=30_000,
    procurement_max_docs=5_000,
    news_max_docs=5_000,
    news_full_text=True,
    embed_batch_size=256,
    max_concurrent=64,
)

MODES: dict[str, IngestMode] = {"small": SMALL, "full": FULL}
