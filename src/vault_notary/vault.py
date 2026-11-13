"""Reading an Obsidian vault and deciding which notes may be published.

Safety rule: a note is publishable only if its YAML frontmatter has a
top-level line that is literally ``publish: true``. Anything else (missing,
false, quoted "true", ``yes``, nested keys, broken YAML) means: private.
We fail closed.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n?---[ \t]*(?:\r?\n|\Z)", re.S)
# Column-0 key, lowercase, value exactly the YAML boolean true (any case), optional comment.
PUBLISH_LINE_RE = re.compile(r"^publish:[ \t]*(?i:true)[ \t]*(?:#.*)?$", re.M)
STATUS_KEY = "publish_status"
STATUS_LINE_RE = re.compile(rf"^{STATUS_KEY}:.*(?:\r?\n[ \t]+.*)*", re.M)
SKIP_DIRS = {".obsidian", ".trash", ".git"}


@dataclass
class Note:
    path: Path          # absolute file path
    rel: str            # vault-relative posix path without ".md", e.g. "Projects/Idea"
    title: str          # file name without ".md"
    frontmatter: dict
    body: str
    raw: str
    publish: bool

    @property
    def status(self) -> dict | None:
        s = self.frontmatter.get(STATUS_KEY)
        return s if isinstance(s, dict) else None

    @property
    def note_id(self) -> str | None:
        s = self.status
        return str(s["id"]) if s and s.get("id") else None


def is_publishable(fm_text: str | None, fm: object) -> bool:
    if fm_text is None or not isinstance(fm, dict):
        return False
    return fm.get("publish") is True and PUBLISH_LINE_RE.search(fm_text) is not None


def parse_note(path: Path, vault_root: Path) -> Note:
    raw = path.read_text(encoding="utf-8")
    rel = path.relative_to(vault_root).with_suffix("").as_posix()
    m = FRONTMATTER_RE.match(raw)
    fm: object = {}
    fm_text = None
    body = raw
    if m:
        fm_text = m.group(1)
        body = raw[m.end():]
        try:
            fm = yaml.safe_load(fm_text) or {}
        except yaml.YAMLError:
            fm, fm_text = {}, None  # broken frontmatter -> private
    return Note(
        path=path,
        rel=rel,
        title=path.stem,
        frontmatter=fm if isinstance(fm, dict) else {},
        body=body,
        raw=raw,
        publish=is_publishable(fm_text, fm),
    )


def scan_vault(root: Path | str) -> list[Note]:
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Vault not found: {root}")
    notes = []
    for p in sorted(root.rglob("*.md")):
        parts = p.relative_to(root).parts
        if any(part in SKIP_DIRS or part.startswith(".") for part in parts[:-1]):
            continue
        notes.append(parse_note(p, root))
    return notes


def write_status(note: Note, status: dict) -> None:
    """Replace only the ``publish_status`` line in the note's frontmatter.

    Every other byte of the file stays as it was. Aborts if the file changed
    on disk since it was read.
    """
    current = note.path.read_text(encoding="utf-8")
    if current != note.raw:
        raise RuntimeError(f"{note.path} changed since it was read; not touching it")
    m = FRONTMATTER_RE.match(current)
    if not m:
        raise RuntimeError(f"{note.path} has no frontmatter")
    fm_text = m.group(1)
    newline = "\r\n" if "\r\n" in fm_text else "\n"
    line = f"{STATUS_KEY}: {json.dumps(status, ensure_ascii=False)}"
    if STATUS_LINE_RE.search(fm_text):
        new_fm = STATUS_LINE_RE.sub(lambda _: line, fm_text, count=1)
    else:
        new_fm = fm_text.rstrip("\r\n") + newline + line
    updated = current[: m.start(1)] + new_fm + current[m.end(1):]
    fd, tmp = tempfile.mkstemp(dir=note.path.parent, prefix=".vn-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(updated)
    os.replace(tmp, note.path)
    note.raw = updated
    note.frontmatter[STATUS_KEY] = status
