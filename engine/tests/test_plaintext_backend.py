"""
Tests for the plaintext storage backend.
Also serves as a reference for how to test a backend plugin.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

from potatosearch.backends.plaintext_backend import PlaintextBackend, _read_file


class TestPlaintextBackend:
    def _make_files(self, tmp_path: Path) -> Path:
        """Create a small test corpus."""
        root = tmp_path / "corpus"
        root.mkdir()
        (root / "hello.txt").write_text("Hello world. This is a test document.")
        (root / "empty.txt").write_text("")
        sub = root / "subdir"
        sub.mkdir()
        (sub / "nested.md").write_text("# Heading\n\nSome nested markdown content.")
        (root / "image.png").write_bytes(b"\x89PNG")  # should be skipped
        return root

    def test_name(self):
        backend = PlaintextBackend(root_dirs=[Path("/tmp")])
        assert backend.name == "plaintext"

    def test_iterate_documents(self, tmp_path):
        root = self._make_files(tmp_path)
        backend = PlaintextBackend(root_dirs=[root])
        docs = list(backend.iterate_documents())

        # Should find hello.txt and nested.md (empty.txt skipped, image.png skipped)
        locators = {d.locator for d in docs}
        assert "hello.txt" in locators
        assert "subdir/nested.md" in locators
        assert len(docs) == 2

    def test_retrieve_text(self, tmp_path):
        root = self._make_files(tmp_path)
        backend = PlaintextBackend(root_dirs=[root])

        text = backend.retrieve_text("hello.txt", 0, 11)
        assert text == "Hello world"

        text = backend.retrieve_text("hello.txt", 6, 11)
        assert text == "world"

    def test_retrieve_nested(self, tmp_path):
        root = self._make_files(tmp_path)
        backend = PlaintextBackend(root_dirs=[root])

        text = backend.retrieve_text("subdir/nested.md", 0, 9)
        assert text == "# Heading"

    def test_missing_file_raises(self, tmp_path):
        root = self._make_files(tmp_path)
        backend = PlaintextBackend(root_dirs=[root])

        try:
            backend.retrieve_text("nonexistent.txt", 0, 10)
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_multiple_roots(self, tmp_path):
        root_a = tmp_path / "a"
        root_a.mkdir()
        (root_a / "doc_a.txt").write_text("Document A content")

        root_b = tmp_path / "b"
        root_b.mkdir()
        (root_b / "doc_b.md").write_text("Document B content")

        backend = PlaintextBackend(root_dirs=[root_a, root_b])
        docs = list(backend.iterate_documents())
        locators = {d.locator for d in docs}
        assert "doc_a.txt" in locators
        assert "doc_b.md" in locators

    def test_custom_extensions(self, tmp_path):
        root = tmp_path / "corpus"
        root.mkdir()
        (root / "notes.org").write_text("* Org mode heading")
        (root / "readme.txt").write_text("A readme")

        backend = PlaintextBackend(root_dirs=[root], extensions={".org"})
        docs = list(backend.iterate_documents())
        assert len(docs) == 1
        assert docs[0].locator == "notes.org"


class TestDocumentExtraction:
    """Tests for rich-format dispatch; library calls are mocked via _READERS."""

    def _mock_reader(self, ext, return_value, tmp_path):
        """Helper: create a fake file, patch _READERS for ext, call _read_file."""
        suffix = ext.lstrip(".")
        f = tmp_path / f"file{ext}"
        f.write_bytes(b"binary")
        mock = MagicMock(return_value=return_value)
        with patch.dict("potatosearch.backends.plaintext_backend._READERS", {ext: mock}):
            result = _read_file(f)
        mock.assert_called_once_with(f)
        assert result == return_value

    def test_read_file_dispatches_pdf(self, tmp_path):
        self._mock_reader(".pdf", "PDF text", tmp_path)

    def test_read_file_dispatches_docx(self, tmp_path):
        self._mock_reader(".docx", "DOCX text", tmp_path)

    def test_read_file_dispatches_pptx(self, tmp_path):
        self._mock_reader(".pptx", "Slide text", tmp_path)

    def test_read_file_dispatches_xlsx(self, tmp_path):
        self._mock_reader(".xlsx", "Cell text", tmp_path)

    def test_read_file_dispatches_odt(self, tmp_path):
        self._mock_reader(".odt", "ODF text", tmp_path)

    def test_read_file_dispatches_ods(self, tmp_path):
        self._mock_reader(".ods", "ODF text", tmp_path)

    def test_read_file_dispatches_odp(self, tmp_path):
        self._mock_reader(".odp", "ODF text", tmp_path)

    def test_missing_library_skipped_with_warning(self, tmp_path):
        """If a required library is absent, the file is skipped gracefully."""
        root = tmp_path / "corpus"
        root.mkdir()
        pdf = root / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        txt = root / "notes.txt"
        txt.write_text("plain text")

        with patch(
            "potatosearch.backends.plaintext_backend._read_pdf",
            side_effect=ImportError("No module named 'pypdf'"),
        ):
            backend = PlaintextBackend(root_dirs=[root])
            docs = list(backend.iterate_documents())

        # PDF skipped; plain text still included
        locators = {d.locator for d in docs}
        assert "notes.txt" in locators
        assert "report.pdf" not in locators
