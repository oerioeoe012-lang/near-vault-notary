#!/usr/bin/env bash
# Two-minute demo on NEAR testnet. Press Enter to advance each step.
# Uses a fresh copy of examples/ in demo-run/ (git-ignored) so the repo stays clean.
set -euo pipefail
cd "$(dirname "$0")"
VN=.venv/bin/vault-notary
step() { echo; printf '\033[1;36m### %s\033[0m' "$1"; read -r _; }

rm -rf demo-run && mkdir demo-run
cp -R examples/demo-vault demo-run/vault && cp -R examples/data demo-run/data
cp demo-run/data/orders.schema.json demo-run/schema-v1-copy.json
NOTE="demo-run/vault/Research/Data Contracts.md"
SCHEMA_ID="acme/orders-schema-$(date +%H%M%S)"

step "1. The vault: 2 public notes, 2 private ones"
find demo-run/vault -name '*.md' | sort
grep -H "^publish" demo-run/vault -r || true

step "2. Publish: preview first, nothing leaves the device before you confirm"
$VN publish --vault demo-run/vault

ID=$(grep publish_status "$NOTE" | sed -E 's/.*"id": "([^"]+)".*/\1/')
step "3. What is public on IPFS (verified against the NEAR registry)"
$VN verify "$ID" --show

step "4. Edit the note and publish again: new version, same id"
printf '\nUpdate: contracts should be versioned and notarized on NEAR.\n' >> "$NOTE"
$VN publish --vault demo-run/vault --yes

step "5. History: version chain with block timestamps"
$VN history "$ID"

step "6. Data provenance: notarize a data contract, the file never leaves the device"
$VN notarize demo-run/data/orders.schema.json --id "$SCHEMA_ID" --yes
python3 - <<'PY'
import json; p="demo-run/data/orders.schema.json"; d=json.load(open(p))
d["columns"]["coupon_code"]={"type":"string","nullable":True}; json.dump(d,open(p,"w"),indent=2)
PY
$VN notarize demo-run/data/orders.schema.json --id "$SCHEMA_ID" --yes

step "7. Which version is this copy? current / outdated / tampered"
$VN verify "$SCHEMA_ID" --file demo-run/data/orders.schema.json || true
$VN verify "$SCHEMA_ID" --file demo-run/schema-v1-copy.json || true
sed 's/24/48/' demo-run/schema-v1-copy.json > demo-run/tampered.json
$VN verify "$SCHEMA_ID" --file demo-run/tampered.json || true
echo; echo "Done."
