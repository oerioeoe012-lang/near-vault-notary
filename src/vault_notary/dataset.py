"""Data provenance: register a fingerprint of a dataset/schema file, never its content.

The fingerprint uses the same CID format as notes (CIDv1, raw codec,
sha2-256), computed by streaming the file, so any size works. For files above
one IPFS block it is a content identifier only, not something to fetch from
IPFS, which is intended: company data stays where it is.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .cid import encode_raw_cid

MAX_ID_LEN = 64


def file_fingerprint(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return encode_raw_cid(h.digest())


@dataclass
class NotarizePlan:
    record_id: str
    path: Path
    size: int
    cid: str
    prev_cid: str | None
    version: int
    owner: str | None  # current author on chain, None if new

    @property
    def changed(self) -> bool:
        return self.cid != self.prev_cid


def plan_notarize(path: Path | str, record_id: str, record: dict | None) -> NotarizePlan:
    """``record`` is the registry's get_note() result for ``record_id`` (or None)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if not record_id or len(record_id) > MAX_ID_LEN:
        raise ValueError(f"id must be 1-{MAX_ID_LEN} characters")
    versions = (record or {}).get("versions", [])
    prev = versions[-1]["cid"] if versions else None
    cid = file_fingerprint(path)
    return NotarizePlan(
        record_id=record_id, path=path, size=path.stat().st_size, cid=cid, prev_cid=prev,
        version=len(versions) + (cid != prev), owner=(record or {}).get("author"),
    )


def match_version(cid: str, record: dict) -> int | None:
    """1-based number of the version whose CID equals ``cid``, else None."""
    for i, v in enumerate(record.get("versions", []), start=1):
        if v["cid"] == cid:
            return i
    return None
