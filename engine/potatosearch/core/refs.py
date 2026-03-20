"""
Lightweight SQLite store that maps FAISS integer IDs → backend locators.

Schema:
    chunks:
        id           INTEGER PRIMARY KEY   -- matches the FAISS vector ID
        backend      TEXT NOT NULL          -- backend name, e.g. 'zim'
        locator      TEXT NOT NULL          -- backend-defined doc identifier
        char_start   INTEGER NOT NULL
        char_end     INTEGER NOT NULL
        content_hash TEXT NOT NULL          -- SHA-256 of chunk text (for dedup)
        title        TEXT                   -- document title (for display)

    locator_epochs:
        backend      TEXT NOT NULL
        locator      TEXT NOT NULL
        epoch        INTEGER NOT NULL       -- last ingestion epoch this locator was seen
        PRIMARY KEY (backend, locator)

    meta:
        key   TEXT PRIMARY KEY
        value TEXT
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChunkRef:
    id: int
    backend: str
    locator: str
    char_start: int
    char_end: int
    title: str | None = None


class ReferenceStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS chunks (
                id           INTEGER PRIMARY KEY,
                backend      TEXT NOT NULL,
                locator      TEXT NOT NULL,
                char_start   INTEGER NOT NULL,
                char_end     INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                title        TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_hash    ON chunks(content_hash);
            CREATE INDEX IF NOT EXISTS idx_chunks_backend ON chunks(backend);
            CREATE INDEX IF NOT EXISTS idx_chunks_locator ON chunks(backend, locator);

            CREATE TABLE IF NOT EXISTS locator_epochs (
                backend TEXT    NOT NULL,
                locator TEXT    NOT NULL,
                epoch   INTEGER NOT NULL,
                PRIMARY KEY (backend, locator)
            );

            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        self._conn.commit()

    # ── Epoch tracking ───────────────────────────────────────────────────

    def next_epoch(self, backend: str) -> int:
        """Atomically increment and return the ingestion epoch for this backend."""
        key = f"epoch.{backend}"
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        epoch = (int(row[0]) if row else 0) + 1
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (key, str(epoch)),
        )
        self._conn.commit()
        return epoch

    def touch_locators(self, locators: list[str], backend: str, epoch: int) -> None:
        """Record that these locators were encountered in the current ingestion epoch."""
        if not locators:
            return
        self._conn.executemany(
            "INSERT OR REPLACE INTO locator_epochs (backend, locator, epoch) VALUES (?, ?, ?)",
            ((backend, loc, epoch) for loc in locators),
        )
        self._conn.commit()

    def build_stale_snapshot(self, backend: str, epoch: int) -> tuple[int, int]:
        """
        Snapshot all chunk IDs whose locator was not touched with epoch into a
        temporary table.  This includes locators that pre-date epoch tracking
        (LEFT JOIN null) as well as locators seen in previous runs but absent now.

        Returns (distinct_stale_locators, total_stale_chunks).
        Call iter_stale_chunk_id_batches() then drop_stale_snapshot() after.
        """
        self._conn.execute("DROP TABLE IF EXISTS _stale_snapshot")
        self._conn.execute("""
            CREATE TEMP TABLE _stale_snapshot AS
            SELECT c.id, c.locator
            FROM   chunks c
            LEFT JOIN locator_epochs le
                   ON c.backend = le.backend AND c.locator = le.locator
            WHERE  c.backend = ?
              AND  (le.epoch IS NULL OR le.epoch < ?)
        """, (backend, epoch))
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT locator), COUNT(id) FROM _stale_snapshot"
        ).fetchone()
        return row[0], row[1]

    def iter_stale_chunk_id_batches(self, batch_size: int = 500):
        """
        Yield batches of chunk IDs from the stale snapshot.
        Must call build_stale_snapshot() first.
        Iterates a separate temp table so concurrent deletes from chunks
        do not disturb the cursor.
        """
        cur = self._conn.execute("SELECT id FROM _stale_snapshot")
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            yield [r[0] for r in rows]

    def drop_stale_snapshot(self) -> None:
        self._conn.execute("DROP TABLE IF EXISTS _stale_snapshot")

    def prune_epoch_rows(self, backend: str, epoch: int) -> None:
        """Remove locator_epochs rows older than the current epoch."""
        self._conn.execute(
            "DELETE FROM locator_epochs WHERE backend = ? AND epoch < ?",
            (backend, epoch),
        )
        self._conn.commit()

    # ── Writes ───────────────────────────────────────────────────────────

    def next_id(self) -> int:
        """Return the next available chunk ID."""
        row = self._conn.execute("SELECT MAX(id) FROM chunks").fetchone()
        return (row[0] or -1) + 1

    def add_chunk(
        self,
        chunk_id: int,
        backend: str,
        locator: str,
        char_start: int,
        char_end: int,
        content_hash: str,
        title: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO chunks (id, backend, locator, char_start, char_end, content_hash, title) "
            "VALUES (?, ?, ?, ?, ?,  ?, ?)",
            (chunk_id, backend, locator, char_start, char_end, content_hash, title),
        )

    def delete_chunks_by_ids(self, ids: list[int]) -> int:
        """Delete chunk rows by FAISS ID. Returns row count deleted."""
        if not ids:
            return 0
        total = 0
        for batch in _batched(ids, 500):
            placeholders = ",".join("?" for _ in batch)
            cur = self._conn.execute(
                f"DELETE FROM chunks WHERE id IN ({placeholders})", batch
            )
            total += cur.rowcount
        return total

    def commit(self) -> None:
        self._conn.commit()

    # ── Reads ────────────────────────────────────────────────────────────

    def get_refs(self, ids: list[int]) -> list[ChunkRef | None]:
        """Look up multiple chunk references by ID.  Returns None for missing IDs."""
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT id, backend, locator, char_start, char_end, title "
            f"FROM chunks WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        by_id = {r[0]: ChunkRef(*r) for r in rows}
        return [by_id.get(i) for i in ids]

    def has_locator(self, locator: str, backend: str) -> bool:
        """Return True if any chunk from this locator is already indexed."""
        row = self._conn.execute(
            "SELECT 1 FROM chunks WHERE backend = ? AND locator = ? LIMIT 1",
            (backend, locator),
        ).fetchone()
        return row is not None

    def has_hash(self, content_hash: str) -> bool:
        """Check if a chunk with this content hash already exists (for dedup)."""
        row = self._conn.execute(
            "SELECT 1 FROM chunks WHERE content_hash = ? LIMIT 1",
            (content_hash,),
        ).fetchone()
        return row is not None

    def count(self, backend: str | None = None) -> int:
        if backend:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE backend = ?", (backend,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return row[0]

    def locator_count(self, backend: str | None = None) -> int:
        """Return the number of distinct document locators."""
        if backend:
            row = self._conn.execute(
                "SELECT COUNT(DISTINCT locator) FROM chunks WHERE backend = ?", (backend,)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(DISTINCT locator) FROM chunks"
            ).fetchone()
        return row[0]

    @property
    def file_size_bytes(self) -> int | None:
        """Return the on-disk size of the refs database."""
        if self._db_path.exists():
            return self._db_path.stat().st_size
        return None

    def get_all_locators(self, backend: str) -> set[str]:
        """Return all distinct locators for a backend (useful for debugging)."""
        rows = self._conn.execute(
            "SELECT DISTINCT locator FROM chunks WHERE backend = ?", (backend,)
        ).fetchall()
        return {r[0] for r in rows}

    # ── Meta ─────────────────────────────────────────────────────────────

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _batched(items: list, size: int):
    """Yield successive slices of items of at most size elements."""
    for i in range(0, len(items), size):
        yield items[i : i + size]
