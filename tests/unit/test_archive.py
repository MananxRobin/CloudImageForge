from cloudimageforge.archive import UbuntuArchiveClient, index_from_dataset, load_bundled_dataset
from cloudimageforge.exceptions import ArchiveAPIError
import pytest
import urllib.parse


def test_bundled_dataset_covers_jammy_and_noble():
    dataset = load_bundled_dataset()
    jammy = index_from_dataset(dataset, "jammy")
    noble = index_from_dataset(dataset, "noble")
    assert jammy.get("python3").version.startswith("3.10")
    assert noble.get("python3").version.startswith("3.12")
    assert jammy.get("liblocalfoo1") is None
    assert jammy.get("libc6").essential is True


def test_query_binary_from_dataset():
    client = UbuntuArchiveClient()
    pkg = client.query_binary("hello", "jammy")
    assert pkg.name == "hello"
    assert "libc6" in pkg.depends


def test_query_unknown_binary_raises():
    client = UbuntuArchiveClient()
    with pytest.raises(ArchiveAPIError, match="liblocalfoo1"):
        client.query_binary("liblocalfoo1", "jammy")


def test_get_published_sources_uses_launchpad_op(monkeypatch):
    seen = {}

    def fake_fetch(url: str):
        seen["url"] = url
        return {
            "entries": [
                {
                    "source_package_name": "hello",
                    "source_package_version": "2.10-2ubuntu4",
                    "component_name": "main",
                    "pocket": "Release",
                    "status": "Published",
                }
            ]
        }

    client = UbuntuArchiveClient(fetch=fake_fetch)
    entries = client.get_published_sources("hello", "jammy")
    assert entries[0]["source_package_name"] == "hello"
    assert "ws.op=getPublishedSources" in seen["url"]
    assert "ubuntu%2Fjammy" in seen["url"] or "ubuntu/jammy" in urllib.parse.unquote(seen["url"])
