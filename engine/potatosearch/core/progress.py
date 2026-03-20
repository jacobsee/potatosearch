"""
In-memory progress tracking for ingestion jobs.

Progress objects are written by worker threads and read by the status
endpoint.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class IngestProgress:
    """Mutable progress state for one backend's ingestion job."""

    backend: str
    phase: str = "starting"
    detail: str = ""
    docs_processed: int = 0
    docs_total: int | None = None
    chunks_new: int = 0
    chunks_skipped: int = 0
    chunks_target: int | None = None
    total_chunks: int | None = None  # set on completion
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None

    def elapsed(self) -> float:
        end = self.finished_at or time.time()
        return end - self.started_at


class ProgressStore:
    """Thread-safe dict of per-backend progress."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, IngestProgress] = {}

    def start(self, backend: str) -> IngestProgress:
        p = IngestProgress(backend=backend)
        with self._lock:
            self._jobs[backend] = p
        return p

    def get(self, backend: str) -> IngestProgress | None:
        with self._lock:
            return self._jobs.get(backend)

    def all(self) -> dict[str, IngestProgress]:
        with self._lock:
            return dict(self._jobs)

    def is_running(self, backend: str) -> bool:
        with self._lock:
            p = self._jobs.get(backend)
            return p is not None and p.phase not in ("done", "error")


progress_store = ProgressStore()
