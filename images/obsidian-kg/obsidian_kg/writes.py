"""Guarded write operations on the vault.

Every change is atomic (temp file + rename), refuses paths outside the vault, in
dot-folders or in excluded folders, keeps the previous content under
`<data>/history/`, and is recorded in `<data>/audit.jsonl`.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading

import yaml

from .vault import WIKILINK_RE, split_frontmatter, strip_code

log = logging.getLogger("obsidian_kg.writes")

BAD_NAME = re.compile(r'[\\:*?"<>|#^\[\]]')


class WriteError(ValueError):
    pass


def version_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def render_frontmatter(fm: dict) -> str:
    if not fm:
        return ""
    body = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{body}---\n"


class Writer:
    def __init__(self, vault: str, exclude: list[str], data_dir: str):
        self.vault = os.path.realpath(vault)
        self.exclude = [e.strip("/").lower() for e in exclude if e.strip("/")]
        self.data_dir = data_dir
        self.lock = threading.Lock()
        os.makedirs(os.path.join(data_dir, "history"), exist_ok=True)

    # ---- paths --------------------------------------------------------------
    def check_path(self, rel: str) -> str:
        """Validate a vault-relative note path; return the normalized relative path."""
        rel = rel.strip().replace("\\", "/").lstrip("/")
        if not rel.lower().endswith(".md"):
            rel += ".md"
        norm = os.path.normpath(rel)
        if norm.startswith("..") or os.path.isabs(norm):
            raise WriteError(f"Path escapes the vault: {rel}")
        parts = norm.split("/")
        if any(p.startswith(".") for p in parts):
            raise WriteError("Dot-folders and hidden files are not writable.")
        low = norm.lower()
        for e in self.exclude:
            if low == e or low.startswith(e + "/"):
                raise WriteError(f"'{e}' is excluded and not writable.")
        name = parts[-1][:-3]
        if not name.strip() or BAD_NAME.search(name):
            raise WriteError("Note names can't be empty or contain \\ : * ? \" < > | # ^ [ ]")
        full = os.path.realpath(os.path.join(self.vault, norm))
        if not full.startswith(self.vault + os.sep):
            raise WriteError(f"Path escapes the vault: {rel}")
        return norm

    def full(self, rel: str) -> str:
        return os.path.join(self.vault, rel)

    # ---- primitives ---------------------------------------------------------
    def read(self, rel: str) -> str:
        with open(self.full(rel), encoding="utf-8") as fh:
            return fh.read()

    def _snapshot(self, rel: str, text: str, stamp: str) -> str:
        dest = os.path.join(self.data_dir, "history", stamp, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(text)
        return os.path.relpath(dest, self.data_dir)

    def _atomic_write(self, rel: str, text: str) -> None:
        full = self.full(rel)
        d = os.path.dirname(full)
        mode = os.stat(full).st_mode & 0o777 if os.path.exists(full) else 0o644
        fd, tmp = tempfile.mkstemp(prefix=".kg-", suffix=".tmp", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.chmod(tmp, mode)
            os.replace(tmp, full)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _audit(self, entry: dict) -> None:
        entry = {"at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), **entry}
        with open(os.path.join(self.data_dir, "audit.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _stamp(self) -> str:
        return dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")

    # ---- operations ---------------------------------------------------------
    def create(self, rel: str, content: str, frontmatter: dict | None, actor: str | None) -> dict:
        rel = self.check_path(rel)
        with self.lock:
            full = self.full(rel)
            if os.path.exists(full):
                raise WriteError(f"{rel} already exists; use kg_append or kg_edit.")
            # Obsidian resolves links by basename, so a duplicate name makes links ambiguous.
            text = render_frontmatter(frontmatter or {}) + content.lstrip("\n")
            if not text.endswith("\n"):
                text += "\n"
            os.makedirs(os.path.dirname(full) or self.vault, exist_ok=True)
            self._atomic_write(rel, text)
            v = version_of(text)
            self._audit({"op": "create", "path": rel, "after": v, "actor": actor})
        return {"path": rel, "version": v}

    def modify(self, rel: str, fn, op: str, expected_version: str | None, actor: str | None,
               detail: dict | None = None) -> dict:
        """Apply fn(old_text) -> new_text under the lock, with version check and history."""
        rel = self.check_path(rel)
        with self.lock:
            if not os.path.exists(self.full(rel)):
                raise WriteError(f"{rel} does not exist.")
            old = self.read(rel)
            before = version_of(old)
            if expected_version and expected_version != before:
                raise WriteError(f"{rel} changed since you read it (version {before}, you had "
                                 f"{expected_version}). Re-read it and retry.")
            new = fn(old)
            if new == old:
                return {"path": rel, "version": before, "changed": False}
            stamp = self._stamp()
            snap = self._snapshot(rel, old, stamp)
            self._atomic_write(rel, new)
            after = version_of(new)
            self._audit({"op": op, "path": rel, "before": before, "after": after,
                         "history": snap, "actor": actor, **(detail or {})})
        return {"path": rel, "version": after, "changed": True, "previous": snap}

    def trash(self, rel: str, expected_version: str | None, actor: str | None) -> dict:
        rel = self.check_path(rel)
        with self.lock:
            full = self.full(rel)
            if not os.path.exists(full):
                raise WriteError(f"{rel} does not exist.")
            old = self.read(rel)
            before = version_of(old)
            if expected_version and expected_version != before:
                raise WriteError(f"{rel} changed since you read it; re-read it and retry.")
            snap = self._snapshot(rel, old, self._stamp())
            # Obsidian's own "move to .trash" layout: same relative path under .trash/.
            dest = os.path.join(self.vault, ".trash", rel)
            if os.path.exists(dest):
                base, ext = os.path.splitext(dest)
                dest = f"{base} {self._stamp()}{ext}"
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(full, dest)
            trash_rel = os.path.relpath(dest, self.vault)
            self._audit({"op": "trash", "path": rel, "before": before, "trash": trash_rel,
                         "history": snap, "actor": actor})
        return {"path": rel, "trashed_to": trash_rel, "previous": snap}


# ---- pure text transforms ---------------------------------------------------
def append_text(old: str, content: str, section: str | None) -> str:
    block = content.strip("\n") + "\n"
    if not section:
        return old.rstrip("\n") + "\n\n" + block
    fm, raw, body, body_line = split_frontmatter(old)
    head_len = len(old) - len(body)
    lines = body.split("\n")
    want = section.strip().lstrip("#").strip().lower()
    start = lvl = None
    in_fence = False
    for i, ln in enumerate(lines):
        if ln.startswith(("```", "~~~")):
            in_fence = not in_fence
        m = None if in_fence else re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", ln)
        if m and start is None and m.group(2).strip().lower() == want:
            start, lvl = i, len(m.group(1))
        elif m and start is not None and len(m.group(1)) <= lvl:
            end = i
            break
    else:
        end = len(lines)
    if start is None:
        raise WriteError(f"No heading '{section}'.")
    # Insert after the section's last non-blank line, keeping one blank line before the next heading.
    j = end
    while j > start + 1 and not lines[j - 1].strip():
        j -= 1
    new_lines = lines[:j] + block.rstrip("\n").split("\n") + ([""] if end < len(lines) else []) + lines[end:]
    return old[:head_len] + "\n".join(new_lines)


def replace_text(old: str, find: str, replace: str, count: int) -> str:
    n = old.count(find)
    if n == 0:
        raise WriteError("old_text not found (it must match exactly, including whitespace).")
    if count == 1 and n > 1:
        raise WriteError(f"old_text occurs {n} times; include more context or set replace_all.")
    return old.replace(find, replace) if count != 1 else old.replace(find, replace, 1)


def update_frontmatter(old: str, set_: dict | None, remove: list[str] | None) -> str:
    fm, raw, body, _ = split_frontmatter(old)
    if raw and not fm and raw.strip():
        raise WriteError("Existing frontmatter isn't valid YAML; fix it with kg_edit.")
    fm = dict(fm)
    for k, v in (set_ or {}).items():
        fm[k] = v
    for k in remove or []:
        fm.pop(k, None)
    return render_frontmatter(fm) + body.lstrip("\n") if fm else body.lstrip("\n")


def links_in(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(2).strip() for m in WIKILINK_RE.finditer(strip_code(text))
                              if m.group(2).strip()))
