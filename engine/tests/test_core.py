"""
Smoke tests for core components that don't require external models or data.
"""
import tempfile
from pathlib import Path

from potatosearch.core.chunker import chunk_text
from potatosearch.core.refs import ReferenceStore, content_hash


class TestChunker:
    def test_empty_text(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_short_text_single_chunk(self):
        text = "Hello world. " * 50  # ~100 words, under default 500
        chunks = chunk_text(text, target_words=500)
        assert len(chunks) == 1
        assert chunks[0].char_start == 0

    def test_multiple_chunks_with_overlap(self):
        # Build text with clear paragraph breaks
        paras = [f"Paragraph {i}. " + "word " * 80 for i in range(10)]
        text = "\n\n".join(paras)
        chunks = chunk_text(text, target_words=100, overlap_words=20)
        assert len(chunks) > 1
        # Verify chunks cover the text
        assert chunks[0].char_start == 0
        assert chunks[-1].char_end <= len(text)

    def test_offsets_are_valid(self):
        text = "Alpha bravo charlie.\n\nDelta echo foxtrot.\n\nGolf hotel india."
        chunks = chunk_text(text, target_words=5, overlap_words=1)
        for c in chunks:
            assert c.text == text[c.char_start:c.char_end]


class TestReferenceStore:
    def test_roundtrip(self, tmp_path):
        db_path = tmp_path / "test_refs.sqlite"
        refs = ReferenceStore(db_path)

        refs.add_chunk(0, "test", "doc1", 0, 100, "hash1", "Title 1")
        refs.add_chunk(1, "test", "doc2", 50, 200, "hash2", "Title 2")
        refs.commit()

        results = refs.get_refs([0, 1, 999])
        assert results[0].locator == "doc1"
        assert results[1].title == "Title 2"
        assert results[2] is None  # missing ID

        refs.close()

    def test_dedup(self, tmp_path):
        db_path = tmp_path / "test_refs.sqlite"
        refs = ReferenceStore(db_path)

        refs.add_chunk(0, "test", "doc1", 0, 100, "hashA")
        refs.commit()

        assert refs.has_hash("hashA") is True
        assert refs.has_hash("hashB") is False

        refs.close()

    def test_count(self, tmp_path):
        db_path = tmp_path / "test_refs.sqlite"
        refs = ReferenceStore(db_path)

        refs.add_chunk(0, "backend_a", "doc1", 0, 10, "h1")
        refs.add_chunk(1, "backend_b", "doc2", 0, 10, "h2")
        refs.add_chunk(2, "backend_a", "doc3", 0, 10, "h3")
        refs.commit()

        assert refs.count() == 3
        assert refs.count("backend_a") == 2
        assert refs.count("backend_b") == 1

        refs.close()


class TestContentHash:
    def test_deterministic(self):
        assert content_hash("hello") == content_hash("hello")
        assert content_hash("hello") != content_hash("world")
