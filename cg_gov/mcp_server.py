from mcp.server.fastmcp import FastMCP
from .reuse import reuse_candidates
from .embed import LocalFastembed
from .search import DATA_DIR  # single source of truth: same dir load_index actually reads

_embedder = None


def _get_embedder():
    """Load the embedding model once; reuse across MCP requests (long-lived)."""
    global _embedder
    if _embedder is None:
        _embedder = LocalFastembed()
    return _embedder


def _reuse_tool(intent: str, k: int = 10) -> dict:
    # Check both files: index.py writes emb.npy then meta.json (non-atomic), so a
    # crash between them leaves a half-built index that must still hit this friendly
    # error instead of a raw FileNotFoundError / JSONDecodeError from load_index.
    if not ((DATA_DIR / "emb.npy").exists() and (DATA_DIR / "meta.json").exists()):
        return {"error": "semantic index not built/incomplete; run: python -m cg_gov.cli index",
                "candidates": [], "service_distribution": {}}
    return reuse_candidates(intent, k=k, embedder=_get_embedder())


mcp = FastMCP("codegraph-gov")


@mcp.tool()
def codegraph_reuse_candidates(intent: str, k: int = 10) -> dict:
    """Find existing reusable symbols across your indexed workspace by INTENT before writing a new one.

    Fuses codegraph FTS (keyword) + local semantic search (union/rerank) so it also finds
    same-meaning-different-name symbols keyword search misses. Returns ranked candidates with
    file:line, signature, caller count, cross-repo distribution. Call before authoring any
    reusable function/class/util/type.
    """
    return _reuse_tool(intent, k)


def list_registered_tool_names():
    """Test helper: names of tools registered on the FastMCP server."""
    import asyncio
    tools = asyncio.run(mcp.list_tools())
    return [t.name for t in tools]


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
