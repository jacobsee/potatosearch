"""
Query engine.

embed question → FAISS search → resolve refs → fetch text from backends → return
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from typing import TYPE_CHECKING

from potatosearch.config import settings
from potatosearch.core import BackendRegistry
from potatosearch.core.embedder import Embedder
from potatosearch.core.index import IndexManager
from potatosearch.core.refs import ReferenceStore

if TYPE_CHECKING:
    from potatosearch.core.shard import Shard

log = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    score: float
    backend: str
    locator: str
    title: str | None
    text: str
    char_start: int
    char_end: int


def query(
    question: str,
    embedder: Embedder,
    index: IndexManager,
    refs: ReferenceStore,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """
    Retrieve the top-K most relevant chunks for a natural language question.
    """
    top_k = top_k or settings.query_top_k

    q_vec = embedder.embed_query(question)
    scores, ids = index.search(q_vec, top_k)

    # Flatten (1, k) → (k,)
    scores = scores[0]
    ids = ids[0]

    # Filter out -1 (empty slots)
    valid = [(float(s), int(i)) for s, i in zip(scores, ids) if i >= 0]
    if not valid:
        return []

    chunk_refs = refs.get_refs([i for _, i in valid])

    results: list[RetrievedChunk] = []
    for (score, _), ref in zip(valid, chunk_refs):
        if ref is None:
            continue
        try:
            backend = BackendRegistry.get(ref.backend)
            text = backend.retrieve_text(ref.locator, ref.char_start, ref.char_end)
        except Exception:
            log.warning("Failed to retrieve chunk %d from backend '%s'", ref.id, ref.backend, exc_info=True)
            continue

        results.append(RetrievedChunk(
            score=score,
            backend=ref.backend,
            locator=ref.locator,
            title=ref.title,
            text=text,
            char_start=ref.char_start,
            char_end=ref.char_end,
        ))

    return results


def query_shards(
    question: str,
    embedder: Embedder,
    shards: dict[str, Shard],
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """
    Federated search across all shards, merged by score.

    Each shard is searched independently for top_k results, then the best
    overall top_k are returned.
    """
    top_k = top_k or settings.query_top_k
    q_vec = embedder.embed_query(question)

    all_results: list[RetrievedChunk] = []

    for shard in shards.values():
        if shard.index.ntotal == 0:
            continue

        scores, ids = shard.index.search(q_vec, top_k)
        valid = [(float(s), int(i)) for s, i in zip(scores[0], ids[0]) if i >= 0]
        if not valid:
            continue

        chunk_refs = shard.refs.get_refs([i for _, i in valid])

        for (score, _), ref in zip(valid, chunk_refs):
            if ref is None:
                continue
            try:
                backend = BackendRegistry.get(ref.backend)
                text = backend.retrieve_text(ref.locator, ref.char_start, ref.char_end)
            except Exception:
                log.warning(
                    "Failed to retrieve chunk %d from backend '%s'",
                    ref.id, ref.backend, exc_info=True,
                )
                continue

            all_results.append(RetrievedChunk(
                score=score,
                backend=ref.backend,
                locator=ref.locator,
                title=ref.title,
                text=text,
                char_start=ref.char_start,
                char_end=ref.char_end,
            ))

    all_results.sort(key=lambda r: r.score, reverse=True)
    return all_results[:top_k]
