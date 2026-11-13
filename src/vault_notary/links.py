"""Wikilink resolution for published notes.

``[[Target]]``, ``[[Target|Alias]]``, ``[[Target#Heading]]``, ``![[Embed]]``:

* target is published -> ``[Visible](note:<note-id>)``
* anything else       -> plain text: the alias if the author wrote one,
  otherwise the neutral placeholder "(private note)". The target's title,
  folder path and heading never leave the device.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .vault import Note

WIKILINK_RE = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
COMMENT_RE = re.compile(r"%%.*?%%", re.S)  # Obsidian comments are never published
PRIVATE_PLACEHOLDER = "(private note)"


@dataclass
class RenderResult:
    text: str
    linked: list[str] = field(default_factory=list)    # note-ids linked to
    delinked: list[tuple[str, str]] = field(default_factory=list)  # (original target, replacement); local only


class LinkIndex:
    def __init__(self, notes: list[Note]):
        self.by_rel: dict[str, Note] = {}
        self.by_name: dict[str, list[Note]] = {}
        for n in notes:
            self.by_rel[n.rel.lower()] = n
            self.by_name.setdefault(n.title.lower(), []).append(n)

    def resolve(self, target: str) -> Note | None:
        t = target.strip().removesuffix(".md").lstrip("/").lower()
        if not t:
            return None
        if "/" in t:
            if t in self.by_rel:
                return self.by_rel[t]
            hits = [n for r, n in self.by_rel.items() if r.endswith("/" + t)]
        else:
            hits = self.by_name.get(t, [])
        # Obsidian prefers the shortest path when names collide.
        return min(hits, key=lambda n: (n.rel.count("/"), n.rel)) if hits else None


def split_link(inner: str) -> tuple[str, str | None]:
    inner = inner.replace("\\|", "|")  # escaped pipe inside tables
    target, _, alias = inner.partition("|")
    target = target.split("#", 1)[0]
    return target.strip(), (alias.strip() or None)


def render_body(body: str, index: LinkIndex, ids: dict[str, str]) -> RenderResult:
    """``ids`` maps note.rel -> note-id for every note published in this run or before."""
    result = RenderResult(text="")

    def repl(m: re.Match) -> str:
        target, alias = split_link(m.group(2))
        note = index.resolve(target) if target else None
        if note is not None and note.publish and note.rel in ids:
            visible = alias or note.title
            result.linked.append(ids[note.rel])
            return f"[{visible}](note:{ids[note.rel]})"
        replacement = alias or PRIVATE_PLACEHOLDER
        result.delinked.append((target, replacement))
        return replacement

    result.text = WIKILINK_RE.sub(repl, COMMENT_RE.sub("", body))
    return result


def render_document(note: Note, index: LinkIndex, ids: dict[str, str]) -> tuple[bytes, RenderResult]:
    """The exact bytes that get uploaded: title + resolved body, no frontmatter."""
    r = render_body(note.body, index, ids)
    doc = f"# {note.title}\n\n{r.text.strip()}\n"
    return doc.encode("utf-8"), r
