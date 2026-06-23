# codegraph-gov

A local **reuse-governance** layer that sits next to a `codegraph` index and
answers one question well: *before I write a new function / class / util, does an
equivalent already exist somewhere in my codebase?*

It fuses keyword search (codegraph's SQLite FTS5) with local semantic search
(ONNX embeddings, no network) via Reciprocal Rank Fusion, so it also surfaces
**same-meaning-different-name** symbols that pure keyword search misses. It
exposes an MCP tool so an AI coding agent can check for an existing
implementation automatically before authoring new code.

> Read-only: codegraph-gov never writes to the codegraph database.

## What it does

| Command | Purpose |
| --- | --- |
| `codegraph_reuse_candidates(intent)` (MCP tool) | ranked existing symbols matching an intent, with `file:line`, signature, caller count, cross-repo distribution |
| `python -m cg_gov.cli reuse <intent>` | the same, from the CLI |
| `python -m cg_gov.cli search <intent>` | semantic-only search |
| `python -m cg_gov.cli gate <intent>` | side-by-side FTS vs semantic comparison |
| `python -m cg_gov.cli scan` | sweep the whole index for near-duplicate symbol clusters (rebuilt wheels) and zero-caller orphans |
| `python -m cg_gov.cli gen-docs` | generate a browsable interface catalog (JSON + markdown) |
| `python -m cg_gov.cli perception-scan` | *(optional)* poll a Gitea host for newly added DB schema fields |

## Requirements

- Python 3.10+
- A **codegraph** SQLite index (`codegraph.db`) produced by the upstream
  codegraph indexer. codegraph-gov reads it read-only; it does not build it.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Configure

All deployment-specific paths are environment variables (see `.env.example`):

| Env var | Default | Meaning |
| --- | --- | --- |
| `CODEGRAPH_WORKSPACE_ROOT` | `~/workspace` | root the codegraph indexer scanned |
| `CODEGRAPH_DB_PATH` | `$CODEGRAPH_WORKSPACE_ROOT/.codegraph/codegraph.db` | the read-only codegraph DB |
| `CODEGRAPH_BLACKLIST_ROOTS` | *(empty)* | comma-separated top-level dirs to treat as vendored |
| `CODEGRAPH_DOCS_MARKDOWN_OUT` | `docs/interface_catalog.md` | where `gen-docs` writes markdown |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | *(unset)* | only if you switch to the API embedder |
| `GITEA_HOST` / `GITEA_OWNER` / `GITEA_TOKEN` | examples | only for `perception-scan` |

Per-project doc slices are configured in `projects.json` (copy
`projects.example.json` to start).

## Usage

```bash
# 1. build the local semantic index over the codegraph symbols
#    (first run downloads the embedding model)
python -m cg_gov.cli index

# 2. ask whether something already exists
python -m cg_gov.cli reuse "format a byte count into a human readable string"

# 3. sweep for duplicate implementations
python -m cg_gov.cli scan --reimpl-only
```

### As an MCP server

```json
{
  "mcpServers": {
    "codegraph-gov": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "cg_gov.mcp_server"],
      "env": { "CODEGRAPH_WORKSPACE_ROOT": "/path/to/your/workspace" }
    }
  }
}
```

## How it works

1. `extract` reads reusable-kind symbols (function / method / class / ...) from
   `codegraph.db`, dropping non-canonical paths (worktree copies, vendored dirs,
   AI-tool mirror dirs, tests) via `canonical`.
2. `index` embeds each symbol's name + signature + docstring with a local ONNX
   model and saves `emb.npy` + `meta.json`.
3. `reuse` runs both FTS (keyword) and semantic (cosine) search, fuses the two
   ranked lists with Reciprocal Rank Fusion, and enriches the top-k with caller
   counts and a cross-repo distribution.

## Embedding provider

`embed.py` ships two providers: `LocalFastembed` (default, ONNX, offline) and
`ApiEmbed` (OpenAI-compatible, needs `OPENAI_API_KEY`).

## Tests

```bash
pip install -e ".[test]"
pytest
```

The test suite is hermetic: it exercises the fusion, FTS sanitizer, canonical
filter, SQL schema-change parser, the cosine ranker, and the Gitea client (with
an injected fake transport) -- no network, no embedding model, no codegraph DB
required.

## License

Apache-2.0. See [LICENSE](LICENSE).
