"""Plan and execute a publish run.

Two phases so the CLI can show a preview before anything leaves the device:

1. ``plan``    - pure, local: filter publishable notes, assign ids, render, hash.
2. ``execute`` - upload changed notes, record them in the registry, write status.

Only ``PlannedNote.content`` is ever handed to the uploader, and plans are only
ever built from notes that passed the publish filter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

from .cid import cid_v1_raw
from .links import LinkIndex, render_document
from .vault import Note, write_status


class Uploader(Protocol):
    def upload(self, content: bytes, name: str) -> str: ...


class Registry(Protocol):
    def publish(self, note_id: str, cid: str, prev_cid: str | None) -> str: ...


@dataclass
class PlannedNote:
    note: Note
    note_id: str
    content: bytes
    cid: str
    prev_cid: str | None
    version: int
    delinked: list[str] = field(default_factory=list)

    @property
    def is_new(self) -> bool:
        return self.prev_cid is None

    @property
    def changed(self) -> bool:
        return self.cid != self.prev_cid


def plan(notes: list[Note], new_id: Callable[[], str] = lambda: str(uuid.uuid4())) -> list[PlannedNote]:
    public = [n for n in notes if n.publish]
    ids = {n.rel: (n.note_id or new_id()) for n in public}
    index = LinkIndex(notes)
    plans = []
    for n in public:
        content, r = render_document(n, index, ids)
        status = n.status or {}
        cid = cid_v1_raw(content)
        plans.append(PlannedNote(
            note=n,
            note_id=ids[n.rel],
            content=content,
            cid=cid,
            prev_cid=status.get("cid"),
            version=int(status.get("version", 0)) + (cid != status.get("cid")),
            delinked=r.delinked,
        ))
    return plans


def execute(plans: list[PlannedNote], uploader: Uploader, registry: Registry,
            on_done: Callable[[PlannedNote, str], None] | None = None) -> None:
    for p in plans:
        if not p.note.publish:  # defence in depth; plan() never produces these
            raise RuntimeError(f"refusing to upload non-public note {p.note.path}")
        if not p.changed:
            continue
        remote_cid = uploader.upload(p.content, f"{p.note_id}.md")
        if remote_cid != p.cid:
            raise RuntimeError(f"storage returned CID {remote_cid}, expected {p.cid}")
        tx = registry.publish(p.note_id, p.cid, p.prev_cid)
        write_status(p.note, {
            "id": p.note_id,
            "cid": p.cid,
            "version": p.version,
            "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        if on_done:
            on_done(p, tx)
