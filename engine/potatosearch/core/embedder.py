"""
Thin wrapper around sentence-transformers for batched embedding.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import numpy as np

from potatosearch.config import settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class Embedder:
    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
    ):
        self._model_name = model_name or settings.embedding_model
        self._device = device or settings.embedding_device
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            cache_dir = settings.model_cache_dir
            cache_dir.mkdir(parents=True, exist_ok=True)

            model_basename = self._model_name.split("/")[-1]
            if any(
                d.is_dir() and d.name.startswith("models--") and model_basename in d.name
                for d in cache_dir.iterdir()
            ):
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"

            from sentence_transformers import SentenceTransformer

            import torch
            torch.set_num_threads(os.cpu_count() or 1)

            self._model = SentenceTransformer(
                self._model_name,
                device=self._device,
                cache_folder=str(cache_dir),
            )
        return self._model

    @property
    def dimension(self) -> int:
        return self.model.get_sentence_embedding_dimension()

    def embed(
        self,
        texts: list[str],
        batch_size: int | None = None,
        show_progress: bool = False,
    ) -> np.ndarray:
        """
        Encode a list of texts → (N, dim) float32 ndarray.
        """
        bs = batch_size or settings.embedding_batch_size
        return self.model.encode(
            texts,
            batch_size=bs,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )

    def embed_query(self, query: str) -> np.ndarray:
        """Embed a single query string → (1, dim) float32 ndarray."""
        return self.embed([query])
