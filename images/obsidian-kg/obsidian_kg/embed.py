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
        self.session = ort.InferenceSession(os.path.join(model_dir, "onnx", "model.onnx"), opts,
                                            providers=["CPUExecutionProvider"])
        self.tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.tok.enable_truncation(512)
        self.tok.enable_padding()
        self.lock = threading.Lock()

    def encode(self, texts: list[str], batch: int = 16) -> np.ndarray:
        out = np.zeros((len(texts), 384), dtype=np.float32)
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        for s in range(0, len(order), batch):
            idx = order[s:s + batch]
            enc = self.tok.encode_batch([texts[i] for i in idx])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            with self.lock:
                hidden = self.session.run(None, {"input_ids": ids, "attention_mask": mask,
                                                 "token_type_ids": np.zeros_like(ids)})[0]
            v = (hidden * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
            out[idx] = v / np.linalg.norm(v, axis=1, keepdims=True)
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
        self.sc_files: dict[str, tuple[float, dict]] = {}
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

    def _sc_entries(self) -> dict[str, dict]:
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
                    self.sc_files[f] = (m, load_ajson(f))
                except OSError as e:
                    log.warning("ajson %s: %s", f, e)
        for f in set(self.sc_files) - seen:
            del self.sc_files[f]
        merged: dict[str, dict] = {}
        for _, data in self.sc_files.values():
            merged.update(data)
        return merged

    def build(self, graph: Graph, embed_missing: bool = True) -> None:
        sig = (graph.generation, self._sc_signature(), embed_missing)
        if sig == getattr(self, "_last_sig", None):
            return
        t0 = time.time()
        sc = self._sc_entries()
        per_note: dict[str, list[tuple[Row, list[float]]]] = {}
        fresh: set[str] = set()
        for key, val in sc.items():
            if not val or ":" not in key:
                continue
            kind, rest = key.split(":", 1)
            path = rest.split("#", 1)[0]
            note = graph.notes.get(path)
            if note is None:
                continue
            if kind == "smart_sources":
                imp = val.get("last_import") or {}
                if imp.get("size") == note.size and abs((imp.get("mtime") or 0) - note.mtime * 1000) < 2000:
                    fresh.add(path)
            vec = ((val.get("embeddings") or {}).get(SC_MODEL_KEY) or {}).get("vec")
            if not vec or len(vec) != 384:
                continue
            if kind == "smart_sources":
                row = Row(path, "", None)
            else:
                label = " > ".join(h for h in rest.split("#")[1:] if h and not h.startswith("{"))
                ln = val.get("lines")
                row = Row(path, label, tuple(ln) if ln else None)
            per_note.setdefault(path, []).append((row, vec))

        rows: list[Row] = []
        vecs: list[np.ndarray] = []
        sources: dict[str, str] = {}
        missing: list[Note] = []
        for path, note in graph.notes.items():
            if path in fresh and per_note.get(path):
                for row, vec in per_note[path]:
                    rows.append(row)
                    vecs.append(np.asarray(vec, dtype=np.float32))
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
            chunks = [(n, label, ln, text) for n in missing for label, ln, text in note_chunks(n)]
            mat = self.encoder.encode([c[3] for c in chunks])
            grouped: dict[str, tuple[list[Row], list[np.ndarray]]] = {}
            for (n, label, ln, _), v in zip(chunks, mat):
                g = grouped.setdefault(n.path, ([], []))
                g[0].append(Row(n.path, label, ln))
                g[1].append(v)
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
        counts: dict[str, int] = {}
        for s in sources.values():
            counts[s] = counts.get(s, 0) + 1
        self.status = {"state": "ready", "vectors": len(rows), "notes_by_source": counts,
                       "notes_without_vectors": len(graph.notes) - len(sources),
                       "built_seconds": round(time.time() - t0, 1)}
        log.info("vectors ready: %s", self.status)
