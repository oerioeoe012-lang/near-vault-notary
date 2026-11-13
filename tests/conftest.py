from pathlib import Path

import pytest


@pytest.fixture
def make_vault(tmp_path: Path):
    def _make(files: dict[str, str]) -> Path:
        for rel, text in files.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return tmp_path
    return _make


class FakeUploader:
    def __init__(self):
        self.uploads: list[tuple[str, bytes]] = []

    def upload(self, content: bytes, name: str) -> str:
        from vault_notary.cid import cid_v1_raw
        self.uploads.append((name, content))
        return cid_v1_raw(content)


class FakeRegistry:
    def __init__(self):
        self.calls: list[tuple[str, str, str | None]] = []

    def publish(self, note_id, cid, prev_cid):
        self.calls.append((note_id, cid, prev_cid))
        return f"tx{len(self.calls)}"


@pytest.fixture
def fakes():
    return FakeUploader(), FakeRegistry()
