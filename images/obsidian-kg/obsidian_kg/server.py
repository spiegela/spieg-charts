"""Read-only MCP server exposing an Obsidian vault as a knowledge graph."""
from __future__ import annotations

import argparse
import functools
import json
import logging
import os
import threading
import time
from collections import Counter

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from .embed import Embeddings
from .vault import Graph, build_notes, plain, walk_vault

log = logging.getLogger("obsidian_kg")

INSTRUCTIONS = """\
Read-only access to the user's Obsidian vault as a knowledge graph. Notes are nodes;
[[wikilinks]] are edges. Most notes carry `type` (moc, topic, entity, project,
chat-summary…) and `area/…` tags.

How to navigate:
1. Orient: kg_overview lists the entry points (Knowledge Map, MOCs, the most-linked hubs)
   and the type/area vocabulary for filters.
2. Find: kg_search (hybrid keyword + semantic) returns compact cards. Filter with
   type/area/tag/folder. Use kg_list to enumerate by metadata.
3. Expand: kg_neighbors walks links around a note. kg_similar finds related notes that
   aren't linked yet. kg_path explains how two notes connect.
4. Read: kg_read only after narrowing down. Pass `section` to read one heading, and page
   long notes with `offset`.
Cite notes by their `path`. Notes can be referenced by path, title or alias.
"""


class KG:
    def __init__(self, vault: str, exclude: list[str], model_dir: str, refresh: int, threads: int,
                 cache_dir: str | None):
        self.vault, self.exclude, self.refresh = vault, exclude, refresh
        self.emb = Embeddings(vault, model_dir, threads, cache_dir)
        self.files: dict = {}
        self.graph = Graph({})
        self.built_at = 0.0
        self.lock = threading.Lock()
        self.rebuild(embed=False)
        threading.Thread(target=self._loop, daemon=True, name="kg-refresh").start()

    def rebuild(self, embed: bool = True) -> bool:
        with self.lock:
            files = walk_vault(self.vault, self.exclude)
            changed = files != self.files
            if changed:
                t0 = time.time()
                notes = build_notes(self.vault, files, self.graph.notes)
                self.graph = Graph(notes)
                self.files = files
                self.built_at = time.time()
                log.info("graph: %d notes in %.1fs", len(notes), time.time() - t0)
            self.emb.build(self.graph, embed_missing=embed)
            return changed

    def _loop(self):
        while True:
            try:
                self.rebuild(embed=True)
            except Exception:  # keep serving the last good snapshot
                log.exception("refresh failed")
            time.sleep(self.refresh)

    # ---- presentation -------------------------------------------------------
    def card(self, p: str, **extra) -> dict:
        g = self.graph
        n = g.notes[p]
        out, inc = g.degree(p)
        c = {"path": p, "title": n.title}
        if n.type:
            c["type"] = n.type
        if n.area:
            c["area"] = n.area
        tags = [t for t in n.tags if not t.startswith(("type/", "area/"))][:6]
        if tags:
            c["tags"] = tags
        if n.summary:
            c["summary"] = n.summary
        c["links"] = {"out": out, "in": inc}
        c["updated"] = n.updated
        c.update({k: v for k, v in extra.items() if v not in (None, "", [])})
        return c

    def resolve(self, ref: str) -> str:
        p, cands = self.graph.lookup(ref)
        if p:
            return p
        if cands:
            raise ValueError(f"'{ref}' is ambiguous; use a path: {cands[:10]}")
        sugg = self.graph.suggest(ref)
        raise ValueError(f"No note '{ref}'." + (f" Did you mean: {sugg}" if sugg else ""))

    def filtered(self, type=None, area=None, tag=None, folder=None) -> set[str] | None:
        if not any((type, area, tag, folder)):
            return None
        keep = set()
        tl = tag.lower().lstrip("#") if tag else None
        fl = folder.strip("/").lower() + "/" if folder else None
        for p, n in self.graph.notes.items():
            if type and (n.type or "").lower() != type.lower():
                continue
            if area and not (n.area or "").lower().startswith(area.lower()):
                continue
            if tl and not any(t.lower() == tl or t.lower().startswith(tl + "/") for t in n.tags):
                continue
            if fl and not p.lower().startswith(fl):
                continue
            keep.add(p)
        return keep


def compact(fn):
    """Serialize tool results as compact JSON; pretty-printing wastes agent tokens."""
    @functools.wraps(fn)
    def wrapper(*a, **kw) -> str:
        return json.dumps(fn(*a, **kw), ensure_ascii=False, separators=(",", ":"))
    wrapper.__annotations__ = {**fn.__annotations__, "return": str}
    return wrapper


def create_app(kg: KG, host: str, port: int) -> FastMCP:
    mcp = FastMCP("obsidian-kg", instructions=INSTRUCTIONS, host=host, port=port,
                  stateless_http=True, json_response=True)
    _tool = mcp.tool

    def tool():
        return lambda fn: _tool(structured_output=False)(compact(fn))
    mcp.tool = tool  # type: ignore[method-assign]

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "notes": len(kg.graph.notes), "vectors": kg.emb.status})

    @mcp.tool()
    def kg_overview(hubs: int = 15) -> dict:
        """Start here. Vault size, note types, areas, tag vocabulary, and entry points:
        the Knowledge Map, every MOC, and the most-linked hub notes."""
        g = kg.graph
        types = Counter(n.type or "(none)" for n in g.notes.values())
        areas = Counter((n.area or "(none)").split("/")[0] for n in g.notes.values())
        mocs = [p for p, n in g.notes.items() if (n.type or "").lower() == "moc"]
        root = [p for p in g.notes if g.notes[p].title.lower() in ("knowledge map", "home", "index")]
        top = sorted(g.notes, key=lambda p: -len(g.incoming.get(p, ())))
        top = [p for p in top if p not in mocs and p not in root][:hubs]
        return {
            "notes": len(g.notes),
            "links": sum(len(v) for v in g.out.values()),
            "types": dict(types.most_common()),
            "areas": dict(areas.most_common()),
            "top_tags": dict((t, c) for t, c in g.tag_counts.most_common(40)
                             if not t.startswith(("type/", "area/"))),
            "entry_points": [kg.card(p) for p in root],
            "mocs": [{"path": p, "title": g.notes[p].title, "links_out": g.degree(p)[0]}
                     for p in sorted(mocs)],
            "hubs": [kg.card(p) for p in top],
            "semantic_index": kg.emb.status,
        }

    @mcp.tool()
    def kg_search(query: str, mode: str = "hybrid", type: str | None = None,
                  area: str | None = None, tag: str | None = None, folder: str | None = None,
                  limit: int = 10) -> dict:
        """Find notes. mode: "hybrid" (default; keyword + semantic, fused), "text" (exact
        words, names, identifiers) or "semantic" (concepts, paraphrases). Optional filters:
        type (e.g. topic, entity, moc, project, chat-summary), area (prefix, e.g. "tech"),
        tag, folder (path prefix). Returns cards with the best-matching passage."""
        limit = max(1, min(limit, 50))
        allowed = kg.filtered(type, area, tag, folder)
        g = kg.graph
        fused: dict[str, float] = {}
        match: dict[str, str] = {}
        if mode in ("hybrid", "text"):
            hits = [h for h in g.text_search(query, 200) if allowed is None or h[0] in allowed]
            for rank, (p, _, snip) in enumerate(hits[:60]):
                fused[p] = fused.get(p, 0) + 1 / (60 + rank)
                match.setdefault(p, snip)
        if mode in ("hybrid", "semantic") and kg.emb.store.rows:
            qv = kg.emb.encode_query(query)
            for rank, (p, score, row) in enumerate(kg.emb.store.search(qv, allowed, 60)):
                if p not in g.notes:
                    continue
                fused[p] = fused.get(p, 0) + 1 / (60 + rank)
                if row.label and (mode == "semantic" or p not in match):
                    match[p] = "§ " + row.label
        ranked = sorted(fused, key=lambda p: -fused[p])[:limit]
        return {"query": query, "mode": mode, "count": len(ranked),
                "results": [kg.card(p, match=match.get(p)) for p in ranked]}

    @mcp.tool()
    def kg_read(note: str, section: str | None = None, offset: int = 0,
                max_chars: int = 8000) -> dict:
        """Read a note (by path, title or alias). Returns frontmatter, content, headings,
        outgoing links and backlinks. Pass `section` (heading text) to read just that section;
        page long notes with `offset` (characters)."""
        p = kg.resolve(note)
        g = kg.graph
        n = g.notes[p]
        if section is None and "#" in note:
            section = note.split("#", 1)[1]
        body = n.body.strip()
        heading = None
        if section:
            heading, body = g.section(p, section)
            if body is None:
                raise ValueError(f"No section '{section}' in {p}. Headings: "
                                 f"{[h[1] for h in n.headings][:40]}")
        max_chars = max(500, min(max_chars, 40000))
        chunk = body[offset:offset + max_chars]
        incoming = g.incoming.get(p, [])
        res = {
            "path": p, "title": n.title, "frontmatter": n.frontmatter,
            "section": heading,
            "content": chunk,
            "chars": {"offset": offset, "returned": len(chunk), "total": len(body)},
            "headings": [("#" * lvl) + " " + t for lvl, t, _ in n.headings][:60],
            "links_out": [g.notes[x].title for x in g.out[p]][:100],
            "backlinks": [g.notes[x].title for x in incoming][:100],
            "backlink_count": len(incoming),
        }
        if offset + max_chars < len(body):
            res["next_offset"] = offset + max_chars
        if g.unresolved.get(p):
            res["unresolved_links"] = g.unresolved[p][:30]
        return res

    @mcp.tool()
    def kg_neighbors(note: str, depth: int = 1, direction: str = "both",
                     type: str | None = None, area: str | None = None, tag: str | None = None,
                     limit: int = 40) -> dict:
        """Walk the link graph around a note. direction: "out" (links it makes), "in"
        (backlinks) or "both". depth 1–3. Filters apply to returned nodes, not to the walk.
        Each card has `hop` and `via` (the note it was reached from)."""
        p = kg.resolve(note)
        g = kg.graph
        depth = max(1, min(depth, 3))
        allowed = kg.filtered(type, area, tag)
        seen = {p: (0, None)}
        frontier = [p]
        for hop in range(1, depth + 1):
            nxt = []
            for cur in frontier:
                for nb in g.neighbors(cur, direction):
                    if nb not in seen:
                        seen[nb] = (hop, cur)
                        nxt.append(nb)
            frontier = nxt
            if len(seen) > 2000:
                break
        nodes = [x for x in seen if x != p and (allowed is None or x in allowed)]
        nodes.sort(key=lambda x: (seen[x][0], -sum(g.degree(x))))
        limit = max(1, min(limit, 100))
        out_set, in_set = set(g.out[p]), set(g.incoming.get(p, ()))

        def rel(x):
            if seen[x][0] > 1:
                return None
            return "both" if x in out_set and x in in_set else ("out" if x in out_set else "in")

        return {"center": kg.card(p), "total": len(nodes),
                "nodes": [kg.card(x, hop=seen[x][0], edge=rel(x),
                                  via=g.notes[seen[x][1]].title if seen[x][0] > 1 else None)
                          for x in nodes[:limit]]}

    @mcp.tool()
    def kg_path(source: str, target: str, max_hops: int = 6,
                avoid_types: list[str] | None = None) -> dict:
        """Shortest link path between two notes (links followed in either direction). By
        default MOC/index notes are not used as stepping stones, so the path shows a real
        relationship; pass avoid_types=[] to allow them."""
        a, b = kg.resolve(source), kg.resolve(target)
        g = kg.graph
        avoid_types = ["moc"] if avoid_types is None else avoid_types
        at = {t.lower() for t in avoid_types}
        avoid = {p for p, n in g.notes.items() if (n.type or "").lower() in at}
        path = g.shortest_path(a, b, max(1, min(max_hops, 10)), avoid)
        if not path:
            return {"found": False, "source": a, "target": b,
                    "hint": "Try a larger max_hops, avoid_types=[], or kg_similar."}
        steps = []
        for i, x in enumerate(path):
            step = kg.card(x)
            if i:
                prev = path[i - 1]
                step["edge"] = "→" if x in g.out[prev] else "←"
            steps.append(step)
        return {"found": True, "hops": len(path) - 1, "path": steps}

    @mcp.tool()
    def kg_similar(note: str, limit: int = 10, unlinked_only: bool = False) -> dict:
        """Semantically similar notes (Smart Connections style). Each card says whether it's
        already linked; unlinked_only=True surfaces hidden connections."""
        p = kg.resolve(note)
        g = kg.graph
        v = kg.emb.store.note_vector(p)
        if v is None:
            return {"note": p, "results": [], "semantic_index": kg.emb.status}
        linked = set(g.neighbors(p))
        hits = [h for h in kg.emb.store.search(v, None, limit * 3 + 10)
                if h[0] != p and h[0] in g.notes and not (unlinked_only and h[0] in linked)]
        return {"note": p, "results": [
            kg.card(x, similarity=round(s, 3), linked=x in linked,
                    match=("§ " + r.label) if r.label else None)
            for x, s, r in hits[:max(1, min(limit, 50))]]}

    @mcp.tool()
    def kg_list(type: str | None = None, area: str | None = None, tag: str | None = None,
                folder: str | None = None, sort: str = "updated", limit: int = 50,
                offset: int = 0) -> dict:
        """List notes by metadata (like a Dataview query). sort: "updated" (newest first),
        "links" (most connected first) or "title"."""
        g = kg.graph
        allowed = kg.filtered(type, area, tag, folder)
        ps = list(g.notes) if allowed is None else list(allowed)
        if sort == "links":
            ps.sort(key=lambda p: -sum(g.degree(p)))
        elif sort == "title":
            ps.sort(key=lambda p: g.notes[p].title.lower())
        else:
            ps.sort(key=lambda p: g.notes[p].updated, reverse=True)
        limit = max(1, min(limit, 200))
        page = ps[offset:offset + limit]
        res = {"total": len(ps), "offset": offset, "results": [kg.card(p) for p in page]}
        if offset + limit < len(ps):
            res["next_offset"] = offset + limit
        return res

    @mcp.tool()
    def kg_tags(prefix: str | None = None, limit: int = 100) -> dict:
        """Tag vocabulary with note counts, optionally under a prefix (e.g. "area/")."""
        items = [(t, c) for t, c in kg.graph.tag_counts.most_common()
                 if not prefix or t.lower().startswith(prefix.lower().lstrip("#"))]
        return {"total": len(items), "tags": dict(items[:max(1, min(limit, 1000))])}

    return mcp


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault", default=os.environ.get("KG_VAULT", "/vault"))
    ap.add_argument("--exclude", default=os.environ.get("KG_EXCLUDE", "Private"),
                    help="comma-separated vault folders to hide")
    ap.add_argument("--model-dir", default=os.environ.get("KG_MODEL_DIR", "/opt/model"))
    ap.add_argument("--refresh", type=int, default=int(os.environ.get("KG_REFRESH_SECONDS", "60")))
    ap.add_argument("--threads", type=int, default=int(os.environ.get("KG_THREADS", "2")))
    ap.add_argument("--cache-dir", default=os.environ.get("KG_CACHE_DIR", "/cache"))
    ap.add_argument("--host", default=os.environ.get("KG_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("KG_PORT", "8080")))
    args = ap.parse_args()
    logging.basicConfig(level=os.environ.get("KG_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    kg = KG(args.vault, [e for e in args.exclude.split(",") if e.strip()], args.model_dir,
            args.refresh, args.threads, args.cache_dir)
    create_app(kg, args.host, args.port).run(transport="streamable-http")


if __name__ == "__main__":
    main()
