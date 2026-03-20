"""
Per-backend index shards.

Each configured backend gets its own directory containing a FAISS index
and SQLite reference store.  This allows independent lifecycle management
(ingest, drop, rebuild) per backend without touching other backends' data.

Layout:
    data/shards/{backend_id}/faiss.index
    data/shards/{backend_id}/refs.sqlite
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Shard:
    """One backend's FAISS index + SQLite reference store."""
    backend_id: str
    index: "IndexManager"  # noqa: F821
    refs: "ReferenceStore"  # noqa: F821
    shard_dir: Path


def load_shard(backend_id: str, shards_dir: Path, dimension: int) -> Shard:
    """Load an existing shard or create an empty one."""
    from potatosearch.core.index import IndexManager
    from potatosearch.core.refs import ReferenceStore

    shard_dir = shards_dir / backend_id
    shard_dir.mkdir(parents=True, exist_ok=True)

    index_path = shard_dir / "faiss.index"
    refs_path = shard_dir / "refs.sqlite"

    refs = ReferenceStore(refs_path)
    index = IndexManager(dimension=dimension, default_path=index_path)

    if index_path.exists():
        index.load(path=index_path)
    else:
        index.create_flat()

    return Shard(backend_id=backend_id, index=index, refs=refs, shard_dir=shard_dir)


def drop_shard(backend_id: str, shards_dir: Path) -> bool:
    """Delete a shard's directory entirely.  Returns True if it existed."""
    shard_dir = shards_dir / backend_id
    if shard_dir.exists():
        shutil.rmtree(shard_dir)
        log.info("Dropped shard '%s' at %s", backend_id, shard_dir)
        return True
    log.info("No shard found for '%s'", backend_id)
    return False
