"""
MCP endpoint for potatosearch (Streamable HTTP).

Mounted on the main FastAPI server at ``/mcp``.  MCP tools operate
on the engine's in-process state - no network hop, no local data
required on the client side.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.routing import Route

from potatosearch.core import BackendRegistry
from potatosearch.core.query import query_shards

if TYPE_CHECKING:
    from fastapi import FastAPI

mcp = FastMCP(
    "potatosearch",
    instructions=(
        "potatosearch is a semantic search engine over large offline corpora. "
        "Use list_backends to discover what knowledge bases are available, "
        "then use search to find relevant information. "
        "IMPORTANT: Searching all backends simultaneously incurs a significant "
        "performance penalty - each backend must be queried and results merged. "
        "Always narrow your search to the most relevant backend(s) using the "
        "backends parameter when you have any idea which corpus is likely to "
        "contain the answer. Use get_document to retrieve the full text of a "
        "document when a search chunk is not enough."
    ),
)

# Callback returning the current _AppState; set by mount_mcp().
_get_state: Callable | None = None

# Session manager; started/stopped in the main app's lifespan.
_session_manager: StreamableHTTPSessionManager | None = None


# ── Tools ────────────────────────────────────────────────────────────────

@mcp.tool()
def list_backends() -> str:
    """List all available search backends with their descriptions and index statistics.

    Call this first to discover what knowledge bases are indexed and
    which backend IDs to pass to the search tool.
    """
    state = _get_state()
    result = []
    for name in BackendRegistry.all():
        info: dict = {
            "id": name,
            "description": BackendRegistry.get_description(name),
            "indexed_chunks": 0,
            "indexed_documents": 0,
        }
        if name in state.shards:
            shard = state.shards[name]
            info["indexed_chunks"] = shard.refs.count()
            info["indexed_documents"] = shard.refs.locator_count()
        result.append(info)
    return json.dumps(result, indent=2)


@mcp.tool()
def search(question: str, backends: list[str] | None = None, top_k: int = 10) -> str:
    """Search across indexed backends for relevant text chunks using semantic similarity.

    Args:
        question: Natural language search query.
        backends: List of backend IDs to restrict the search to. *Strongly*
                  recommended - omitting this searches all backends and incurs
                  a performance penalty proportional to the number of backends.
        top_k: Number of results to return (1-50, default 10).
    """
    state = _get_state()
    top_k = min(max(top_k, 1), 50)

    shards = state.shards
    if backends:
        shards = {k: v for k, v in shards.items() if k in backends}
        if not shards:
            available = list(state.shards.keys())
            return json.dumps({"error": f"No matching backends. Available: {available}"})

    results = query_shards(
        question=question,
        embedder=state.embedder,
        shards=shards,
        top_k=top_k,
    )

    return json.dumps(
        [
            {
                "score": round(r.score, 4),
                "backend": r.backend,
                "title": r.title,
                "text": r.text,
                "locator": r.locator,
            }
            for r in results
        ],
        indent=2,
    )


@mcp.tool()
def get_document(backend: str, locator: str) -> str:
    """Retrieve the full text of a document by its backend ID and locator.

    Use this after searching to read an entire document rather than just
    the matched chunk. The backend and locator values are returned in
    search results.

    Args:
        backend: Backend ID that owns the document (from search results).
        locator: Document locator string (from search results).
    """
    state = _get_state()

    if backend not in state.shards:
        available = list(state.shards.keys())
        return json.dumps({"error": f"Unknown backend '{backend}'. Available: {available}"})

    try:
        backend_impl = BackendRegistry.get(backend)
    except KeyError:
        return json.dumps({"error": f"Backend '{backend}' not registered"})

    try:
        text = backend_impl.retrieve_document(locator)
    except FileNotFoundError as e:
        return json.dumps({"error": str(e)})

    return json.dumps({"backend": backend, "locator": locator, "text": text}, indent=2)


# ── Mount helper ─────────────────────────────────────────────────────────

def mount_mcp(app: FastAPI, get_state: Callable) -> None:
    """
    Wire the MCP Streamable HTTP endpoint into the FastAPI app.
    """
    global _get_state, _session_manager
    _get_state = get_state

    _session_manager = StreamableHTTPSessionManager(
        app=mcp._mcp_server,
        json_response=mcp.settings.json_response,
        stateless=mcp.settings.stateless_http,
    )

    handler = StreamableHTTPASGIApp(_session_manager)
    app.router.routes.insert(0, Route("/mcp", endpoint=handler))


@asynccontextmanager
async def mcp_lifespan():
    """Start / stop the MCP session manager.  Enter inside the main lifespan."""
    if _session_manager is not None:
        async with _session_manager.run():
            yield
    else:
        yield
