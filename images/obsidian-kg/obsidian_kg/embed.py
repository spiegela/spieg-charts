"""Semantic vectors: reuse Smart Connections embeddings, fill gaps with the same model."""
from __future__ import annotations

import glob
import json
import logging
import os
import pickle
import threading
import time
from dataclasses import dataclass

import numpy as np

from .vault import Graph, Note

log = logging.getLogger("obsidian_kg.embed")

SC_MODEL_KEY = "TaylorAI/bge-micro-v2"
MIN_SECTION_CHARS = 200
MAX_SECTIONS = 40


def release_memory() -> None:
    """Hand freed heap back to the OS (glibc keeps it otherwise, and the pod looks bloated)."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


def load_ajson(path: str) -> dict:
    """Smart Connections .ajson files are append-only `"key": value,` logs; last write wins."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read().strip().rstrip(",")
    try:
        return json.loads("{" + raw + "}")
    except json.JSONDecodeError:
        out = {}
        for line in raw.split("\n"):
            line = line.strip().rstrip(",")
            if not line:
                continue
            try:
                out.update(json.loads("{" + line + "}"))
            except json.JSONDecodeError:
                continue
        return out


@dataclass
class SCEntry:
    kind: str  # "smart_sources" | "smart_blocks"
    path: str
    label: str
    lines: tuple[int, int] | None
    imported: tuple[float, int] | None  # (mtime ms, size) of the plugin's last import
    vec: np.ndarray | None


def compact_ajson(data: dict) -> dict[str, SCEntry | None]:
    """Keep only what we use; the raw parsed JSON is several times larger than the vectors."""
    out: dict[str, SCEntry | None] = {}
    for key, val in data.items():
        if ":" not in key:
            continue
        if not val:
            out[key] = None
            continue
        kind, rest = key.split(":", 1)
        if kind not in ("smart_sources", "smart_blocks"):
            continue
        path = rest.split("#", 1)[0]
        imp = val.get("last_import") or {}
        imported = (imp.get("mtime") or 0, imp.get("size")) if imp else None
        vec = ((val.get("embeddings") or {}).get(SC_MODEL_KEY) or {}).get("vec")
        vec = np.asarray(vec, dtype=np.float32) if vec and len(vec) == 384 else None
        label = " > ".join(h for h in rest.split("#")[1:] if h and not h.startswith("{"))
        ln = val.get("lines")
        out[key] = SCEntry(kind, path, label, tuple(ln) if ln else None, imported, vec)
    return out


def crumbs(path: str) -> str:
    return path[:-3].replace("/", " > ")


@dataclass
class Row:
    path: str
    label: str  # "" for the whole note, else "Heading > Sub"
    lines: tuple[int, int] | None


class Encoder:
    def __init__(self, model_dir: str, threads: int = 2):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        # Variable batch shapes make the arena and memory patterns grow without bound.
        opts.enable_cpu_mem_arena = False
        opts.enable_mem_pattern = False
        self.session = ort.InferenceSession(os.path.join(model_dir, "onnx", "model.onnx"), opts,
                                            providers=["CPUExecutionProvider"])
        self.tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.tok.enable_truncation(512)
        self.tok.no_padding()
        self.lock = threading.Lock()

    # Attention memory grows with batch * seq^2; cap it at one full-length sequence.
    TOKEN_BUDGET = 512 * 512

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), 384), dtype=np.float32)
        # Keep only token ids; full Encoding objects (offsets, strings) are large.
        toks = []
        for k in range(0, len(texts), 256):
            toks.extend(e.ids for e in self.tok.encode_batch(texts[k:k + 256]))
        order = sorted(range(len(texts)), key=lambda i: len(toks[i]))
        s = 0
        while s < len(order):
            seq = len(toks[order[s]])
            e = s + 1
            while e < len(order):
                seq = max(seq, len(toks[order[e]]))
                if (e - s + 1) * seq * seq > self.TOKEN_BUDGET or e - s >= 64:
                    break
                e += 1
            idx = order[s:e]
            width = -(-max(len(toks[i]) for i in idx) // 64) * 64
            ids = np.zeros((len(idx), width), dtype=np.int64)
            mask = np.zeros((len(idx), width), dtype=np.int64)
            for r, i in enumerate(idx):
                n = len(toks[i])
                ids[r, :n] = toks[i]
                mask[r, :n] = 1
            with self.lock:
                hidden = self.session.run(None, {"input_ids": ids, "attention_mask": mask,
                                                 "token_type_ids": np.zeros_like(ids)})[0]
            v = (hidden * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
            out[idx] = v / np.linalg.norm(v, axis=1, keepdims=True)
            s = e
        return out


def note_chunks(n: Note) -> list[tuple[str, tuple[int, int] | None, str]]:
    """(label, line range, embed input) for a note, mirroring Smart Connections' input shape."""
    c = crumbs(n.path)
    chunks: list[tuple[str, tuple[int, int] | None, str]] = [("", None, f"{c}:\n{n.body}")]
    lines = n.body.split("\n")
    stack: list[tuple[int, str]] = []
    total = n.body_line + len(lines)
    for i, (lvl, text, line) in enumerate(n.headings):
        stack = [s for s in stack if s[0] < lvl] + [(lvl, text)]
        end = n.headings[i + 1][2] if i + 1 < len(n.headings) else total
        section = "\n".join(lines[line - n.body_line + 1:end - n.body_line]).strip()
        if len(section) < MIN_SECTION_CHARS:
            continue
        label = " > ".join(s[1] for s in stack)
        chunks.append((label, (line, end - 1), f"{c}: {label}:\n{section}"))
        if len(chunks) > MAX_SECTIONS:
            break
    return chunks


class VectorStore:
    def __init__(self, rows: list[Row], mat: np.ndarray, sources: dict[str, str]):
        self.rows, self.mat, self.sources = rows, mat, sources
        self.by_path: dict[str, list[int]] = {}
        for i, r in enumerate(rows):
            self.by_path.setdefault(r.path, []).append(i)

    def note_vector(self, path: str) -> np.ndarray | None:
        idx = self.by_path.get(path)
        if not idx:
            return None
        whole = [i for i in idx if not self.rows[i].label]
        v = self.mat[whole[0]] if whole else self.mat[idx].mean(0)
        return v / (np.linalg.norm(v) or 1)

    def search(self, qvec: np.ndarray, allowed: set[str] | None, limit: int):
        """Best-scoring row per note → [(path, score, row)]."""
        if not len(self.rows):
            return []
        scores = self.mat @ qvec
        best: dict[str, tuple[float, int]] = {}
        for i in np.argsort(-scores)[: max(limit * 40, 400)]:
            r = self.rows[i]
            if allowed is not None and r.path not in allowed:
                continue
            if r.path not in best:
                best[r.path] = (float(scores[i]), int(i))
                if len(best) >= limit:
                    break
        return [(p, s, self.rows[i]) for p, (s, i) in best.items()]


class Embeddings:
    def __init__(self, vault: str, model_dir: str, threads: int = 2, cache_dir: str | None = None):
        self.vault, self.model_dir, self.threads = vault, model_dir, threads
        self._encoder: Encoder | None = None
        self.sc_files: dict[str, tuple[float, dict[str, SCEntry | None]]] = {}
        self.own: dict[str, tuple[float, int, list[Row], np.ndarray]] = {}
        self.cache_path = os.path.join(cache_dir, "vectors.pkl") if cache_dir else None
        self._load_cache()
        self.store = VectorStore([], np.zeros((0, 384), np.float32), {})
        self.status = {"state": "starting"}

    def _load_cache(self) -> None:
        if not self.cache_path or not os.path.exists(self.cache_path):
            return
        try:
            with open(self.cache_path, "rb") as fh:
                data = pickle.load(fh)
            if data.get("model") == SC_MODEL_KEY:
                self.own = data["own"]
                log.info("loaded %d cached note embeddings", len(self.own))
        except Exception as e:  # a bad cache only costs a re-embed
            log.warning("ignoring vector cache: %s", e)

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        tmp = self.cache_path + ".tmp"
        try:
            with open(tmp, "wb") as fh:
                pickle.dump({"model": SC_MODEL_KEY, "own": self.own}, fh)
            os.replace(tmp, self.cache_path)
        except OSError as e:
            log.warning("cannot write vector cache: %s", e)

    @property
    def encoder(self) -> Encoder:
        if self._encoder is None:
            self._encoder = Encoder(self.model_dir, self.threads)
        return self._encoder

    def encode_query(self, text: str) -> np.ndarray:
        return self.encoder.encode([text])[0]

    def _sc_signature(self) -> tuple:
        files = glob.glob(os.path.join(self.vault, ".smart-env", "multi", "*.ajson"))
        sig = []
        for f in files:
            try:
                sig.append((f, os.stat(f).st_mtime))
            except OSError:
                pass
        return tuple(sorted(sig))

    def _sc_entries(self) -> dict[str, SCEntry | None]:
        files = glob.glob(os.path.join(self.vault, ".smart-env", "multi", "*.ajson"))
        seen = set()
        for f in files:
            seen.add(f)
            try:
                m = os.stat(f).st_mtime
            except OSError:
                continue
            if f not in self.sc_files or self.sc_files[f][0] != m:
                try:
                    self.sc_files[f] = (m, compact_ajson(load_ajson(f)))
                except OSError as e:
                    log.warning("ajson %s: %s", f, e)
        for f in set(self.sc_files) - seen:
            del self.sc_files[f]
        merged: dict[str, SCEntry | None] = {}
        for _, data in self.sc_files.values():
            merged.update(data)
        return merged

    def build(self, graph: Graph, embed_missing: bool = True) -> None:
        sig = (graph.generation, self._sc_signature(), embed_missing)
        if sig == getattr(self, "_last_sig", None):
            return
        t0 = time.time()
        sc = self._sc_entries()
        per_note: dict[str, list[tuple[Row, np.ndarray]]] = {}
        fresh: set[str] = set()
        for e in sc.values():
            if e is None:
                continue
            note = graph.notes.get(e.path)
            if note is None:
                continue
            if e.kind == "smart_sources" and e.imported:
                mtime_ms, size = e.imported
                if size == note.size and abs(mtime_ms - note.mtime * 1000) < 2000:
                    fresh.add(e.path)
            if e.vec is None:
                continue
            row = Row(e.path, "" if e.kind == "smart_sources" else e.label, e.lines)
            per_note.setdefault(e.path, []).append((row, e.vec))

        rows: list[Row] = []
        vecs: list[np.ndarray] = []
        sources: dict[str, str] = {}
        missing: list[Note] = []
        for path, note in graph.notes.items():
            if path in fresh and per_note.get(path):
                for row, vec in per_note[path]:
                    rows.append(row)
                    vecs.append(vec)
                sources[path] = "smart-connections"
                continue
            own = self.own.get(path)
            if own and own[0] == note.mtime and own[1] == note.size:
                rows.extend(own[2])
                vecs.extend(own[3])
                sources[path] = "local"
                continue
            missing.append(note)

        if embed_missing and missing:
            self.status = {"state": "embedding", "pending_notes": len(missing)}
            log.info("embedding %d notes not covered by fresh Smart Connections vectors", len(missing))
            grouped: dict[str, tuple[list[Row], list[np.ndarray]]] = {}
            for k in range(0, len(missing), 100):
                chunks = [(n, label, ln, text) for n in missing[k:k + 100]
                          for label, ln, text in note_chunks(n)]
                mat = self.encoder.encode([c[3] for c in chunks])
                for (n, label, ln, _), v in zip(chunks, mat):
                    g = grouped.setdefault(n.path, ([], []))
                    g[0].append(Row(n.path, label, ln))
                    g[1].append(v)
                self.status = {"state": "embedding", "pending_notes": max(0, len(missing) - k - 100)}
                release_memory()
            for n in missing:
                r, v = grouped.get(n.path, ([], []))
                self.own[n.path] = (n.mtime, n.size, r, np.array(v, dtype=np.float32).reshape(-1, 384))
                rows.extend(r)
                vecs.extend(v)
                sources[n.path] = "local"
        stale = set(self.own) - set(graph.notes)
        for p in stale:
            del self.own[p]
        if (embed_missing and missing) or stale:
            self._save_cache()

        mat = np.vstack(vecs).astype(np.float32) if vecs else np.zeros((0, 384), np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        mat = mat / np.where(norms == 0, 1, norms)
        self.store = VectorStore(rows, mat, sources)
        self._last_sig = sig
        release_memory()
        counts: dict[str, int] = {}
        for s in sources.values():
            counts[s] = counts.get(s, 0) + 1
        self.status = {"state": "ready", "vectors": len(rows), "notes_by_source": counts,
                       "notes_without_vectors": len(graph.notes) - len(sources),
                       "built_seconds": round(time.time() - t0, 1)}
        log.info("vectors ready: %s", self.status)
