"""
Ingestion pipeline.

Phases:
  1. Iterate documents from a storage backend
  2. Chunk each document
  3. Skip already-indexed chunks (content hash dedup)
  4. Batch-embed new chunks
  5. Assign FAISS IDs, store references in SQLite, add vectors to index
  6. Periodically flush to disk

For IVF-PQ, there's an additional training phase that must run before
the first full ingestion - see ``collect_training_sample()``.
"""
from __future__ import annotations

import logging
from typing import Iterator

import numpy as np

from potatosearch.config import settings
from potatosearch.core import StorageBackend
from potatosearch.core.chunker import Chunk, chunk_text
from potatosearch.core.embedder import Embedder
from potatosearch.core.index import IndexManager
from potatosearch.core.progress import IngestProgress
from potatosearch.core.refs import ReferenceStore, content_hash

log = logging.getLogger(__name__)


def collect_training_sample(
    backend: StorageBackend,
    embedder: Embedder,
    refs: ReferenceStore | None = None,
    max_chunks: int | None = None,
    progress: IngestProgress | None = None,
) -> np.ndarray | None:
    """
    Embed a representative sample of chunks for IVF-PQ training.

    If refs is provided, documents whose locator is already indexed are
    skipped (pass refs=None or use --force to reprocess everything).

    Returns an (N, dim) float32 array, or None if there are no new documents.
    """
    max_chunks = max_chunks or settings.faiss_train_sample_size
    texts: list[str] = []
    skipped_docs = 0

    if progress:
        progress.phase = "collecting_sample"
        progress.detail = "Iterating documents for training sample"
        progress.chunks_target = max_chunks
        progress.chunks_new = 0
        progress.docs_processed = 0

    for doc in backend.iterate_documents():
        if refs is not None and refs.has_locator(doc.locator, backend.name):
            skipped_docs += 1
            continue
        if progress:
            progress.docs_processed += 1
        chunks = chunk_text(doc.text)
        for c in chunks:
            texts.append(c.text)
            if progress:
                progress.chunks_new = len(texts)
            if len(texts) >= max_chunks:
                break
        if len(texts) >= max_chunks:
            break

    if skipped_docs:
        log.info("Skipped %d already-indexed documents during training sample collection", skipped_docs)

    if not texts:
        log.info("No new documents found for training sample.")
        return None

    log.info("Collected %d chunks for training sample", len(texts))

    if progress:
        progress.phase = "embedding_sample"
        progress.chunks_new = 0
        progress.chunks_target = len(texts)
        progress.detail = f"Embedding training chunks (0 / {len(texts):,})"

    # Embed in batches so we can report progress between each one.
    bs = settings.embedding_batch_size
    parts: list[np.ndarray] = []
    for i in range(0, len(texts), bs):
        batch = texts[i : i + bs]
        parts.append(embedder.embed(batch))
        done = min(i + bs, len(texts))
        if progress:
            progress.chunks_new = done
            progress.detail = f"Embedding training chunks ({done:,} / {len(texts):,})"
        log.info("Embedded %d / %d training chunks", done, len(texts))

    return np.vstack(parts)


_LOCATOR_TOUCH_BATCH = 2_000  # flush touched locators to SQLite every N documents


def ingest(
    backend: StorageBackend,
    embedder: Embedder,
    index: IndexManager,
    refs: ReferenceStore,
    flush_every: int = 10_000,
    progress: IngestProgress | None = None,
) -> int:
    """
    Full ingestion pass for a single backend.

    Encountered locators are recorded in SQLite via an epoch counter - no
    Python-side sets - so memory usage is O(batch_size) regardless of corpus
    size.  After iteration, a SQL LEFT JOIN identifies stale chunks and they
    are streamed out in batches for removal from both FAISS and the refs DB.

    Returns the number of new chunks indexed.
    """
    epoch = refs.next_epoch(backend.name)
    next_id = refs.next_id()
    buf_texts: list[str] = []
    buf_meta: list[dict] = []
    locator_buf: list[str] = []
    total_new = 0
    total_skipped = 0

    if progress:
        progress.phase = "ingesting"
        progress.detail = "Indexing documents"
        progress.chunks_new = 0
        progress.chunks_skipped = 0
        progress.chunks_target = None
        progress.docs_processed = 0

    def _flush_locators() -> None:
        """Push the locator buffer to SQLite and commit."""
        if locator_buf:
            refs.touch_locators(locator_buf, backend.name, epoch)
            locator_buf.clear()

    def _flush() -> int:
        nonlocal next_id
        if not buf_texts:
            return 0

        vectors = embedder.embed(buf_texts)
        ids = np.arange(next_id, next_id + len(buf_texts), dtype=np.int64)
        index.add(vectors, ids)

        for i, meta in enumerate(buf_meta):
            refs.add_chunk(
                chunk_id=int(ids[i]),
                backend=backend.name,
                locator=meta["locator"],
                char_start=meta["char_start"],
                char_end=meta["char_end"],
                content_hash=meta["hash"],
                title=meta.get("title"),
            )

        refs.commit()
        next_id += len(buf_texts)
        count = len(buf_texts)
        buf_texts.clear()
        buf_meta.clear()
        return count

    for doc in backend.iterate_documents():
        locator_buf.append(doc.locator)
        if len(locator_buf) >= _LOCATOR_TOUCH_BATCH:
            _flush_locators()

        if progress:
            progress.docs_processed += 1

        chunks = chunk_text(doc.text)
        for c in chunks:
            h = content_hash(c.text)
            if refs.has_hash(h):
                total_skipped += 1
                if progress:
                    progress.chunks_skipped = total_skipped
                continue

            buf_texts.append(c.text)
            buf_meta.append({
                "locator": doc.locator,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "hash": h,
                "title": doc.title,
            })

            if len(buf_texts) >= flush_every:
                n = _flush()
                total_new += n
                if progress:
                    progress.chunks_new = total_new
                log.info("Flushed %d chunks (total new: %d, skipped: %d)", n, total_new, total_skipped)

    total_new += _flush()
    if progress:
        progress.chunks_new = total_new
    _flush_locators()  # commit any remaining locator touches

    if progress:
        progress.phase = "pruning"
        progress.detail = "Detecting stale chunks"

    # Build a SQLite temp table of stale chunk IDs (LEFT JOIN against
    # locator_epochs - no Python sets, bounded memory regardless of scale).
    n_stale_locators, n_stale_chunks = refs.build_stale_snapshot(backend.name, epoch)

    if n_stale_chunks > 0:
        if progress:
            progress.detail = f"Pruning {n_stale_chunks:,} stale chunks"
        log.info(
            "Pruning %d stale locators (%d chunks) from '%s'...",
            n_stale_locators, n_stale_chunks, backend.name,
        )
        n_removed_vectors = 0
        n_deleted_chunks = 0
        for id_batch in refs.iter_stale_chunk_id_batches():
            n_removed_vectors += index.remove_ids(id_batch)
            n_deleted_chunks += refs.delete_chunks_by_ids(id_batch)
            refs.commit()
        log.info(
            "Pruned %d chunks (%d vectors) from '%s'",
            n_deleted_chunks, n_removed_vectors, backend.name,
        )

    refs.drop_stale_snapshot()
    refs.prune_epoch_rows(backend.name, epoch)

    if progress:
        progress.phase = "saving"
        progress.detail = "Writing index to disk"

    index.save()
    log.info(
        "Ingestion complete for '%s': %d new, %d skipped, %d stale chunks pruned",
        backend.name, total_new, total_skipped, n_stale_chunks,
    )
    return total_new
