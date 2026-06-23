import sqlite3
from pathlib import Path
from .config import CODEGRAPH_DB


def get_connection(db_path: Path = CODEGRAPH_DB) -> sqlite3.Connection:
    """Open the codegraph DB strictly read-only.

    Uses mode=ro (NOT immutable) so reads stay WAL-aware and lock-safe while the
    codegraph indexer may be writing concurrently. Never writes.
    """
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    return con
