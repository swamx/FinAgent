from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    text: str
    start: int
    end: int
    metadata: dict = field(default_factory=dict)


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def chunk_text(
    text: str,
    chunk_size: int = 1_200,
    overlap: int = 200,
    metadata: dict | None = None,
) -> list[Chunk]:
    """Sentence-boundary-aware chunker.

    Splits text into sentences then groups them into chunks of at most
    `chunk_size` characters, with `overlap` characters of backward context.
    """
    sentences = split_sentences(text)
    chunks: list[Chunk] = []
    current: list[str] = []
    current_len = 0
    cursor = 0

    for sentence in sentences:
        if current_len + len(sentence) > chunk_size and current:
            chunk_text = " ".join(current)
            chunks.append(
                Chunk(
                    text=chunk_text,
                    start=cursor - current_len,
                    end=cursor,
                    metadata=dict(metadata or {}),
                )
            )
            # keep last `overlap` chars worth of sentences as context
            overlap_sentences: list[str] = []
            overlap_len = 0
            for s in reversed(current):
                if overlap_len + len(s) > overlap:
                    break
                overlap_sentences.insert(0, s)
                overlap_len += len(s) + 1
            current = overlap_sentences
            current_len = overlap_len

        current.append(sentence)
        current_len += len(sentence) + 1
        cursor += len(sentence) + 1

    if current:
        chunks.append(
            Chunk(
                text=" ".join(current),
                start=cursor - current_len,
                end=cursor,
                metadata=dict(metadata or {}),
            )
        )

    return chunks
