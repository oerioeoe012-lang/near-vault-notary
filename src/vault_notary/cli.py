"""vault-notary command line."""

from __future__ import annotations

import os
import sys

import click
from dotenv import find_dotenv, load_dotenv

from . import chain, storage
from .cid import cid_v1_raw
from .dataset import file_fingerprint, match_version, plan_notarize
from .pipeline import execute, plan
from .vault import scan_vault

EXPLORER = "https://testnet.nearblocks.io/txns/"


def fail(msg: str) -> None:
    click.secho(f"error: {msg}", fg="red", err=True)
    sys.exit(1)


@click.group()
def main() -> None:
    """Publish selected Obsidian notes to IPFS with provenance on NEAR (testnet)."""
    load_dotenv(find_dotenv(usecwd=True))


@main.command()
@click.option("--vault", type=click.Path(file_okay=False), default=lambda: os.environ.get("VAULT_PATH"),
              help="Vault directory (default: $VAULT_PATH)")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt (for scripted demos).")
def publish(vault: str | None, yes: bool) -> None:
    """Preview, confirm, upload and register all notes with `publish: true`."""
    if not vault:
        fail("no vault given: use --vault or set VAULT_PATH")
    notes = scan_vault(vault)
    plans = plan(notes)
    todo = [p for p in plans if p.changed]

    click.echo(f"Vault: {vault}")
    click.echo(f"{len(notes)} notes scanned, {len(plans)} marked `publish: true`, "
               f"{len(notes) - len(plans)} stay private.\n")
    for p in plans:
        tag = ("NEW" if p.is_new else "UPDATE") if p.changed else "unchanged"
        colour = {"NEW": "green", "UPDATE": "yellow"}.get(tag)
        click.echo(click.style(f"  {tag:9}", fg=colour) + f" {p.note.rel}  ({len(p.content)} B, v{p.version})")
        click.echo(f"            id  {p.note_id}")
        if p.changed:
            click.echo(f"            cid {p.cid}")
        if p.delinked:
            click.echo("            links to private/missing notes become plain text:")
            for target, repl in p.delinked:
                click.echo(f"              [[{target}]] -> \"{repl}\"")
    if not todo:
        click.echo("\nNothing to publish.")
        return
    click.secho(f"\n{len(todo)} note(s) will be uploaded to public IPFS. This cannot be undone.", bold=True)
    if not yes and not click.confirm("Publish now?", default=False):
        click.echo("Aborted, nothing left the device.")
        return

    try:
        uploader, registry = storage.PinataUploader(), chain.NearRegistry()
    except RuntimeError as e:
        fail(str(e))

    def done(p, tx):
        click.echo(f"  published {p.note.rel} v{p.version}  tx {EXPLORER}{tx}")

    execute(todo, uploader, registry, on_done=done)
    click.secho("Done. Status written to each note's `publish_status` field.", fg="green")


@main.command()
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--id", "record_id", required=True, help="Stable registry id, e.g. acme/orders-schema (max 64 chars).")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def notarize(path: str, record_id: str, yes: bool) -> None:
    """Register a dataset/schema file's fingerprint. The file itself is never uploaded."""
    p = plan_notarize(path, record_id, chain.get_note(record_id))
    click.echo(f"File     {p.path}  ({p.size:,} B, stays on this device)")
    click.echo(f"Id       {p.record_id}")
    click.echo(f"Hash     {p.cid}")
    if not p.changed:
        click.echo(f"Unchanged: already registered as v{p.version}.")
        return
    click.echo(f"Version  v{p.version}" + (f" (previous {p.prev_cid})" if p.prev_cid else " (new record)"))
    try:
        registry = chain.NearRegistry()
    except RuntimeError as e:
        fail(str(e))
    if p.owner and p.owner != registry.account_id:
        fail(f"{record_id} belongs to {p.owner}; only that account can add versions")
    if not yes and not click.confirm("Write this hash to the NEAR registry?", default=False):
        click.echo("Aborted.")
        return
    tx = registry.publish(p.record_id, p.cid, p.prev_cid)
    click.secho(f"Registered v{p.version}  tx {EXPLORER}{tx}", fg="green")


@main.command()
@click.argument("note_id")
@click.option("--file", "local_file", type=click.Path(exists=True, dir_okay=False),
              help="Check a local copy against the registry instead of fetching from IPFS.")
@click.option("--all", "all_versions", is_flag=True, help="Verify every version, not just the latest.")
@click.option("--show", is_flag=True, help="Print the verified content.")
def verify(note_id: str, local_file: str | None, all_versions: bool, show: bool) -> None:
    """Fetch the note from IPFS, recompute its CID and compare with the registry."""
    record = chain.get_note(note_id)
    if not record:
        fail(f"note {note_id} is not in registry {chain.contract_id()}")
    if local_file:
        _verify_local(note_id, record, local_file)
        return
    versions = record["versions"] if all_versions else record["versions"][-1:]
    ok = True
    for i, v in enumerate(versions, start=len(record["versions"]) - len(versions) + 1):
        content, gw = storage.fetch(v["cid"])
        actual = cid_v1_raw(content)
        match = actual == v["cid"]
        ok &= match
        click.echo(f"v{i}  registry cid  {v['cid']}")
        click.echo(f"    computed cid  {actual}  (bytes from {gw})")
        click.secho(f"    {'MATCH' if match else 'MISMATCH'}", fg="green" if match else "red", bold=True)
        click.echo(f"    author {v['author']}, published {chain.ns_to_iso(v['timestamp_ns'])}, "
                   f"block {v['block_height']}")
        if show and match:
            click.echo("\n" + content.decode("utf-8", "replace"))
    sys.exit(0 if ok else 2)


def _verify_local(record_id: str, record: dict, path: str) -> None:
    cid = file_fingerprint(path)
    n = match_version(cid, record)
    total = len(record["versions"])
    click.echo(f"File {path}\nHash {cid}")
    if n is None:
        click.secho(f"NO MATCH: this file is not any registered version of {record_id}", fg="red", bold=True)
        sys.exit(2)
    v = record["versions"][n - 1]
    state = "the CURRENT version" if n == total else f"an OUTDATED version (latest is v{total})"
    click.secho(f"MATCH: v{n} of {total}, {state}", fg="green" if n == total else "yellow", bold=True)
    click.echo(f"registered by {v['author']} at {chain.ns_to_iso(v['timestamp_ns'])}, block {v['block_height']}")
    sys.exit(0 if n == total else 3)


@main.command()
@click.argument("note_id")
def history(note_id: str) -> None:
    """Show the version chain of a note."""
    record = chain.get_note(note_id)
    if not record:
        fail(f"note {note_id} is not in registry {chain.contract_id()}")
    click.echo(f"Note {note_id}  author {record['author']}  registry {chain.contract_id()}\n")
    prev = None
    for i, v in enumerate(record["versions"], start=1):
        linked = v["prev_cid"] == prev
        click.echo(f"  v{i}  {chain.ns_to_iso(v['timestamp_ns'])}  block {v['block_height']}")
        click.echo(f"      cid  {v['cid']}")
        click.echo(f"      prev {v['prev_cid'] or '-'}" + ("" if linked else click.style("  (broken chain!)", fg="red")))
        prev = v["cid"]


def run() -> None:
    """Console entry point: show configuration/network errors without a traceback."""
    import httpx
    try:
        main(standalone_mode=True)
    except (RuntimeError, FileNotFoundError, ValueError, httpx.HTTPError) as e:
        fail(str(e))


if __name__ == "__main__":
    run()
