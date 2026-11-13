"""Compute an IPFS CID locally, so nobody has to trust the storage provider.

Notes are small, so each one fits in a single IPFS block. For a single-block
file IPFS (CIDv1, raw leaves) uses the "raw" codec: the CID is just
version 1 + codec 0x55 + sha2-256 multihash of the bytes, base32-encoded.
"""

from __future__ import annotations

import base64
import hashlib

MAX_SINGLE_BLOCK = 256 * 1024  # default IPFS chunk size


def encode_raw_cid(sha256_digest: bytes) -> str:
    """CIDv1 (0x01) + raw codec (0x55) + multihash sha2-256 (0x12, 32 bytes), base32."""
    cid = bytes([0x01, 0x55, 0x12, 0x20]) + sha256_digest
    return "b" + base64.b32encode(cid).decode().lower().rstrip("=")


def cid_v1_raw(data: bytes) -> str:
    """CID of a note as IPFS computes it; only valid for single-block content."""
    if len(data) > MAX_SINGLE_BLOCK:
        raise ValueError(f"note is {len(data)} bytes; prototype supports up to {MAX_SINGLE_BLOCK}")
    return encode_raw_cid(hashlib.sha256(data).digest())
