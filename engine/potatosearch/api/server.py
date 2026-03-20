"""
FastAPI server - the sole API surface for potatosearch.

All interaction with the system goes through here; backends are never
exposed directly.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from potatosearch.config import settings
from potatosearch.core import BackendRegistry
from potatosearch.cli import _register_backends_from_config
from potatosearch.core.embedder import Embedder
from potatosearch.core.index import IndexManager
from potatosearch.core.progress import IngestProgress, progress_store
from potatosearch.core.query import query_shards
from potatosearch.core.ingest import ingest as do_ingest, collect_training_sample
from potatosearch.core.shard import Shard, load_shard, drop_shard
from potatosearch.mcp_server import mount_mcp, mcp_lifespan

log = logging.getLogger(__name__)

try:
    from importlib.metadata import version as _pkg_version
    _VERSION = _pkg_version("potatosearch")
except Exception:
    _VERSION = "dev"


# ── Application state ────────────────────────────────────────────────────

@dataclass
class _AppState:
    """
    All mutable singletons in one object so they can be swapped atomically.
    Endpoints capture `state = _state` at the start of each request; a
    concurrent reload swaps `_state` without disturbing in-flight requests.
    """
    embedder: Embedder
    shards: dict[str, Shard] = field(default_factory=dict)


_state: _AppState | None = None
_reload_lock: asyncio.Lock | None = None

# Background ingest threads, keyed by backend name.
_ingest_threads: dict[str, threading.Thread] = {}
_ingest_lock = threading.Lock()


def _build_state(embedder: Embedder | None = None) -> _AppState:
    """
    Construct a fresh AppState from disk.  If *embedder* is provided it is
    reused (avoids re-downloading model weights on reload).
    """
    if embedder is None:
        embedder = Embedder()

    shards = {}
    for name in BackendRegistry.all():
        shards[name] = load_shard(name, settings.shards_dir, embedder.dimension)
        log.info("Loaded shard '%s' (%d vectors)", name, shards[name].index.ntotal)

    return _AppState(embedder=embedder, shards=shards)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _state, _reload_lock

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _reload_lock = asyncio.Lock()
    _register_backends_from_config()
    _state = _build_state()

    async with mcp_lifespan():
        yield

    if _state:
        for shard in _state.shards.values():
            shard.refs.close()


app = FastAPI(
    title="potatosearch",
    description="Pointer-based retrieval-augmented generation with pluggable storage backends",
    version=_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str
    top_k: int = Field(default=10, ge=1, le=200)
    backends: list[str] | None = Field(
        default=None,
        description="Optional list of backend IDs to search (default: all)",
    )


class ChunkResponse(BaseModel):
    score: float
    backend: str
    locator: str
    title: str | None
    text: str


class QueryResponse(BaseModel):
    question: str
    results: list[ChunkResponse]


class IngestRequest(BaseModel):
    backend: str = Field(description="Backend ID to ingest from")
    train_ivfpq: bool = Field(
        default=False,
        description="Collect a training sample and create an IVF-PQ index before ingesting.",
    )
    force_train: bool = Field(
        default=False,
        description="When train_ivfpq=true, include already-indexed documents in the training sample.",
    )


class IngestStartResponse(BaseModel):
    status: str
    backend: str


class IngestProgressResponse(BaseModel):
    backend: str
    phase: str
    detail: str
    docs_processed: int
    docs_total: int | None
    chunks_new: int
    chunks_skipped: int
    chunks_target: int | None
    total_chunks: int | None
    elapsed_seconds: float
    error: str | None


class IngestStatusResponse(BaseModel):
    jobs: dict[str, IngestProgressResponse]


class StatsResponse(BaseModel):
    total_chunks: int
    backends: dict[str, int]


class ReloadResponse(BaseModel):
    status: str
    backends_before: list[str]
    backends_after: list[str]
    total_chunks: int


# ── Background ingest worker ─────────────────────────────────────────────

def _ingest_worker(
    req: IngestRequest,
    state: _AppState,
    progress: IngestProgress,
) -> None:
    """Run ingestion (optionally with IVF-PQ training) in a background thread."""
    try:
        backend = BackendRegistry.get(req.backend)

        if req.backend not in state.shards:
            state.shards[req.backend] = load_shard(
                req.backend, settings.shards_dir, state.embedder.dimension,
            )

        shard = state.shards[req.backend]

        if req.train_ivfpq and req.force_train:
            # Drop the existing shard entirely so the new index starts clean.
            # Without this, do_ingest skips all chunks via content-hash dedup
            # because refs still contains every hash from the previous run.
            log.info("force_train: dropping existing shard for '%s'", req.backend)
            shard.refs.close()
            drop_shard(req.backend, settings.shards_dir)
            shard = load_shard(req.backend, settings.shards_dir, state.embedder.dimension)
            state.shards[req.backend] = shard

        if req.train_ivfpq:
            log.info("Collecting training sample from '%s'...", req.backend)
            # After a force_train drop, refs is empty so refs_for_train=None
            # is equivalent - but be explicit for clarity.
            refs_for_train = None if req.force_train else shard.refs
            sample = collect_training_sample(
                backend, state.embedder, refs=refs_for_train, progress=progress,
            )
            if sample is None:
                progress.phase = "error"
                progress.error = "All documents already indexed; use force_train=true to retrain."
                progress.finished_at = time.time()
                return

            progress.phase = "training_index"
            progress.detail = f"Training IVF-PQ index from {len(sample):,} vectors"

            new_index = IndexManager(
                dimension=state.embedder.dimension,
                default_path=shard.shard_dir / "faiss.index",
            )
            new_index.create_ivfpq(sample)
            shard.index = new_index

        progress.docs_total = backend.document_count_hint()
        new = do_ingest(backend, state.embedder, shard.index, shard.refs, progress=progress)

        progress.chunks_new = new
        progress.total_chunks = shard.refs.count()
        progress.phase = "done"
        progress.detail = f"{new:,} new chunks ({shard.refs.count():,} total)"
        progress.finished_at = time.time()

    except Exception as e:
        log.exception("Ingestion failed for '%s'", req.backend)
        progress.phase = "error"
        progress.error = str(e)
        progress.finished_at = time.time()
    finally:
        with _ingest_lock:
            _ingest_threads.pop(req.backend, None)


# ── API Router ────────────────────────────────────────────────────────────

api_router = APIRouter(prefix="/api")


@api_router.post("/query", response_model=QueryResponse)
async def api_query(req: QueryRequest):
    state = _state
    shards = state.shards
    if req.backends:
        shards = {k: v for k, v in shards.items() if k in req.backends}
    results = query_shards(
        question=req.question,
        embedder=state.embedder,
        shards=shards,
        top_k=req.top_k,
    )
    return QueryResponse(
        question=req.question,
        results=[
            ChunkResponse(
                score=r.score,
                backend=r.backend,
                locator=r.locator,
                title=r.title,
                text=r.text,
            )
            for r in results
        ],
    )


@api_router.get("/document/{backend_id}")
async def api_get_document(backend_id: str, locator: str):
    """Retrieve the full text of a document by backend ID and locator."""
    try:
        backend = BackendRegistry.get(backend_id)
    except KeyError:
        raise HTTPException(404, f"Backend '{backend_id}' not registered")

    try:
        text = backend.retrieve_document(locator)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

    return {"backend": backend_id, "locator": locator, "text": text}


@api_router.post("/ingest", response_model=IngestStartResponse)
async def api_ingest(req: IngestRequest):
    """Kick off ingestion in a background thread. Returns immediately."""
    state = _state

    try:
        BackendRegistry.get(req.backend)
    except KeyError:
        raise HTTPException(404, f"Backend '{req.backend}' not registered")

    with _ingest_lock:
        existing = _ingest_threads.get(req.backend)
        if existing is not None and existing.is_alive():
            raise HTTPException(409, f"Ingestion already running for '{req.backend}'")

        progress = progress_store.start(req.backend)

        thread = threading.Thread(
            target=_ingest_worker,
            args=(req, state, progress),
            daemon=True,
            name=f"ingest-{req.backend}",
        )
        thread.start()
        _ingest_threads[req.backend] = thread

    return IngestStartResponse(status="started", backend=req.backend)


@api_router.get("/ingest/status", response_model=IngestStatusResponse)
async def api_ingest_status():
    """Return progress for all ingestion jobs (active and recently completed)."""
    jobs: dict[str, IngestProgressResponse] = {}
    for name, p in progress_store.all().items():
        jobs[name] = IngestProgressResponse(
            backend=p.backend,
            phase=p.phase,
            detail=p.detail,
            docs_processed=p.docs_processed,
            docs_total=p.docs_total,
            chunks_new=p.chunks_new,
            chunks_skipped=p.chunks_skipped,
            chunks_target=p.chunks_target,
            total_chunks=p.total_chunks,
            elapsed_seconds=round(p.elapsed(), 1),
            error=p.error,
        )
    return IngestStatusResponse(jobs=jobs)


@api_router.get("/backends")
async def api_backends():
    state = _state
    result = {}
    for name in BackendRegistry.all():
        info: dict = {"name": name, "description": BackendRegistry.get_description(name), "indexed_chunks": 0}
        if name in state.shards:
            shard = state.shards[name]
            info["indexed_chunks"] = shard.refs.count()
            info["indexed_documents"] = shard.refs.locator_count()
            info["index_type"] = shard.index.index_type
            info["index_params"] = shard.index.index_params
            idx_bytes = shard.index.file_size_bytes
            refs_bytes = shard.refs.file_size_bytes
            info["index_size_bytes"] = idx_bytes
            info["refs_size_bytes"] = refs_bytes
            info["total_size_bytes"] = (idx_bytes or 0) + (refs_bytes or 0)
        else:
            info["indexed_documents"] = 0
            info["index_type"] = "none"
            info["index_params"] = {}
            info["index_size_bytes"] = None
            info["refs_size_bytes"] = None
            info["total_size_bytes"] = 0
        result[name] = info
    return result


@api_router.get("/stats", response_model=StatsResponse)
async def api_stats():
    state = _state
    return StatsResponse(
        total_chunks=sum(s.refs.count() for s in state.shards.values()),
        backends={name: s.refs.count() for name, s in state.shards.items()},
    )


@api_router.delete("/backends/{backend_id}")
async def api_drop_backend(backend_id: str):
    """Drop a shard entirely - deletes its index and refs from disk."""
    state = _state
    if backend_id in state.shards:
        state.shards[backend_id].refs.close()
        del state.shards[backend_id]

    dropped = drop_shard(backend_id, settings.shards_dir)
    if not dropped:
        raise HTTPException(404, f"No shard found for '{backend_id}'")

    return {"status": "ok", "backend_id": backend_id}


def _do_reload() -> ReloadResponse:
    """
    Rebuild app state from disk without restarting the process.

    - Rereads backends.json and updates BackendRegistry.
    - Reopens the refs DB and reloads the FAISS index from disk.
    - Reuses the existing embedder so model weights are not reloaded.

    Runs in a thread pool executor to avoid blocking the event loop.
    """
    global _state

    backends_before = sorted(BackendRegistry.all().keys())
    BackendRegistry.clear()
    _register_backends_from_config()
    backends_after = sorted(BackendRegistry.all().keys())

    old_state = _state
    new_state = _build_state(embedder=old_state.embedder)

    # Swap atomically. In-flight requests that captured `state = _state`
    # before this point keep their reference to old_state and finish cleanly.
    _state = new_state

    total_chunks = sum(s.refs.count() for s in new_state.shards.values())

    log.info(
        "Reload complete: backends=%s, chunks=%d",
        backends_after, total_chunks,
    )
    return ReloadResponse(
        status="ok",
        backends_before=backends_before,
        backends_after=backends_after,
        total_chunks=total_chunks,
    )


@api_router.post("/reload", response_model=ReloadResponse)
async def api_reload():
    """
    Soft restart: reload backends.json, reopen the refs DB, and reload the
    FAISS index from disk. The embedding model is reused. Returns 409 if a
    reload is already in progress.
    """
    if _reload_lock.locked():
        raise HTTPException(409, "Reload already in progress")
    async with _reload_lock:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _do_reload)


# ── Config CRUD ───────────────────────────────────────────────────────────

def _config_path() -> Path:
    return settings.data_dir / "backends.json"


@api_router.get("/config")
async def api_get_config():
    path = _config_path()
    if not path.exists():
        return JSONResponse({"backends": []})
    try:
        data = path.read_text()
        parsed = json.loads(data)
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(500, f"failed to read config: {e}")
    return JSONResponse(parsed)


@api_router.put("/config")
async def api_put_config(request: Request):
    body = await request.body()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"invalid JSON: {e}")

    if not isinstance(parsed, dict) or "backends" not in parsed:
        raise HTTPException(400, "config must contain a 'backends' key")

    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(parsed, indent=2))

    log.info("config updated: %s", path)
    return {"status": "saved"}


def _validate_config(cfg: dict) -> list[str]:
    errs: list[str] = []

    backends = cfg.get("backends")
    if backends is None:
        return ["Config must contain a 'backends' key"]
    if not isinstance(backends, list):
        return ["'backends' must be an array"]

    for i, b in enumerate(backends):
        if not isinstance(b, dict):
            errs.append(f"backend[{i}]: must be an object")
            continue

        bid = b.get("id")
        if not isinstance(bid, str) or not bid:
            errs.append(f"backend[{i}]: missing 'id' field")

        typ = b.get("type")
        if not isinstance(typ, str) or not typ:
            errs.append(f"backend[{i}]: missing 'type' field")
        elif typ not in ("zim", "plaintext"):
            errs.append(f"backend[{i}]: unknown type '{typ}' (expected 'zim' or 'plaintext')")

        paths = b.get("paths")
        if paths is None:
            errs.append(f"backend[{i}]: missing 'paths' field")
        elif not isinstance(paths, list):
            errs.append(f"backend[{i}]: 'paths' must be an array")
        elif len(paths) == 0:
            errs.append(f"backend[{i}]: 'paths' must not be empty")

    return errs


@api_router.post("/config/validate")
async def api_validate_config(request: Request):
    body = await request.body()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as e:
        return {"valid": False, "errors": [f"Invalid JSON: {e}"]}

    if not isinstance(parsed, dict):
        return {"valid": False, "errors": ["Config must be a JSON object"]}

    errors = _validate_config(parsed)
    return {"valid": len(errors) == 0, "errors": errors}


# ── Health ────────────────────────────────────────────────────────────────

@api_router.get("/health")
async def api_health():
    return {"status": "ok", "engine": "connected"}


# ── Mount router ──────────────────────────────────────────────────────────

app.include_router(api_router)


# ── MCP (Streamable HTTP) ────────────────────────────────────────────────

mount_mcp(app, lambda: _state)


# ── SPA serving (conditional on serve_ui) ─────────────────────────────────

if settings.serve_ui:
    dist_dir = settings.ui_dist_dir.resolve()
    assets_dir = dist_dir / "assets"
    index_html = dist_dir / "index.html"

    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        # Serve static files from dist if they exist, otherwise index.html
        file_path = dist_dir / path
        if path and file_path.is_file():
            return FileResponse(str(file_path))
        if index_html.is_file():
            return FileResponse(str(index_html))
        raise HTTPException(404, "UI not built - set POTATOSEARCH_SERVE_UI=false or build the frontend")


def main():
    import uvicorn
    uvicorn.run(
        "potatosearch.api.server:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
