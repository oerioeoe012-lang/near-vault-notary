import hashlib

import pytest

from vault_notary.cid import cid_v1_raw, encode_raw_cid
from vault_notary.dataset import file_fingerprint, match_version, plan_notarize


def test_fingerprint_equals_note_cid_for_small_files(tmp_path):
    f = tmp_path / "s.json"
    f.write_bytes(b'{"col": "int"}')
    assert file_fingerprint(f) == cid_v1_raw(b'{"col": "int"}')


def test_fingerprint_streams_large_files(tmp_path):
    f = tmp_path / "big.csv"
    data = b"a,b\n" * 1_000_000  # 4 MB, larger than one IPFS block
    f.write_bytes(data)
    fp = file_fingerprint(f)
    assert fp.startswith("bafkrei")
    assert fp == file_fingerprint(f)
    assert fp == encode_raw_cid(hashlib.sha256(data).digest())


def test_plan_new_and_next_version(tmp_path):
    f = tmp_path / "orders.csv"
    f.write_text("id,total\n1,10\n")
    p1 = plan_notarize(f, "acme/orders", None)
    assert (p1.prev_cid, p1.version, p1.changed) == (None, 1, True)
    record = {"author": "a.testnet", "versions": [{"cid": p1.cid}]}
    assert not plan_notarize(f, "acme/orders", record).changed
    f.write_text("id,total\n1,10\n2,20\n")
    p2 = plan_notarize(f, "acme/orders", record)
    assert (p2.prev_cid, p2.version, p2.owner) == (p1.cid, 2, "a.testnet")


def test_plan_never_carries_file_content(tmp_path):
    f = tmp_path / "secret.csv"
    f.write_text("customer,iban\nACME,DE00SECRET\n")
    p = plan_notarize(f, "acme/customers", None)
    assert "SECRET" not in repr(p.record_id) + p.cid + repr(p.prev_cid)


@pytest.mark.parametrize("bad", ["", "x" * 65])
def test_invalid_id(tmp_path, bad):
    f = tmp_path / "a"
    f.write_text("x")
    with pytest.raises(ValueError):
        plan_notarize(f, bad, None)


def test_match_version():
    rec = {"versions": [{"cid": "c1"}, {"cid": "c2"}]}
    assert match_version("c1", rec) == 1
    assert match_version("c2", rec) == 2
    assert match_version("zz", rec) is None
