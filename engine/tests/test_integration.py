"""
End-to-end integration test.

Ingests a small plaintext corpus through the full pipeline (chunk → embed →
index → query → retrieve) and verifies the round-trip works.

Requires sentence-transformers + faiss-cpu to be installed.
Marked slow - skip with `pytest -m "not slow"`.
"""
import pytest
from pathlib import Path

from potatosearch.core import BackendRegistry
from potatosearch.backends.plaintext_backend import PlaintextBackend
from potatosearch.core.embedder import Embedder
from potatosearch.core.index import IndexManager
from potatosearch.core.refs import ReferenceStore
from potatosearch.core.ingest import ingest
from potatosearch.core.query import query


@pytest.fixture
def corpus(tmp_path):
    """Create a small test corpus with distinct topics."""
    root = tmp_path / "corpus"
    root.mkdir()

    (root / "photosynthesis.txt").write_text(
        "Photosynthesis is the process by which green plants and certain other "
        "organisms transform light energy into chemical energy. During photosynthesis "
        "in green plants, light energy is captured and used to convert water, carbon "
        "dioxide, and minerals into oxygen and energy-rich organic compounds. "
        "The process takes place primarily in the leaves of plants, within "
        "specialized cell structures called chloroplasts. Chloroplasts contain "
        "chlorophyll, the green pigment responsible for absorbing light."
    )

    (root / "black_holes.txt").write_text(
        "A black hole is a region of spacetime where gravity is so strong that "
        "nothing, not even light or other electromagnetic waves, has enough energy "
        "to escape the event horizon. The theory of general relativity predicts "
        "that a sufficiently compact mass can deform spacetime to form a black hole. "
        "The boundary of no escape is called the event horizon. A black hole has "
        "a great effect on the fate and circumstances of an object crossing it."
    )

    (root / "bread_recipe.txt").write_text(
        "To make a simple bread loaf, combine flour, water, yeast, and salt. "
        "Knead the dough for about ten minutes until it becomes smooth and elastic. "
        "Let the dough rise in a warm place for one hour, then shape it into a loaf. "
        "Bake at 220 degrees Celsius for approximately 30 minutes until the crust "
        "is golden brown and the loaf sounds hollow when tapped on the bottom."
    )

    return root


@pytest.mark.slow
class TestEndToEnd:
    def test_ingest_and_query(self, corpus, tmp_path):
        # Setup
        backend = PlaintextBackend(root_dirs=[corpus])
        BackendRegistry._backends.clear()
        BackendRegistry.register(backend)

        embedder = Embedder(model_name="all-MiniLM-L6-v2", device="cpu")
        refs = ReferenceStore(tmp_path / "refs.sqlite")
        index = IndexManager(dimension=embedder.dimension)
        index.create_flat()

        # Ingest
        new_chunks = ingest(backend, embedder, index, refs)
        assert new_chunks > 0
        assert refs.count() == new_chunks
        assert index.ntotal == new_chunks

        # Query - should find the photosynthesis document
        results = query("How do plants convert sunlight?", embedder, index, refs, top_k=3)
        assert len(results) > 0
        top = results[0]
        assert "photosynthesis" in top.locator.lower() or "chloro" in top.text.lower()

        # Query - should find the black holes document
        results = query("What is an event horizon?", embedder, index, refs, top_k=3)
        assert len(results) > 0
        top = results[0]
        assert "black_hole" in top.locator.lower() or "event horizon" in top.text.lower()

        # Query - should find the bread document
        results = query("How do I bake bread?", embedder, index, refs, top_k=3)
        assert len(results) > 0
        top = results[0]
        assert "bread" in top.locator.lower() or "dough" in top.text.lower()

        refs.close()

    def test_dedup_on_reingest(self, corpus, tmp_path):
        """Ingesting the same backend twice should not duplicate chunks."""
        backend = PlaintextBackend(root_dirs=[corpus])
        BackendRegistry._backends.clear()
        BackendRegistry.register(backend)

        embedder = Embedder(model_name="all-MiniLM-L6-v2", device="cpu")
        refs = ReferenceStore(tmp_path / "refs.sqlite")
        index = IndexManager(dimension=embedder.dimension)
        index.create_flat()

        first_run = ingest(backend, embedder, index, refs)
        assert first_run > 0

        second_run = ingest(backend, embedder, index, refs)
        assert second_run == 0  # everything already indexed

        refs.close()
