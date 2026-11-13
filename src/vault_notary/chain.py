"""NEAR registry access.

* Reading (verify, history) uses plain JSON-RPC: no keys, no SDK, anyone can do it.
* Writing (publish) signs a function call with near-kit-py.

Testnet only: anything that is not a ``.testnet`` account is refused, so no
real money can be spent by accident.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone

import httpx

DEFAULT_RPC = "https://test.rpc.fastnear.com"


def _testnet_only(account_id: str) -> str:
    if not account_id.endswith(".testnet"):
        raise RuntimeError(f"{account_id!r} is not a testnet account; this tool is testnet-only")
    return account_id


def contract_id() -> str:
    cid = os.environ.get("NOTARY_CONTRACT")
    if not cid:
        raise RuntimeError("NOTARY_CONTRACT is not set (see .env.example)")
    return _testnet_only(cid)


def rpc_url() -> str:
    return os.environ.get("NEAR_RPC_URL", DEFAULT_RPC)


def view(method: str, args: dict, contract: str | None = None):
    payload = {
        "jsonrpc": "2.0", "id": "vault-notary", "method": "query",
        "params": {
            "request_type": "call_function", "finality": "final",
            "account_id": contract or contract_id(), "method_name": method,
            "args_base64": base64.b64encode(json.dumps(args).encode()).decode(),
        },
    }
    r = httpx.post(rpc_url(), json=payload, timeout=30)
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise RuntimeError(f"RPC error: {body['error']}")
    return json.loads(bytes(body["result"]["result"]) or b"null")


def get_note(note_id: str) -> dict | None:
    return view("get_note", {"note_id": note_id})


def ns_to_iso(ns: str | int) -> str:
    return datetime.fromtimestamp(int(ns) / 1e9, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class NearRegistry:
    """Writes to the registry as NEAR_ACCOUNT_ID, signed with NEAR_PRIVATE_KEY."""

    def __init__(self):
        from near import Near  # imported lazily: read-only commands don't need it

        self.account_id = _testnet_only(os.environ.get("NEAR_ACCOUNT_ID", ""))
        key = os.environ.get("NEAR_PRIVATE_KEY")
        if not key:
            raise RuntimeError("NEAR_PRIVATE_KEY is not set (see .env.example)")
        self.contract = contract_id()
        self.client = Near(network="testnet", rpc_url=rpc_url(), account_id=self.account_id, private_key=key)

    def publish(self, note_id: str, cid: str, prev_cid: str | None) -> str:
        res = self.client.call(self.contract, "publish",
                               {"note_id": note_id, "cid": cid, "prev_cid": prev_cid},
                               gas="30 Tgas", wait_until="FINAL")
        if isinstance(res.status, dict) and "Failure" in res.status:
            raise RuntimeError(f"registry rejected the publish: {res.status['Failure']}")
        return res.transaction_hash or "?"
