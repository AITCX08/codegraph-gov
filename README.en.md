# codegraph-gov

> A local **reuse-governance** layer that sits next to a [CodeGraph](https://github.com/colbymchenry/codegraph) index and answers one question well: *before I write a new function / class / util, does an equivalent already exist somewhere in my codebase?*

[中文](README.md) | English

It fuses keyword search (CodeGraph's SQLite FTS5) with local semantic search
(ONNX embeddings, no network) via Reciprocal Rank Fusion, so it also surfaces
**same-meaning-different-name** symbols that pure keyword search misses. It
exposes an MCP tool so an AI coding agent can check for an existing
implementation automatically before authoring new code.

> Read-only: codegraph-gov never writes to the CodeGraph database.

---

## 1. Upstream: CodeGraph (the foundation this builds on)

codegraph-gov is built on top of **CodeGraph** (npm `@colbymchenry/codegraph`, MIT),
a local-first **code intelligence** tool for AI coding agents, served over MCP:

- It parses your codebase with **tree-sitter** and pre-builds a **knowledge graph**
  (symbols, call graphs, code structure) into `.codegraph/codegraph.db` at the
  project root.
- Agents **query the graph** instead of repeatedly grepping / reading files —
  **cheaper, fewer tool calls, 100% local** (official benchmark: ~16% cheaper,
  ~47% fewer tokens, ~58% fewer tool calls on average).
- Multi-language (TypeScript / Python / Rust / Java / Go / Swift / ...), multi-agent
  (Claude Code / Cursor / Codex / opencode / Gemini / ...).
- Repo: **https://github.com/colbymchenry/codegraph** · Docs:
  https://colbymchenry.github.io/codegraph/ · npm: `@colbymchenry/codegraph`

Build the index (on the CodeGraph side, once):

```bash
cd your-project
codegraph init -i      # creates .codegraph/ and builds the initial graph
```

---

## 2. Relationship to CodeGraph

| Aspect | CodeGraph (upstream) | codegraph-gov (this project) |
| --- | --- | --- |
| Role | turns your codebase **into** a queryable symbol graph | does reuse-governance **on top of** that graph |
| Order | builds `codegraph.db` **first** | works **on** it, **read-only**, never writes |
| Position | the index layer | the reuse gate **before** you author code (reuse-first) |

In one line: **CodeGraph is the foundation (the index); codegraph-gov is the
reuse check that runs on top of it, before you write code.** It does not replace
CodeGraph — it stands on the index it produces and tackles one thing:
not rebuilding wheels.

---

## 3. What it does

| Command | Purpose |
| --- | --- |
| `codegraph_reuse_candidates(intent)` (MCP tool) | ranked existing symbols matching an intent, with `file:line`, signature, caller count, cross-repo distribution |
| `python -m cg_gov.cli reuse <intent>` | the same, from the CLI |
| `python -m cg_gov.cli search <intent>` | semantic-only search |
| `python -m cg_gov.cli gate <intent>` | side-by-side FTS vs semantic comparison |
| `python -m cg_gov.cli scan` | sweep the whole index for near-duplicate symbol clusters (rebuilt wheels) and zero-caller orphans |
| `python -m cg_gov.cli gen-docs` | generate a browsable interface catalog (JSON + markdown) |
| `python -m cg_gov.cli perception-scan` | *(optional)* poll a Gitea host for newly added DB schema fields |

---

## 4. Advantages

- **Finds same-meaning-different-name implementations.** Pure keyword search can't
  tell `formatFileSize` and `bytesToHuman` are the same thing; codegraph-gov fuses
  FTS (keyword) and local semantic vectors with **RRF** so semantically-close
  symbols surface too.
- **100% local, offline by default.** Uses a local ONNX embedder (fastembed) — no
  API key, your code never leaves the machine.
- **Read-only, pollution-free.** Never writes the CodeGraph DB; drops non-canonical
  paths (worktree copies, vendored dirs, AI-tool mirror dirs, tests) so mirror
  symbols don't outrank the real source.
- **Not just check-on-write — also sweep.** `scan` surfaces near-duplicate symbol
  clusters and zero-caller orphans across the whole index.
- **Callable by AI agents.** Exposes the MCP tool `codegraph_reuse_candidates`.
- **Interface catalog + optional schema perception.** `gen-docs` and an optional
  Gitea poller.
- **Env-driven, runs out of the box.** All deployment paths are env vars with
  generic defaults.

---

## 5. How it works

```
CodeGraph's codegraph.db (symbol graph, read-only)
        │
        ▼
  extract  ── read reusable-kind symbols (function/method/class/interface/...)
        │     drop non-canonical paths (worktree/vendored/AI-mirror/tests) via canonical
        ▼
  index    ── embed each symbol's name + signature + docstring with a local ONNX
        │     model; save emb.npy + meta.json
        ▼
  reuse    ── run both searches for one intent:
        │       · FTS      (CodeGraph's bm25 keyword)
        │       · semantic (local vector cosine)
        │     fuse the two rankings with RRF; enrich top-k with caller counts +
        │     cross-repo distribution
        ▼
   ranked reuse candidates (hit -> reuse; none -> only then write new)
```

- **canonical**: decides which paths are canonical source.
- **fuse (RRF)**: `score(id) = Σ 1 / (60 + rank)` across both rankings.
- **perception (optional)**: pure-function SQL diff of old/new `.sql` into a
  structured change stream; network poll uses stdlib `urllib` with an injectable
  transport (tests run with no network).

---

## 6. Requirements

- Python 3.10+
- A `codegraph.db` index built by upstream **CodeGraph** (read-only here; not built
  by this project — see section 1).

## 7. Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## 8. Configure

| Env var | Default | Meaning |
| --- | --- | --- |
| `CODEGRAPH_WORKSPACE_ROOT` | `~/workspace` | root the CodeGraph indexer scanned |
| `CODEGRAPH_DB_PATH` | `$CODEGRAPH_WORKSPACE_ROOT/.codegraph/codegraph.db` | the read-only codegraph DB |
| `CODEGRAPH_BLACKLIST_ROOTS` | *(empty)* | comma-separated top-level dirs to treat as vendored |
| `CODEGRAPH_DOCS_MARKDOWN_OUT` | `docs/interface_catalog.md` | where `gen-docs` writes markdown |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | *(unset)* | only if you switch to the API embedder |
| `GITEA_HOST` / `GITEA_OWNER` / `GITEA_TOKEN` | examples | only for `perception-scan` |

## 9. Usage

```bash
python -m cg_gov.cli index
python -m cg_gov.cli reuse "format a byte count into a human readable string"
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

## 10. Tests

```bash
pip install -e ".[test]"
pytest
```

Hermetic: no network, no embedding model, no codegraph DB required.

## 11. License

Apache-2.0. See [LICENSE](LICENSE). CodeGraph itself belongs to its author; refer
to its [upstream repo](https://github.com/colbymchenry/codegraph) for its license.
