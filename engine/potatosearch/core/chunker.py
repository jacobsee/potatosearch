"""
Paragraph-aware text chunker with configurable overlap.

Splits on paragraph boundaries where possible, falling back to sentence and
then word boundaries.  Returns character offsets so the reference store can
point back into the original document without storing text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from potatosearch.config import settings


@dataclass(frozen=True)
class Chunk:
    text: str
    char_start: int  # inclusive
    char_end: int    # exclusive


# Paragraph break: two+ newlines (possibly with whitespace between)
_PARA_SPLIT = re.compile(r"\n\s*\n")


def chunk_text(
    text: str,
    target_words: int | None = None,
    overlap_words: int | None = None,
) -> list[Chunk]:
    """
    Split *text* into overlapping chunks of roughly *target_words* words,
    respecting paragraph boundaries where possible.

    Returns a list of Chunk(text, char_start, char_end).
    """
    target_words = target_words or settings.chunk_target_words
    overlap_words = overlap_words or settings.chunk_overlap_words

    if not text or not text.strip():
        return []

    paragraphs = _split_paragraphs(text)

    chunks: list[Chunk] = []
    buf_parts: list[tuple[int, int]] = []  # (start, end) spans
    buf_wc = 0

    for p_start, p_end in paragraphs:
        p_text = text[p_start:p_end]
        p_wc = len(p_text.split())

        # If a single paragraph exceeds target, split it by sentences/words
        if p_wc > target_words and not buf_parts:
            chunks.extend(_hard_split(text, p_start, p_end, target_words, overlap_words))
            continue

        # Adding this paragraph would exceed target → flush buffer first
        if buf_wc + p_wc > target_words and buf_parts:
            c_start = buf_parts[0][0]
            c_end = buf_parts[-1][1]
            chunks.append(Chunk(text[c_start:c_end], c_start, c_end))
            # Overlap: keep trailing paragraphs whose words fit in overlap
            buf_parts, buf_wc = _keep_overlap(buf_parts, text, overlap_words)

        buf_parts.append((p_start, p_end))
        buf_wc += p_wc

    # Flush remaining
    if buf_parts:
        c_start = buf_parts[0][0]
        c_end = buf_parts[-1][1]
        chunks.append(Chunk(text[c_start:c_end], c_start, c_end))

    return chunks


# ── helpers ──────────────────────────────────────────────────────────────

def _split_paragraphs(text: str) -> list[tuple[int, int]]:
    """Return (start, end) char spans for each paragraph."""
    spans = []
    for m in _PARA_SPLIT.finditer(text):
        spans.append(m.start())
    # Convert split points to (start, end) pairs
    starts = [0] + [s for s in spans]
    ends = spans + [len(text)]
    result = []
    for s, e in zip(starts, ends):
        stripped = text[s:e].strip()
        if stripped:
            # Adjust to the stripped content's position
            leading = len(text[s:e]) - len(text[s:e].lstrip())
            trailing = len(text[s:e]) - len(text[s:e].rstrip())
            actual_end = e - trailing if trailing else e
            result.append((s + leading, actual_end))
    return result


def _hard_split(
    text: str, start: int, end: int, target: int, overlap: int,
) -> list[Chunk]:
    """Word-level split for oversized paragraphs."""
    words = text[start:end].split()
    chunks = []
    i = 0
    while i < len(words):
        slice_words = words[i : i + target]
        chunk_text_str = " ".join(slice_words)
        # Compute approximate char offsets (good enough for retrieval)
        c_start = text.index(slice_words[0], start) if chunks == [] or i == 0 else chunks[-1].char_end
        c_end = min(c_start + len(chunk_text_str) + 50, end)  # conservative
        chunks.append(Chunk(text[c_start:c_end].strip(), c_start, c_end))
        i += target - overlap
    return chunks


def _keep_overlap(
    parts: list[tuple[int, int]], text: str, overlap_words: int,
) -> tuple[list[tuple[int, int]], int]:
    """Keep trailing paragraph spans that fit within overlap budget."""
    kept: list[tuple[int, int]] = []
    wc = 0
    for p_start, p_end in reversed(parts):
        p_wc = len(text[p_start:p_end].split())
        if wc + p_wc > overlap_words:
            break
        kept.insert(0, (p_start, p_end))
        wc += p_wc
    return kept, wc
