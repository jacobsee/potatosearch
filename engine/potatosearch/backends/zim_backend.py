"""
ZIM file storage backend.

Reads .zim files via python-libzim.  Each ZIM article becomes one Document;
the harness handles chunking.

Locator format:  "<zim_filename>::<article_path>"
    e.g.  "wikipedia_en_all.zim::A/Python_(programming_language)"

Install:  pip install libzim
"""
from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from typing import Iterator

from potatosearch.core import Document, StorageBackend

log = logging.getLogger(__name__)

# Simple HTML tag stripper (good enough for ZIM article HTML)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _html_to_text(raw_html: str) -> str:
    """Rough HTML → plaintext conversion."""
    text = _TAG_RE.sub(" ", raw_html)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


class ZimBackend(StorageBackend):
    """
    Backend for .zim archives (Kiwix offline content).

    Args:
        zim_paths: List of paths to .zim files to index.
        min_text_length: Skip articles shorter than this (filters navboxes, stubs, etc.)
    """

    def __init__(self, zim_paths: list[Path], min_text_length: int = 200, *, backend_id: str = "zim"):
        self._backend_id = backend_id
        self._zim_paths = [Path(p) for p in zim_paths]
        self._min_len = min_text_length
        # Lazily imported and cached per-file
        self._archives: dict[str, object] = {}

    @property
    def name(self) -> str:
        return self._backend_id

    def _get_archive(self, zim_path: Path):
        """Lazy-load a ZIM archive."""
        key = str(zim_path)
        if key not in self._archives:
            try:
                from libzim.reader import Archive  # type: ignore[import-untyped]
            except ImportError:
                raise ImportError(
                    "python-libzim is required for the ZIM backend. "
                    "Install it with: pip install libzim"
                )
            self._archives[key] = Archive(str(zim_path))
        return self._archives[key]

    def iterate_documents(self) -> Iterator[Document]:
        """Yield all text articles from all configured ZIM files."""
        for zim_path in self._zim_paths:
            archive = self._get_archive(zim_path)
            filename = zim_path.name
            log.info("Iterating ZIM: %s (%d entries)", filename, archive.entry_count)

            for i in range(archive.entry_count):
                try:
                    entry = archive._get_entry_by_id(i)

                    # Skip redirects and non-article entries
                    if entry.is_redirect:
                        continue

                    item = entry.get_item()

                    # Only process text content
                    mimetype = item.mimetype
                    if "text/html" not in mimetype and "text/plain" not in mimetype:
                        continue

                    raw = bytes(item.content).decode("utf-8", errors="replace")

                    if "text/html" in mimetype:
                        text = _html_to_text(raw)
                    else:
                        text = raw

                    if len(text) < self._min_len:
                        continue

                    locator = f"{filename}::{entry.path}"
                    yield Document(
                        locator=locator,
                        title=entry.title or entry.path,
                        text=text,
                        metadata={"zim_file": filename, "mimetype": mimetype},
                    )
                except Exception:
                    log.debug("Skipping entry %d in %s", i, filename, exc_info=True)
                    continue

    def retrieve_text(self, locator: str, char_start: int, char_end: int) -> str:
        """Re-read an article from the ZIM and return the requested slice."""
        return self.retrieve_document(locator)[char_start:char_end]

    def retrieve_document(self, locator: str) -> str:
        """Re-read an article from the ZIM and return the full text."""
        filename, article_path = locator.split("::", 1)

        # Find the matching ZIM path
        zim_path = None
        for p in self._zim_paths:
            if p.name == filename:
                zim_path = p
                break
        if zim_path is None:
            raise FileNotFoundError(f"ZIM file not found: {filename}")

        archive = self._get_archive(zim_path)
        entry = archive.get_entry_by_path(article_path)
        item = entry.get_item()
        raw = bytes(item.content).decode("utf-8", errors="replace")

        if "text/html" in item.mimetype:
            text = _html_to_text(raw)
        else:
            text = raw

        return text

    def document_count_hint(self) -> int | None:
        total = 0
        for p in self._zim_paths:
            try:
                archive = self._get_archive(p)
                total += archive.entry_count
            except Exception:
                pass
        return total or None
