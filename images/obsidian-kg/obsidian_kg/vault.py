"""Parse an Obsidian vault into notes, a link graph and a full-text index."""
from __future__ import annotations

import datetime as dt
import itertools
import logging
import os
import re
import sqlite3
import urllib.parse
from collections import Counter, defaultdict, deque
from dataclasses import dataclass

import yaml

log = logging.getLogger("obsidian_kg.vault")

FENCE_RE = re.compile(r"^(```|~~~).*?^\1", re.M | re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
WIKILINK_RE = re.compile(r"(!?)\[\[([^\[\]|#^]*)(#[^\[\]|]*)?(?:\|([^\[\]]*))?\]\]")
MDLINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+?\.md)(#[^)]*)?\)")
TAG_RE = re.compile(r"(?<![\w/#&])#([A-Za-z_][\w/-]*)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)
CALLOUT_RE = re.compile(r"^>\s*\[!(\w+)\][-+]?\s*(.*)$", re.M)


def strip_code(text: str) -> str:
    return INLINE_CODE_RE.sub("", FENCE_RE.sub("", text))


def plain(text: str) -> str:
    """Markdown → compact plain text, for summaries and snippets."""
    text = WIKILINK_RE.sub(lambda m: m.group(4) or m.group(2), text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`>#]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _jsonable(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def split_frontmatter(text: str) -> tuple[dict, str, str, int]:  # type: ignore[return]
    """Return (frontmatter, raw frontmatter, body, body start line [1-based])."""
    if not text.startswith("---"):
        return {}, "", text, 1
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(\r?\n|$)", text, re.S)
    if not m:
        return {}, "", text, 1
    raw = m.group(1)
    try:
        fm = yaml.safe_load(raw) or {}
        if not isinstance(fm, dict):
            fm = {}
    except yaml.YAMLError:
        fm = {}
    body = text[m.end():]
    return _jsonable(fm), raw, body, text[: m.end()].count("\n") + 1


def as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [s for s in re.split(r"[,\s]+", v) if s]
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if x is not None]
    return [str(v)]


@dataclass
class Note:
    path: str  # vault-relative, with .md
    title: str
    mtime: float
    size: int
    frontmatter: dict
    body: str
    body_line: int
    aliases: list[str]
    tags: list[str]
    type: str | None
    area: str | None
    headings: list[tuple[int, str, int]]  # (level, text, line)
    raw_links: list[str]  # unresolved link targets, in order
    summary: str
    updated: str

    @property
    def folder(self) -> str:
        return os.path.dirname(self.path)


def summarize(fm: dict, body: str, limit: int = 240) -> str:
    for key in ("summary", "description", "tldr"):
        if isinstance(fm.get(key), str) and fm[key].strip():
            return plain(fm[key])[:limit]
    m = CALLOUT_RE.search(body)
    if m and m.group(1).lower() in ("tldr", "summary", "abstract", "info", "note"):
        lines = [m.group(2)]
        for ln in body[m.end():].split("\n")[1:]:
            if not ln.startswith(">"):
                break
            lines.append(ln.lstrip("> "))
        s = plain(" ".join(lines))
        if s:
            return s[:limit]
    for para in re.split(r"\n\s*\n", strip_code(body)):
        p = para.strip()
        if not p or p.startswith(("#", "|", "---", "![[", "<")):
            continue
        s = plain(p)
        if len(s) > 20:
            return s[:limit]
    return ""


def parse_note(root: str, rel: str) -> Note:
    full = os.path.join(root, rel)
    st = os.stat(full)
    with open(full, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    fm, fm_raw, body, body_line = split_frontmatter(text)
    title = os.path.basename(rel)[:-3]
    aliases = as_list(fm.get("aliases")) + as_list(fm.get("alias"))
    if isinstance(fm.get("aliases"), str):
        aliases = [fm["aliases"]]
    code_free = strip_code(body)
    tags = [t.lstrip("#") for t in as_list(fm.get("tags")) + as_list(fm.get("tag"))]
    tags += TAG_RE.findall(code_free)
    tags = list(dict.fromkeys(t for t in tags if t and not t.isdigit()))
    ntype = fm.get("type") if isinstance(fm.get("type"), str) else None
    area = None
    for t in tags:
        if not ntype and t.startswith("type/"):
            ntype = t[5:]
        if not area and t.startswith("area/"):
            area = t[5:]
    raw_links = []
    for m in WIKILINK_RE.finditer(fm_raw + "\n" + code_free):
        if m.group(2).strip():
            raw_links.append(m.group(2).strip())
    for m in MDLINK_RE.finditer(code_free):
        target = urllib.parse.unquote(m.group(2))
        if not re.match(r"^[a-z]+://", target):
            raw_links.append(os.path.normpath(os.path.join(os.path.dirname(rel), target)))
    headings = []
    for m in HEADING_RE.finditer(body):
        line = body_line + body[: m.start()].count("\n")
        headings.append((len(m.group(1)), plain(m.group(2)), line))
    # Drop headings that are inside code fences.
    fenced = [(m.start(), m.end()) for m in FENCE_RE.finditer(body)]
    if fenced:
        lines = body.split("\n")
        offsets, pos = [], 0
        for ln in lines:
            offsets.append(pos)
            pos += len(ln) + 1
        headings = [h for h in headings
                    if not any(a <= offsets[h[2] - body_line] < b for a, b in fenced)]
    updated = fm.get("updated") or fm.get("modified") or fm.get("created")
    updated = str(updated)[:10] if updated else dt.date.fromtimestamp(st.st_mtime).isoformat()
    return Note(path=rel, title=title, mtime=st.st_mtime, size=st.st_size, frontmatter=fm,
                body=body, body_line=body_line, aliases=aliases, tags=tags, type=ntype,
                area=area, headings=headings, raw_links=raw_links,
                summary=summarize(fm, body), updated=updated)


def walk_vault(root: str, exclude: list[str]) -> dict[str, tuple[float, int]]:
    """Map relative note path → (mtime, size) for every visible note."""
    excl = {e.strip("/").lower() for e in exclude if e.strip("/")}
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames[:] = [d for d in dirnames if not d.startswith(".")
                       and os.path.join(rel_dir, d).lower() not in excl]
        for fn in filenames:
            if fn.endswith(".md") and not fn.startswith("."):
                rel = os.path.join(rel_dir, fn)
                try:
                    st = os.stat(os.path.join(root, rel))
                except OSError:
                    continue
                found[rel] = (st.st_mtime, st.st_size)
    return found


class Graph:
    """Immutable snapshot: notes, resolved links, name lookup and FTS index."""

    _generations = itertools.count(1)

    def __init__(self, notes: dict[str, Note]):
        self.generation = next(Graph._generations)
        self.notes = notes
        self.by_name: dict[str, list[str]] = defaultdict(list)
        self.by_alias: dict[str, list[str]] = defaultdict(list)
        self.by_path: dict[str, str] = {}
        for p, n in notes.items():
            self.by_name[n.title.lower()].append(p)
            self.by_path[p.lower()] = p
            self.by_path[p[:-3].lower()] = p
            for a in n.aliases:
                self.by_alias[a.lower()].append(p)
        for lst in list(self.by_name.values()) + list(self.by_alias.values()):
            lst.sort(key=lambda p: (p.count("/"), len(p), p))
        # Links live on the snapshot, not the Note, because unchanged Note objects
        # are shared between consecutive snapshots.
        self.out: dict[str, list[str]] = {}
        self.unresolved: dict[str, list[str]] = {}
        self.incoming: dict[str, list[str]] = defaultdict(list)
        for p, n in notes.items():
            out, unresolved = [], []
            for t in n.raw_links:
                r = self.resolve_link(t)
                if r and r != p:
                    if r not in out:
                        out.append(r)
                elif not r and t not in unresolved:
                    unresolved.append(t)
            self.out[p], self.unresolved[p] = out, unresolved
            for r in out:
                self.incoming[r].append(p)
        self.tag_counts = Counter(t for n in notes.values() for t in n.tags)
        self._build_fts()

    # ---- lookup -------------------------------------------------------------
    def resolve_link(self, target: str) -> str | None:
        t = target.strip().replace("\\", "/").lstrip("/")
        low = t.lower()
        if low.endswith(".md"):
            low = low[:-3]
        if "/" in low:
            if low in self.by_path:
                return self.by_path[low]
            suffix = "/" + low + ".md"
            hits = [p for p in self.notes if p.lower().endswith(suffix)]
            if hits:
                return min(hits, key=len)
            low = low.rsplit("/", 1)[-1]
        if low in self.by_name:
            return self.by_name[low][0]
        if low in self.by_alias:
            return self.by_alias[low][0]
        return None

    def lookup(self, ref: str) -> tuple[str | None, list[str]]:
        """Resolve a user/agent reference. Returns (path, candidates-if-ambiguous)."""
        ref = ref.strip()
        if ref.startswith("[[") and ref.endswith("]]"):
            ref = ref[2:-2].split("|")[0]
        ref = ref.split("#")[0].strip()
        low = ref.lower()
        if low in self.by_path or low.removesuffix(".md") in self.by_path:
            return self.by_path.get(low) or self.by_path[low.removesuffix(".md")], []
        name = low.rsplit("/", 1)[-1].removesuffix(".md")
        hits = self.by_name.get(name) or self.by_alias.get(name) or []
        if len(hits) == 1:
            return hits[0], []
        if hits:
            return None, hits
        return None, []

    def suggest(self, ref: str, n: int = 5) -> list[str]:
        import difflib
        names = {self.notes[p].title: p for p in self.notes}
        for a, ps in self.by_alias.items():
            names.setdefault(a, ps[0])
        close = difflib.get_close_matches(ref, list(names), n=n, cutoff=0.5)
        low = ref.lower()
        subs = [k for k in names if low in k.lower()][:n]
        return list(dict.fromkeys(names[k] for k in subs + close))[:n]

    # ---- graph --------------------------------------------------------------
    def degree(self, p: str) -> tuple[int, int]:
        return len(self.out[p]), len(self.incoming.get(p, ()))

    def neighbors(self, p: str, direction: str = "both") -> list[str]:
        out = self.out[p] if direction in ("both", "out") else []
        inc = self.incoming.get(p, []) if direction in ("both", "in") else []
        return list(dict.fromkeys(out + inc))

    def shortest_path(self, a: str, b: str, max_hops: int, avoid: set[str]) -> list[str] | None:
        prev: dict[str, str | None] = {a: None}
        q = deque([(a, 0)])
        while q:
            cur, d = q.popleft()
            if cur == b:
                path = [b]
                while (step := prev[path[-1]]) is not None:
                    path.append(step)
                return path[::-1]
            if d >= max_hops:
                continue
            for nb in self.neighbors(cur):
                if nb in prev or (nb in avoid and nb != b):
                    continue
                prev[nb] = cur
                q.append((nb, d + 1))
        return None

    # ---- full text ----------------------------------------------------------
    def _build_fts(self):
        db = sqlite3.connect(":memory:", check_same_thread=False)
        db.execute("CREATE VIRTUAL TABLE fts USING fts5(path UNINDEXED, title, aliases, tags,"
                   " headings, body, tokenize='porter unicode61')")
        db.executemany("INSERT INTO fts VALUES (?,?,?,?,?,?)", [
            (p, n.title, " ".join(n.aliases), " ".join(t.replace("/", " ") for t in n.tags),
             " ".join(h[1] for h in n.headings), strip_code(n.body))
            for p, n in self.notes.items()])
        self.db = db

    def text_search(self, query: str, limit: int = 50) -> list[tuple[str, float, str]]:
        words = re.findall(r"[\w][\w'-]*", query.lower())
        if not words:
            return []
        q = " OR ".join('"%s"' % w.replace('"', "") for w in words)
        if len(words) > 1:
            q = '"%s" OR %s' % (" ".join(words).replace('"', ""), q)
        try:
            rows = self.db.execute(
                "SELECT path, bm25(fts, 0, 10.0, 8.0, 4.0, 3.0, 1.0) AS s,"
                " snippet(fts, 5, '', '', '…', 16) FROM fts WHERE fts MATCH ? ORDER BY s LIMIT ?",
                (q, limit)).fetchall()
        except sqlite3.OperationalError as e:
            log.warning("fts query failed %r: %s", q, e)
            return []
        return [(p, -s, plain(snip).replace("[[", "").replace("]]", "")) for p, s, snip in rows]

    # ---- sections -----------------------------------------------------------
    def section(self, p: str, heading: str) -> tuple[str | None, str | None]:
        n = self.notes[p]
        want = heading.strip().lstrip("#").strip().lower()
        lines = n.body.split("\n")
        for i, (lvl, text, line) in enumerate(n.headings):
            if text.lower() == want or (want and want in text.lower()):
                end = len(lines) + n.body_line
                for lvl2, _, line2 in n.headings[i + 1:]:
                    if lvl2 <= lvl:
                        end = line2
                        break
                return text, "\n".join(lines[line - n.body_line:end - n.body_line]).strip()
        return None, None


def build_notes(root: str, files: dict[str, tuple[float, int]],
                previous: dict[str, Note] | None = None) -> dict[str, Note]:
    notes = {}
    previous = previous or {}
    for rel, (mtime, size) in files.items():
        old = previous.get(rel)
        if old and old.mtime == mtime and old.size == size:
            notes[rel] = old
            continue
        try:
            notes[rel] = parse_note(root, rel)
        except (OSError, UnicodeError) as e:
            log.warning("skip %s: %s", rel, e)
    return notes
