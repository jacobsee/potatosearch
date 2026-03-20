"""
Global configuration, loaded from environment / .env / config file.
"""
import os

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    model_config = {"env_prefix": "POTATOSEARCH_"}

    # --- Paths ---
    data_dir: Path = Field(
        default=Path("./data"),
        description="Root directory for all persistent data (index, refs DB, etc.)",
    )

    # --- Embedding ---
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="sentence-transformers model name or path",
    )
    embedding_batch_size: int = Field(
        default=512,
        description="Chunks per batch during embedding",
    )
    embedding_device: str = Field(
        default="cpu",
        description="Device for embedding model: 'cpu', 'cuda', 'mps'",
    )

    # --- Chunking ---
    chunk_target_words: int = Field(default=500)
    chunk_overlap_words: int = Field(default=75)

    # --- FAISS ---
    faiss_use_mmap: bool = Field(
        default=True,
        description="Memory-map the index instead of loading into RAM",
    )
    faiss_nprobe: int = Field(
        default=32,
        description="Number of IVF clusters to probe at query time (recall vs speed)",
    )
    faiss_nlist: int = Field(
        default=4096,
        description="Number of IVF clusters (set higher for larger corpora)",
    )
    faiss_pq_m: int = Field(
        default=48,
        description="Number of PQ sub-quantizers (must divide vector dimension)",
    )
    faiss_train_sample_size: int = Field(
        default=500_000,
        description="Vectors sampled for IVF-PQ training",
    )

    # --- Query ---
    query_top_k: int = Field(default=10)

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8391

    # --- UI serving ---
    serve_ui: bool = Field(
        default=True,
        description="Mount the React SPA and static assets",
    )
    ui_dist_dir: Path = Field(
        default=Path("./ui/dist"),
        description="Path to the built React frontend (dist directory)",
    )

    @property
    def shards_dir(self) -> Path:
        return self.data_dir / "shards"

    @property
    def model_cache_dir(self) -> Path:
        return self.data_dir / "model_cache"


settings = Settings()
