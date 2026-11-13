"""IPFS storage: upload via Pinata, download via any IPFS gateway.

Downloads are trust-free: the caller recomputes the CID from the bytes, so a
lying gateway is detected, not believed.
"""

from __future__ import annotations

import os

import httpx

PINATA_UPLOAD_URL = "https://uploads.pinata.cloud/v3/files"
DEFAULT_GATEWAYS = ["https://gateway.pinata.cloud", "https://ipfs.io", "https://dweb.link"]


class PinataUploader:
    def __init__(self, jwt: str | None = None):
        self.jwt = jwt or os.environ.get("PINATA_JWT")
        if not self.jwt:
            raise RuntimeError("PINATA_JWT is not set (see .env.example)")

    def upload(self, content: bytes, name: str) -> str:
        r = httpx.post(
            PINATA_UPLOAD_URL,
            headers={"Authorization": f"Bearer {self.jwt}"},
            files={"file": (name, content, "text/markdown")},
            data={"network": "public", "name": name, "cid_version": "v1"},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["data"]["cid"]


def gateways() -> list[str]:
    custom = os.environ.get("IPFS_GATEWAY")
    return ([custom.rstrip("/")] if custom else []) + DEFAULT_GATEWAYS


def fetch(cid: str) -> tuple[bytes, str]:
    """Return (content, gateway_used). Tries gateways in order."""
    errors = []
    for gw in gateways():
        url = f"{gw}/ipfs/{cid}"
        try:
            r = httpx.get(url, timeout=30, follow_redirects=True)
            r.raise_for_status()
            return r.content, gw
        except httpx.HTTPError as e:
            errors.append(f"{gw}: {e}")
    raise RuntimeError("could not fetch from any gateway:\n  " + "\n  ".join(errors))
