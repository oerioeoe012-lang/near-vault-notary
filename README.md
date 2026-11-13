# vault-notary

[![CI](https://github.com/oerioeoe012-lang/near-vault-notary/actions/workflows/ci.yml/badge.svg)](https://github.com/oerioeoe012-lang/near-vault-notary/actions/workflows/ci.yml)

**Verifiable provenance for knowledge and data, on NEAR.**
Publish selected notes from an Obsidian vault to IPFS, or notarize dataset and
schema files without uploading them, and let anyone check *which account
published which version when*, without trusting a central server.

Submission for the NEAR Hackathon (November 2026).

## Problem

When you publish notes, research or data definitions, readers have to trust
whoever hosts them: the server can change text silently, backdate it, or
attribute it to someone else. Inside companies the same problem shows up as
"which version of this schema / data contract was actually approved, by whom,
and when?". Audit trails usually live in a database the auditee controls.

## Solution

`vault-notary` separates **content** from **proof**:

* **Content** is addressed by its hash (an IPFS CID). Notes are stored on
  IPFS; private datasets stay on the owner's machine.
* **Proof** lives in a tiny NEAR smart contract: for every record it stores the
  current CID, the previous CID, the block timestamp and the author account.
  No text ever goes on chain.
* **Verification** needs no keys and no trust: fetch the bytes from *any*
  gateway (or use your local copy), recompute the CID locally, compare with
  the registry.

Two use cases, one registry:

| | Notes (`publish`) | Data provenance (`notarize`) |
|---|---|---|
| Input | Obsidian notes with `publish: true` | any file: CSV, Parquet, JSON schema, data contract |
| Content goes to | public IPFS (Pinata) | **nowhere**, only the hash is registered |
| Verify with | `verify <id>` (downloads from IPFS) | `verify <id> --file <copy>` (tells you *which* version the copy is) |

## Privacy rules (enforced and tested)

* Only notes whose frontmatter contains the literal top-level line
  `publish: true` are published. `"true"`, `yes`, nested keys, broken YAML:
  all private (fail closed). Data on IPFS cannot be deleted, so this is the
  most important rule. See `tests/test_publish_filter.py::test_private_note_is_never_uploaded`.
* Frontmatter and Obsidian `%%comments%%` are never uploaded.
* `[[Wikilinks]]` to published notes become `[Title](note:<note-id>)`. Links to
  private or missing notes become plain text: the alias if you wrote one,
  otherwise `(private note)`, so private titles never leak.
* `publish` always shows a preview (including every link that gets
  neutralised) and asks for confirmation.
* The only change made to your vault is one `publish_status:` line in the
  frontmatter of published notes (id, cid, version, timestamp).
* `notarize` never uploads the file. Only its hash and the id go on chain.

## Architecture

```
 Obsidian vault ──▶ parser + publish filter ──▶ renderer (resolve wikilinks)
                                                   │ bytes
                           local CID (sha2-256) ◀──┤
                                                   ▼
                                   Pinata ─▶ IPFS (content, public)
                                                   │ CID must match local CID
                                                   ▼
            NEAR testnet: registry.jan-solver.testnet
            publish(note_id, cid, prev_cid)   signed by author account
            get_note(note_id) / get_latest(note_id)   free view calls

 verify:  registry CID ──▶ fetch bytes from any gateway ──▶ recompute CID ──▶ MATCH?
 history: registry version chain, each prev_cid checked
```

**Contract rules** (`contract/src/lib.rs`):

* The first account to register an id becomes its author (`predecessor_account_id`).
* Only the author can append versions; others are rejected on chain.
* A new version must name the current CID as `prev_cid`, so the chain can't
  fork or skip versions. Re-publishing unchanged content is rejected.
* Each version stores `cid`, `prev_cid`, `timestamp_ns`, `block_height`, `author`.
* Each publish emits a NEP-297 style `EVENT_JSON` log for indexers.

**CIDs.** Notes are small (≤ 256 KiB = one IPFS block), so their CID is
CIDv1 / raw codec / sha2-256 of the exact bytes, which is what Pinata
(`cid_version=v1`, raw leaves) returns. The tool aborts if Pinata's CID differs
from the locally computed one. Dataset fingerprints use the same format,
computed by streaming, so files of any size work.

## Deployed contract

| | |
|---|---|
| Network | NEAR **testnet** |
| Registry contract | [`registry.jan-solver.testnet`](https://testnet.nearblocks.io/address/registry.jan-solver.testnet) |
| Author account (demo) | `jan-solver.testnet` |

Example transactions from the demo run:
[note v1](https://testnet.nearblocks.io/txns/7cj56xoTAfdPb9bE2L6oVNUp5B5cxRwRRoVxbKumfxKv),
[note v2](https://testnet.nearblocks.io/txns/HfSQZR92tQVYgRx8qqXLYyP5PNH2366Rg4agxaLE2d85),
[schema v1](https://testnet.nearblocks.io/txns/ABba3j5rinCjbwX3WJzc8JBLyqnkXYDMTxkk4FoHN5wv),
[schema v2](https://testnet.nearblocks.io/txns/AK8DCPWrCgco9xsvPC1iPpbFEad3k4LRYBjEvk4vkdPL),
[rejected write by a foreign account](https://testnet.nearblocks.io/txns/6zXKiX4upwBro4Qguu3CYbkxcXstccckKFmFxir7ne9C).

Try it without any account or key:

```bash
NOTARY_CONTRACT=registry.jan-solver.testnet vault-notary history b83d141e-f9ba-4a75-a02e-4d5f141c5ac6
NOTARY_CONTRACT=registry.jan-solver.testnet vault-notary verify  b83d141e-f9ba-4a75-a02e-4d5f141c5ac6 --all --show
NOTARY_CONTRACT=registry.jan-solver.testnet vault-notary history acme/orders-schema
```

## Installation

Requirements: Python ≥ 3.11. For your own registry: Rust,
[`cargo-near`](https://github.com/near/cargo-near) and
[`near-cli-rs`](https://docs.near.org/tools/cli).

```bash
git clone https://github.com/oerioeoe012-lang/near-vault-notary.git && cd near-vault-notary
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest            # 40 tests, no network needed
cp .env.example .env        # then fill in, see below
```

Read-only commands (`verify`, `history`) only need `NOTARY_CONTRACT`.

### Publishing (testnet)

1. Create a testnet account (funded by the faucet):
   ```bash
   near account create-account sponsor-by-faucet-service YOU.testnet \
     autogenerate-new-keypair save-to-keychain network-config testnet create
   ```
2. Use the shared registry `registry.jan-solver.testnet`, or deploy your own:
   ```bash
   near account create-account fund-myself registry.YOU.testnet '3 NEAR' \
     autogenerate-new-keypair save-to-keychain sign-as YOU.testnet \
     network-config testnet sign-with-keychain send
   cd contract && cargo near build non-reproducible-wasm
   near contract deploy registry.YOU.testnet use-file target/near/note_registry.wasm \
     without-init-call network-config testnet sign-with-keychain send
   ```
3. Create a **function-call access key** that can only call `publish` on the
   registry and cannot move funds, and put it in `.env` as `NEAR_PRIVATE_KEY`:
   ```bash
   near account add-key YOU.testnet grant-function-call-access --allowance '0.25 NEAR' \
     --contract-account-id registry.YOU.testnet --function-names publish \
     autogenerate-new-keypair save-to-legacy-keychain network-config testnet sign-with-keychain send
   # private key: ~/.near-credentials/testnet/YOU.testnet/<public-key>.json
   ```
4. Create a [Pinata](https://pinata.cloud) API key (scope `org:files:write`,
   free plan: 1 GB) and set `PINATA_JWT`.

### Usage

```bash
vault-notary publish [--vault PATH]          # preview, confirm, upload, register
vault-notary verify  <id> [--all] [--show]   # fetch from IPFS, recompute CID, compare
vault-notary verify  <id> --file <path>      # compare a local copy; exit 0 current, 3 outdated, 2 no match
vault-notary history <id>                    # version chain with timestamps
vault-notary notarize <file> --id acme/orders-schema   # register a dataset/schema hash
```

The tool refuses any account that does not end in `.testnet`.

## NEAR building blocks used

| Building block | Used for |
|---|---|
| **NEAR testnet** | all transactions; faucet-funded accounts |
| **near-sdk-rs 5.30** (Rust) | the registry contract: `#[near(contract_state)]`, `store::LookupMap`, `require!`, `env::predecessor_account_id`, `env::block_timestamp`, `env::block_height`, `log!` |
| **cargo-near 0.23** | building the contract to Wasm (with embedded ABI) |
| **near-cli-rs 0.31** | creating accounts, sub-account, deploying, adding access keys |
| **Faucet account creation** (`sponsor-by-faucet-service`) | the author account |
| **Sub-accounts** (`registry.jan-solver.testnet`) | the registry account, owned by the author account |
| **Function-call access keys** with allowance | the CLI's signing key can only call `publish`, max 0.25 NEAR gas, can't transfer funds |
| **Storage staking** | the registry account holds NEAR to pay for its on-chain state |
| **NEAR JSON-RPC** (`query` / `call_function`, FastNEAR testnet RPC) | key-less view calls for `verify` and `history` |
| **near-kit-py** (community Python client) | signing and sending `publish` transactions |
| **NEP-297 event logs** | `EVENT_JSON` log on every publish, for indexers |
| **NearBlocks testnet explorer** | transaction links in CLI output |

Non-NEAR components: IPFS via Pinata (storage), Python (CLI).

## Limitations and next steps

* Prototype: notes up to 256 KiB, no attachments or images.
* The registry account pays storage for all records. Before mainnet, authors
  should attach a storage deposit (otherwise anyone can fill the registry).
* Wikilinks inside code blocks are rewritten like any others.
* Next: authors pay their own storage, an Obsidian plugin, a reader that lives on
  IPFS itself, retraction markers, reproducible contract builds, multi-provider
  pinning, and for data teams: notarizing data contracts directly from CI/dbt
  runs, with `verify --file` as a pipeline gate.

## License

MIT, see [LICENSE](LICENSE).

## Security notes

* `.env` (keys, tokens) is git-ignored; `.env.example` contains no secrets.
* Use a function-call key in `.env`, never a full-access key.
