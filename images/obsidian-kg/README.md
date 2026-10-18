# obsidian-kg

MCP server that exposes an Obsidian vault as a knowledge graph:
notes are nodes, `[[wikilinks]]` are edges, frontmatter `type` and
`type/…` / `area/…` tags are facets.

- **Index:** every note is parsed for frontmatter, aliases, tags, headings and
  links (wikilinks, embeds, relative markdown links). Links resolve the way
  Obsidian does (path, then basename case-insensitively, then alias). Full text
  goes into an in-memory SQLite FTS5 index.
- **Semantic search:** vectors come from Smart Connections'
  `.smart-env/multi/*.ajson` when they are fresh for a note (same size and
  mtime as its last import). Notes without fresh vectors are embedded locally
  with the same model (`TaylorAI/bge-micro-v2`, fp32 ONNX, mean pooling), so
  both sets share one vector space. Local vectors are cached in `KG_CACHE_DIR`.
- **Refresh:** the vault is re-scanned every `KG_REFRESH_SECONDS`; only changed
  notes are re-parsed and re-embedded, and the snapshot is swapped atomically.
- **Privacy:** folders in `KG_EXCLUDE` (default `Private`) and dot-folders are
  invisible, including as link targets.

- **Writes (opt-in, `KG_WRITE_ENABLED=true`):** `kg_create`, `kg_append`,
  `kg_edit` (exact unique replacement), `kg_update_frontmatter`, `kg_trash`
  (moves to `.trash/`). Writes are atomic, refuse excluded/dot/out-of-vault
  paths and duplicate note titles, honour an optional `expected_version`
  (from `kg_read`) to avoid clobbering concurrent edits, save the previous
  content under `KG_DATA_DIR/history/`, and append to `KG_DATA_DIR/audit.jsonl`
  with the `Remote-User` from the auth proxy. Changes are visible to reads
  immediately; their embeddings follow in the background.

MCP endpoint: `/mcp` (streamable HTTP, stateless). Health: `/healthz`.
There is no auth in the server itself; put it behind an authenticating proxy.

## Tools

| Tool | Purpose |
|---|---|
| `kg_overview` | Counts, types, areas, tag vocabulary, Knowledge Map, MOCs, top hubs |
| `kg_search` | Hybrid (FTS + semantic, reciprocal-rank fused) / text / semantic search with type, area, tag, folder filters |
| `kg_read` | Note content (whole, by section, or paged) + frontmatter, headings, links out, backlinks |
| `kg_neighbors` | BFS over links (in/out/both, depth ≤ 3) |
| `kg_path` | Shortest link path between two notes, skipping MOCs by default |
| `kg_similar` | Semantically similar notes, flagging which are already linked |
| `kg_list` | Metadata listing sorted by updated / links / title |
| `kg_tags` | Tag counts, optionally under a prefix |

## Environment

| Variable | Default | |
|---|---|---|
| `KG_VAULT` | `/vault` | vault root |
| `KG_EXCLUDE` | `Private` | comma-separated folders to hide |
| `KG_CACHE_DIR` | `/cache` | local vector cache |
| `KG_WRITE_ENABLED` | `false` | register the write tools |
| `KG_DATA_DIR` | `/data` | audit log + history (write mode) |
| `KG_REFRESH_SECONDS` | `60` | rescan interval |
| `KG_THREADS` | `2` | ONNX intra-op threads |
| `KG_PORT` | `8080` | |

## Local run

```sh
pip install -r requirements.txt
KG_VAULT=~/vault KG_MODEL_DIR=<dir with onnx/model.onnx + tokenizer.json> \
  KG_CACHE_DIR=/tmp/kg python -m obsidian_kg.server
```
