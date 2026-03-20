"""
Storage backend plugin interface.

Every backend is a *stateless reader* - it knows how to:
  1. Iterate over documents in its source(s)  (for ingestion)
  2. Retrieve a specific chunk given a locator  (for query-time resolution)

The harness owns all embedding, indexing, chunking, and API concerns.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Iterator


@dataclass(frozen=True)
class Document:
    """
    A single logical document yielded by a backend during iteration.

    Attributes:
        locator:  Opaque string the backend can later use to re-fetch this
                  document.  Format is backend-defined (e.g. a ZIM article URL,
                  a filesystem path, etc.).
        title:    Human-readable title, used for optional article-level indexing.
        text:     Full plaintext content.  The harness handles chunking.
        metadata: Arbitrary extra fields (language, author, source file …).
    """
    locator: str
    title: str
    text: str
    metadata: dict = field(default_factory=dict)


class StorageBackend(abc.ABC):
    """
    Base class for all storage backend plugins.

    Subclass, implement the three abstract methods, and register via
    ``BackendRegistry.register()``.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique short name used in reference records, e.g. 'zim', 'markdown'."""
        ...

    @abc.abstractmethod
    def iterate_documents(self) -> Iterator[Document]:
        """
        Yield every document from this backend's configured source(s).

        Called during ingestion.  Backends should yield documents lazily to
        keep memory low.
        """
        ...

    @abc.abstractmethod
    def retrieve_text(self, locator: str, char_start: int, char_end: int) -> str:
        """
        Retrieve a slice of a document's text at query time.

        Parameters:
            locator:    The same locator string stored during ingestion.
            char_start: Character offset (inclusive) of the chunk start.
            char_end:   Character offset (exclusive) of the chunk end.

        Returns:
            The requested text slice.
        """
        ...

    @abc.abstractmethod
    def retrieve_document(self, locator: str) -> str:
        """
        Retrieve the full text of a document.

        Parameters:
            locator: The same locator string stored during ingestion.

        Returns:
            The complete document text.
        """
        ...

    def document_count_hint(self) -> int | None:
        """Optional: return an estimated document count for progress bars."""
        return None


class BackendRegistry:
    """Simple name → instance registry."""

    _backends: dict[str, StorageBackend] = {}
    _descriptions: dict[str, str] = {}

    @classmethod
    def register(cls, backend: StorageBackend, description: str = "") -> None:
        if backend.name in cls._backends:
            raise ValueError(f"Backend '{backend.name}' already registered")
        cls._backends[backend.name] = backend
        cls._descriptions[backend.name] = description

    @classmethod
    def get(cls, name: str) -> StorageBackend:
        return cls._backends[name]

    @classmethod
    def get_description(cls, name: str) -> str:
        return cls._descriptions.get(name, "")

    @classmethod
    def all(cls) -> dict[str, StorageBackend]:
        return dict(cls._backends)

    @classmethod
    def clear(cls) -> None:
        """Unregister all backends (used before reloading from config)."""
        cls._backends.clear()
        cls._descriptions.clear()
