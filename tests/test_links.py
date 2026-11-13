from vault_notary.cid import cid_v1_raw
from vault_notary.links import LinkIndex, render_body
from vault_notary.pipeline import plan
from vault_notary.vault import scan_vault, write_status

PUB = "---\npublish: true\n---\n"
PRIV = "---\npublish: false\n---\n"


def render(make_vault, files, body):
    files = {**files, "Source.md": PUB + body}
    notes = scan_vault(make_vault(files))
    ids = {n.rel: f"id-{n.title}" for n in notes if n.publish}
    src = next(n for n in notes if n.title == "Source")
    return render_body(src.body, LinkIndex(notes), ids)


def test_link_to_published_note_becomes_id_link(make_vault):
    r = render(make_vault, {"Target.md": PUB}, "go [[Target]]")
    assert r.text == "go [Target](note:id-Target)"


def test_alias_heading_and_case(make_vault):
    r = render(make_vault, {"Target.md": PUB}, "[[target#Part 2|see here]]")
    assert r.text == "[see here](note:id-Target)"


def test_path_link_and_md_suffix(make_vault):
    r = render(make_vault, {"A/Target.md": PUB}, "[[A/Target.md]]")
    assert r.text == "[Target](note:id-Target)"


def test_embed_of_published_note(make_vault):
    r = render(make_vault, {"Target.md": PUB}, "![[Target]]")
    assert r.text == "[Target](note:id-Target)"


def test_link_to_private_note_becomes_plain_alias(make_vault):
    r = render(make_vault, {"Private/Salary 2026.md": PRIV}, "[[Private/Salary 2026#Q4|money]]")
    assert r.text == "money"
    assert "Salary" not in r.text and "Private" not in r.text and "Q4" not in r.text
    assert r.delinked == [("Private/Salary 2026", "money")]


def test_link_to_private_note_without_alias_hides_title(make_vault):
    r = render(make_vault, {"Private/Secret Plan.md": PRIV}, "see [[Private/Secret Plan#heading]]")
    assert r.text == "see (private note)"


def test_link_to_missing_note_and_attachment(make_vault):
    r = render(make_vault, {}, "[[Nope]] ![[photo.png]]")
    assert r.text == "(private note) (private note)"


def test_escaped_pipe_in_table(make_vault):
    r = render(make_vault, {"Target.md": PUB}, r"| [[Target\|T]] |")
    assert r.text == "| [T](note:id-Target) |"


def test_duplicate_names_prefer_shortest_path(make_vault):
    r = render(make_vault, {"Target.md": PUB, "deep/Target.md": PRIV}, "[[Target]]")
    assert r.text == "[Target](note:id-Target)"


def test_ids_assigned_in_same_run_are_linked(make_vault):
    root = make_vault({"A.md": PUB + "[[B]]", "B.md": PUB + "[[A]]"})
    a, b = plan(scan_vault(root))
    assert f"(note:{b.note_id})".encode() in a.content
    assert f"(note:{a.note_id})".encode() in b.content


def test_write_status_changes_only_status_line(make_vault):
    original = "---\ntitle: X\npublish: true\ntags: [a, b]\n---\nbody [[link]]\n"
    root = make_vault({"X.md": original})
    [n] = scan_vault(root)
    write_status(n, {"id": "abc", "cid": "bafy1", "version": 1})
    once = (root / "X.md").read_text()
    assert once == original.replace("tags: [a, b]\n", 'tags: [a, b]\npublish_status: {"id": "abc", "cid": "bafy1", "version": 1}\n')
    [n] = scan_vault(root)
    write_status(n, {"id": "abc", "cid": "bafy2", "version": 2})
    twice = (root / "X.md").read_text()
    assert twice == once.replace('"bafy1", "version": 1', '"bafy2", "version": 2')
    assert scan_vault(root)[0].note_id == "abc"


def test_cid_known_vector():
    # CID of the empty file in IPFS (CIDv1, raw codec, sha2-256)
    assert cid_v1_raw(b"") == "bafkreihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"
