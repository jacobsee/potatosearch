"""
FAISS index manager.

Supports two modes:
  - Flat index (small corpora, exact search, good if it can fit in RAM)
  - IVF-PQ index (large corpora, approximate search, disk-resident)

The caller is responsible for choosing the right mode based on corpus size.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from potatosearch.config import settings

if TYPE_CHECKING:
    import faiss

log = logging.getLogger(__name__)

_TRAIN_WORKER = str(Path(__file__).with_name("_faiss_train_worker.py"))


class IndexManager:
    """
    Wraps a FAISS index with helpers for training, adding, searching,
    and persisting to disk.
    """

    def __init__(self, dimension: int, default_path: Path | None = None):
        import faiss
        self._faiss = faiss
        self.dimension = dimension
        self._index: faiss.Index | None = None
        self._mmap_loaded: bool = False
        self._path: Path | None = default_path

    # ── Construction ─────────────────────────────────────────────────────

    def create_flat(self) -> None:
        """Create an exact (brute-force) index.  Good for < ~1M vectors."""
        self._index = self._faiss.IndexFlatIP(self.dimension)
        log.info("Created flat IP index (dim=%d)", self.dimension)

    def create_ivfpq(
        self,
        train_vectors: np.ndarray,
        nlist: int | None = None,
        pq_m: int | None = None,
    ) -> None:
        """
        Create and train an IVF-PQ index for disk-resident search.

        Training runs in a subprocess that only loads FAISS (no PyTorch),
        allowing full multi-threaded OMP / avoiding the dual-libomp
        segfault on macOS.

        Args:
            train_vectors: Representative sample, shape (n_train, dim), float32.
            nlist: Number of IVF partitions (clusters).
            pq_m: Number of PQ sub-quantizers.  Must divide ``self.dimension``.
        """
        nlist = nlist or settings.faiss_nlist
        pq_m = pq_m or settings.faiss_pq_m

        if self.dimension % pq_m != 0:
            for m in range(pq_m, 0, -1):
                if self.dimension % m == 0:
                    pq_m = m
                    break
            log.warning("Adjusted pq_m to %d to divide dimension %d", pq_m, self.dimension)

        log.info(
            "Training IVF-PQ index: nlist=%d, pq_m=%d, train_samples=%d",
            nlist, pq_m, len(train_vectors),
        )

        with tempfile.TemporaryDirectory() as tmp:
            vectors_path = str(Path(tmp) / "train.npy")
            index_path = str(Path(tmp) / "trained.index")

            np.save(vectors_path, np.ascontiguousarray(train_vectors, dtype=np.float32))

            # Strip OMP_NUM_THREADS so the worker subprocess can use all cores.
            env = {k: v for k, v in os.environ.items()
                   if k != "OMP_NUM_THREADS"}

            result = subprocess.run(
                [sys.executable, _TRAIN_WORKER,
                 vectors_path, index_path,
                 str(nlist), str(pq_m), str(self.dimension)],
                env=env,
                capture_output=True,
                text=True,
            )
            if result.stdout:
                for line in result.stdout.strip().splitlines():
                    log.info("[train-worker] %s", line)
            if result.returncode != 0:
                log.error("FAISS training subprocess failed:\n%s", result.stderr)
                raise RuntimeError(
                    f"FAISS training subprocess exited with code {result.returncode}"
                )

            self._index = self._faiss.read_index(index_path)

        log.info("Training complete.")

    # ── I/O ──────────────────────────────────────────────────────────────

    def save(self, path: Path | None = None) -> None:
        path = path or self._path
        if path is None:
            raise ValueError("No path specified and no default_path set")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._faiss.write_index(self._index, str(path))
        log.info("Index saved to %s (%d vectors)", path, self._index.ntotal)

    def load(self, path: Path | None = None, mmap: bool | None = None) -> None:
        path = path or self._path
        if path is None:
            raise ValueError("No path specified and no default_path set")
        use_mmap = mmap if mmap is not None else settings.faiss_use_mmap
        self._path = path

        if use_mmap:
            self._index = self._faiss.read_index(str(path), self._faiss.IO_FLAG_MMAP)
            self._mmap_loaded = True
            log.info("Loaded index (mmap) from %s", path)
        else:
            self._index = self._faiss.read_index(str(path))
            self._mmap_loaded = False
            log.info("Loaded index from %s", path)

        if hasattr(self._index, "nprobe"):
            self._index.nprobe = settings.faiss_nprobe

    # ── Operations ───────────────────────────────────────────────────────

    def add(self, vectors: np.ndarray, ids: np.ndarray) -> None:
        """
        Add vectors with explicit 64-bit integer IDs.

        Wraps the underlying index in IndexIDMap if needed.
        """
        assert vectors.shape[0] == ids.shape[0]
        self._faiss.normalize_L2(vectors)

        if not isinstance(self._index, self._faiss.IndexIDMap):
            self._index = self._faiss.IndexIDMap(self._index)

        self._index.add_with_ids(vectors, ids.astype(np.int64))

    def remove_ids(self, ids: list[int]) -> int:
        """
        Remove vectors by ID from the index. Returns the count removed.

        If the index was loaded with mmap (read-only), it is transparently
        reloaded without mmap before removal so the data can be modified.
        """
        if not ids or self._index is None:
            return 0
        if not isinstance(self._index, self._faiss.IndexIDMap):
            log.warning("remove_ids: index is not an IndexIDMap; skipping removal")
            return 0
        if self._mmap_loaded:
            if self._path is None:
                raise ValueError("Cannot reload mmap'd index: no path set")
            log.info("Reloading index without mmap to allow removal of stale vectors")
            self._faiss.write_index(self._index, str(self._path))
            self._index = self._faiss.read_index(str(self._path))
            if hasattr(self._index, "nprobe"):
                self._index.nprobe = settings.faiss_nprobe
            self._mmap_loaded = False
        ids_arr = np.array(ids, dtype=np.int64)
        selector = self._faiss.IDSelectorArray(len(ids_arr), self._faiss.swig_ptr(ids_arr))
        return self._index.remove_ids(selector)

    def search(
        self, query_vector: np.ndarray, top_k: int | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Search for nearest neighbors.

        Returns:
            (scores, ids) - each shape (1, top_k).  IDs are -1 for missing slots.
        """
        top_k = top_k or settings.query_top_k
        self._faiss.normalize_L2(query_vector)
        self._faiss.omp_set_num_threads(1)
        scores, ids = self._index.search(query_vector, top_k)
        return scores, ids

    @property
    def ntotal(self) -> int:
        return self._index.ntotal if self._index else 0

    @property
    def index_type(self) -> str:
        """Return 'ivfpq', 'flat', or 'unknown'."""
        if self._index is None:
            return "none"
        inner = self._unwrap_index()
        if isinstance(inner, self._faiss.IndexIVFPQ):
            return "ivfpq"
        if isinstance(inner, (self._faiss.IndexFlat, self._faiss.IndexFlatIP, self._faiss.IndexFlatL2)):
            return "flat"
        return type(inner).__name__

    @property
    def index_params(self) -> dict:
        """Return index-specific parameters (nlist, pq_m, nprobe for IVF-PQ)."""
        if self._index is None:
            return {}
        inner = self._unwrap_index()
        if isinstance(inner, self._faiss.IndexIVFPQ):
            return {
                "nlist": inner.nlist,
                "pq_m": inner.pq.M,
                "nprobe": inner.nprobe,
            }
        return {}

    @property
    def file_size_bytes(self) -> int | None:
        """Return the on-disk size of the index file, or None if not saved."""
        path = self._path
        if path and path.exists():
            return path.stat().st_size
        return None

    def _unwrap_index(self):
        """Unwrap IndexIDMap to get the underlying index."""
        idx = self._index
        if isinstance(idx, (self._faiss.IndexIDMap, self._faiss.IndexIDMap2)):
            return self._faiss.downcast_index(idx.index)
        return idx
