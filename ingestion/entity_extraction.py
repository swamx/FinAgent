"""Neuro-symbolic hybrid entity extractor.

Uses spaCy (fast, broad coverage) merged with GLiNER (slower, higher
precision for financial/compliance entities). GLiNER is optional — the
module degrades gracefully to spaCy-only if it isn't installed.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import spacy
from spacy.language import Language

try:
    from gliner import GLiNER as _GLiNER  # type: ignore
    _GLINER_AVAILABLE = True
except ImportError:
    _GLINER_AVAILABLE = False


# Labels spaCy uses that are compliance-relevant
_SPACY_KEEP = {"PERSON", "ORG", "GPE", "FAC", "LAW", "MONEY", "NORP"}

# Zero-shot GLiNER labels tuned for AML/PEP domain
_GLINER_LABELS = [
    "person",
    "organization",
    "political party",
    "government body",
    "financial institution",
    "jurisdiction",
    "offshore company",
    "law firm",
]

# Confidence threshold — below this GLiNER hits are discarded
_GLINER_THRESHOLD = 0.45


@dataclass
class ExtractedEntity:
    text: str
    label: str          # normalised to UPPER_CASE
    start: int          # char offset in source text
    end: int
    confidence: float   # 1.0 for spaCy (no score), GLiNER score otherwise
    source: str         # "spacy" | "gliner" | "hybrid"


@lru_cache(maxsize=1)
def _load_spacy() -> Language:
    return spacy.load("en_core_web_sm")


@lru_cache(maxsize=1)
def _load_gliner() -> "_GLiNER | None":
    if not _GLINER_AVAILABLE:
        return None
    return _GLiNER.from_pretrained("urchade/gliner_mediumv2.1")


class HybridEntityExtractor:
    """Extract entities using spaCy + GLiNER and merge the results."""

    def __init__(self, use_gliner: bool = True):
        self._nlp = _load_spacy()
        self._gliner = _load_gliner() if use_gliner else None

    def extract(self, text: str) -> list[ExtractedEntity]:
        spacy_hits = self._run_spacy(text)
        gliner_hits = self._run_gliner(text) if self._gliner else []
        return self._merge(spacy_hits, gliner_hits)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_spacy(self, text: str) -> list[ExtractedEntity]:
        doc = self._nlp(text)
        return [
            ExtractedEntity(
                text=ent.text,
                label=ent.label_,
                start=ent.start_char,
                end=ent.end_char,
                confidence=1.0,
                source="spacy",
            )
            for ent in doc.ents
            if ent.label_ in _SPACY_KEEP
        ]

    def _run_gliner(self, text: str) -> list[ExtractedEntity]:
        try:
            hits = self._gliner.predict_entities(text, _GLINER_LABELS, threshold=_GLINER_THRESHOLD)
        except Exception:
            return []
        return [
            ExtractedEntity(
                text=h["text"],
                label=h["label"].upper().replace(" ", "_"),
                start=h["start"],
                end=h["end"],
                confidence=h["score"],
                source="gliner",
            )
            for h in hits
        ]

    def _merge(
        self,
        spacy_hits: list[ExtractedEntity],
        gliner_hits: list[ExtractedEntity],
    ) -> list[ExtractedEntity]:
        """
        Prefer GLiNER when spans overlap — it tends to be more precise for
        financial entities. Keep all non-overlapping spaCy hits.
        """
        merged: list[ExtractedEntity] = list(gliner_hits)
        gliner_spans = {(h.start, h.end) for h in gliner_hits}

        for hit in spacy_hits:
            overlaps = any(
                hit.start < end and hit.end > start
                for start, end in gliner_spans
            )
            if not overlaps:
                merged.append(hit)
            else:
                # mark the covering GLiNER entity as hybrid
                for g in merged:
                    if g.start <= hit.start and g.end >= hit.end:
                        g.source = "hybrid"

        # dedup by (text.lower, label)
        seen: set[tuple[str, str]] = set()
        deduped: list[ExtractedEntity] = []
        for e in merged:
            key = (e.text.lower(), e.label)
            if key not in seen:
                seen.add(key)
                deduped.append(e)

        return deduped
