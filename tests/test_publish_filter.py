import pytest

from vault_notary.pipeline import execute, plan
from vault_notary.vault import scan_vault

SECRET = "SECRET-BODY-7f3a"


def note(fm: str | None, body: str = "hello") -> str:
    return (f"---\n{fm}\n---\n" if fm is not None else "") + body


@pytest.mark.parametrize("fm, expected", [
    ("publish: true", True),
    ("publish: True", True),
    ("publish: TRUE", True),
    ("title: x\npublish: true  # yes, public", True),
    ("publish: false", False),
    ("title: no publish key", False),
    ('publish: "true"', False),       # string, not boolean
    ("publish: yes", False),          # YAML 1.1 truthy, but not literally true
    ("publish: 1", False),
    ("Publish: true", False),         # wrong key case
    ("meta:\n  publish: true", False),  # nested, not top level
    ("publish: [true", False),        # broken YAML
    ("publish: true\npublish: false", False),  # last key wins in YAML -> false
    (None, False),                    # no frontmatter at all
])
def test_publish_flag(make_vault, fm, expected):
    root = make_vault({"N.md": note(fm)})
    [n] = scan_vault(root)
    assert n.publish is expected


def test_frontmatter_must_be_at_file_start(make_vault):
    root = make_vault({"N.md": "intro\n---\npublish: true\n---\nbody"})
    [n] = scan_vault(root)
    assert n.publish is False


def test_hidden_and_system_folders_ignored(make_vault):
    root = make_vault({
        ".obsidian/x.md": note("publish: true"),
        ".trash/y.md": note("publish: true"),
        "ok.md": note("publish: true"),
    })
    assert [n.rel for n in scan_vault(root)] == ["ok"]


def test_private_note_is_never_uploaded(make_vault, fakes):
    """MANDATORY: a note without `publish: true` never leaves the device.

    Checks the uploader and the registry: no private body, no private title,
    no private path in anything they receive, even when public notes link to,
    or embed, the private notes.
    """
    root = make_vault({
        "Public.md": note("publish: true",
                          "See [[Top Secret Plan]], [[Diary/2026-11-01|my day]] and ![[Top Secret Plan]]."),
        "Top Secret Plan.md": note("publish: false", SECRET),
        "Diary/2026-11-01.md": note("mood: fine", SECRET),
        "Quoted.md": note('publish: "true"', SECRET),
        "Yes.md": note("publish: yes", SECRET),
        "Plain.md": SECRET,
    })
    uploader, registry = fakes
    plans = plan(scan_vault(root))
    execute(plans, uploader, registry)

    assert [name for name, _ in uploader.uploads] == [f"{plans[0].note_id}.md"]
    assert len(registry.calls) == 1
    blob = b"".join(c for _, c in uploader.uploads) + repr(registry.calls).encode()
    assert SECRET.encode() not in blob
    assert b"Diary" not in blob and b"2026-11-01" not in blob
    assert b"Top Secret" not in blob  # private title of an unaliased link/embed
    # The private files on disk are untouched.
    for f in ["Top Secret Plan.md", "Diary/2026-11-01.md", "Quoted.md", "Yes.md", "Plain.md"]:
        assert "publish_status" not in (root / f).read_text()


def test_frontmatter_is_not_uploaded(make_vault, fakes):
    root = make_vault({"P.md": note("publish: true\nprivate_field: hush-hush", "body")})
    uploader, registry = fakes
    execute(plan(scan_vault(root)), uploader, registry)
    assert uploader.uploads[0][1] == b"# P\n\nbody\n"


def test_obsidian_comments_are_stripped(make_vault, fakes):
    root = make_vault({"P.md": note("publish: true", "a %%private remark%% b\n%%\nblock\n%%")})
    uploader, registry = fakes
    execute(plan(scan_vault(root)), uploader, registry)
    assert b"private" not in uploader.uploads[0][1]
    assert b"block" not in uploader.uploads[0][1]


def test_unchanged_note_is_not_republished(make_vault, fakes):
    root = make_vault({"P.md": note("publish: true", "v1")})
    uploader, registry = fakes
    execute(plan(scan_vault(root)), uploader, registry)
    execute(plan(scan_vault(root)), uploader, registry)
    assert len(uploader.uploads) == 1


def test_new_version_keeps_id_and_links_previous_cid(make_vault, fakes):
    root = make_vault({"P.md": note("publish: true", "v1")})
    uploader, registry = fakes
    [p1] = plan(scan_vault(root))
    execute([p1], uploader, registry)
    (root / "P.md").write_text((root / "P.md").read_text().replace("v1", "v2"))
    [p2] = plan(scan_vault(root))
    execute([p2], uploader, registry)
    assert p2.note_id == p1.note_id
    assert registry.calls[1] == (p1.note_id, p2.cid, p1.cid)
    assert p2.version == 2
