"""
CLI for ingestion, queries, and shard management.

Usage:
    python -m potatosearch.cli ingest --backend wikipedia-en --train
    python -m potatosearch.cli query "What is photosynthesis?"
    python -m potatosearch.cli stats
    python -m potatosearch.cli drop --backend wikipedia-en
"""
from __future__ import annotations

import argparse
import logging
import sys

from potatosearch.config import settings


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def cmd_ingest(args: argparse.Namespace) -> None:
    from potatosearch.core import BackendRegistry
    from potatosearch.core.embedder import Embedder
    from potatosearch.core.index import IndexManager
    from potatosearch.core.ingest import ingest, collect_training_sample
    from potatosearch.core.shard import load_shard

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _register_backends_from_config()

    embedder = Embedder()
    backend = BackendRegistry.get(args.backend)
    shard = load_shard(args.backend, settings.shards_dir, embedder.dimension)

    if args.train:
        logging.info("Collecting training sample...")
        sample = collect_training_sample(
            backend, embedder,
            refs=None if args.force else shard.refs,
        )
        if sample is None:
            print("All documents already indexed; nothing to train on. Use --force to retrain anyway.")
            return
        new_index = IndexManager(
            dimension=embedder.dimension,
            default_path=shard.shard_dir / "faiss.index",
        )
        new_index.create_ivfpq(sample)
        shard.index = new_index

    new = ingest(backend, embedder, shard.index, shard.refs)
    print(f"Ingested {new} new chunks from '{args.backend}'. Total in shard: {shard.refs.count()}")


def cmd_query(args: argparse.Namespace) -> None:
    from potatosearch.core import BackendRegistry
    from potatosearch.core.embedder import Embedder
    from potatosearch.core.query import query_shards
    from potatosearch.core.shard import load_shard

    _register_backends_from_config()
    embedder = Embedder()

    shards = {}
    for name in BackendRegistry.all():
        shard_dir = settings.shards_dir / name
        if (shard_dir / "faiss.index").exists():
            shards[name] = load_shard(name, settings.shards_dir, embedder.dimension)

    if not shards:
        print("No indexed shards found. Run 'ingest' first.")
        return

    results = query_shards(args.question, embedder, shards, top_k=args.top_k)
    for i, r in enumerate(results, 1):
        print(f"\n── Result {i} (score: {r.score:.4f}) ──")
        print(f"   Backend: {r.backend}  |  Source: {r.locator}")
        if r.title:
            print(f"   Title: {r.title}")
        print(f"   {r.text[:300]}{'...' if len(r.text) > 300 else ''}")


def cmd_stats(args: argparse.Namespace) -> None:
    from potatosearch.core.index import IndexManager
    from potatosearch.core.refs import ReferenceStore

    shards_dir = settings.shards_dir
    if not shards_dir.exists() or not any(shards_dir.iterdir()):
        print("No shards found.")
        return

    total_chunks = 0
    total_vectors = 0
    for shard_name in sorted(p.name for p in shards_dir.iterdir() if p.is_dir()):
        shard_dir = shards_dir / shard_name
        refs_path = shard_dir / "refs.sqlite"
        index_path = shard_dir / "faiss.index"

        chunks = 0
        if refs_path.exists():
            refs = ReferenceStore(refs_path)
            chunks = refs.count()
            refs.close()

        vectors = 0
        if index_path.exists():
            index = IndexManager(dimension=0)
            index.load(path=index_path)
            vectors = index.ntotal

        print(f"  {shard_name}: {chunks} chunks, {vectors} vectors")
        total_chunks += chunks
        total_vectors += vectors

    print(f"Total: {total_chunks} chunks, {total_vectors} vectors")


def cmd_drop(args: argparse.Namespace) -> None:
    from potatosearch.core.shard import drop_shard

    if drop_shard(args.backend, settings.shards_dir):
        print(f"Dropped shard '{args.backend}'")
    else:
        print(f"No shard found for '{args.backend}'")


def _register_backends_from_config() -> None:
    """
    Bootstrap backends from a config file or environment.
    Customize this for your setup.
    """
    import json
    from pathlib import Path
    from potatosearch.core import BackendRegistry

    config_path = settings.data_dir / "backends.json"
    if not config_path.exists():
        logging.warning(
            "No backends.json found at %s. Create one to configure backends. "
            "See README for format.",
            config_path,
        )
        return

    config_dir = config_path.resolve().parent

    with open(config_path) as f:
        config = json.load(f)

    def _resolve(p: str) -> Path:
        """Resolve a path relative to the backends.json directory."""
        path = Path(p)
        if not path.is_absolute():
            path = config_dir / path
        return path

    for entry in config.get("backends", []):
        btype = entry["type"]
        backend_id = entry.get("id", btype)
        description = entry.get("description", "")
        if btype == "zim":
            from potatosearch.backends.zim_backend import ZimBackend
            backend = ZimBackend(
                zim_paths=[_resolve(p) for p in entry["paths"]],
                min_text_length=entry.get("min_text_length", 200),
                backend_id=backend_id,
            )
        elif btype == "plaintext":
            from potatosearch.backends.plaintext_backend import PlaintextBackend
            backend = PlaintextBackend(
                root_dirs=[_resolve(p) for p in entry["paths"]],
                backend_id=backend_id,
            )
        else:
            logging.warning("Unknown backend type: %s", btype)
            continue

        BackendRegistry.register(backend, description=description)
        logging.info("Registered backend: %s (%s)", backend.name, btype)


def ingest_main():
    """Entry point for potatosearch-ingest script."""
    parser = argparse.ArgumentParser(description="potatosearch ingestion")
    parser.add_argument("--backend", required=True, help="Backend ID to ingest")
    parser.add_argument("--train", action="store_true", help="Train IVF-PQ index first")
    parser.add_argument("--force", action="store_true", help="Retrain even on already-indexed documents")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    _setup_logging(args.verbose)
    cmd_ingest(args)


def main():
    parser = argparse.ArgumentParser(description="potatosearch CLI")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest from a backend")
    p_ingest.add_argument("--backend", required=True)
    p_ingest.add_argument("--train", action="store_true", help="Train IVF-PQ first")
    p_ingest.add_argument("--force", action="store_true", help="Retrain even on already-indexed documents")

    p_query = sub.add_parser("query", help="Query the index")
    p_query.add_argument("question")
    p_query.add_argument("--top-k", type=int, default=5)

    sub.add_parser("stats", help="Show per-shard index stats")

    p_drop = sub.add_parser("drop", help="Drop a shard (delete index + refs)")
    p_drop.add_argument("--backend", required=True)

    args = parser.parse_args()
    _setup_logging(args.verbose)

    if args.command == "ingest":
        cmd_ingest(args)
    elif args.command == "query":
        cmd_query(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "drop":
        cmd_drop(args)


if __name__ == "__main__":
    main()
