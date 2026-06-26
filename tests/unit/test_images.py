import hashlib
from pathlib import Path

from cloudimageforge.images import CloudImage, CloudImageCatalog, pull_image, sha256_file
import json

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "simplestreams.json"


def test_catalog_lists_jammy_and_noble_qemu_images():
    products = json.loads(FIXTURE.read_text(encoding="utf-8"))
    catalog = CloudImageCatalog(products=products)
    jammy = catalog.latest("jammy", cloud="qemu")
    noble = catalog.latest("noble", cloud="qemu")
    assert jammy.release == "jammy"
    assert jammy.version == "22.04"
    assert jammy.ftype == "disk1.img"
    assert "ubuntu-22.04-server-cloudimg-amd64.img" in jammy.path
    assert jammy.url.startswith("https://cloud-images.ubuntu.com/")
    assert noble.release == "noble"
    assert noble.serial >= jammy.serial or noble.version == "24.04"


def test_latest_accepts_ubuntu_release_object():
    from cloudimageforge.releases import JAMMY

    products = json.loads(FIXTURE.read_text(encoding="utf-8"))
    catalog = CloudImageCatalog(products=products)
    image = catalog.latest(JAMMY, cloud="qemu")
    assert image.release == "jammy"
    products = json.loads(FIXTURE.read_text(encoding="utf-8"))
    catalog = CloudImageCatalog(products=products)
    images = catalog.list_images("noble", cloud="lxd")
    assert any(item.ftype == "squashfs" for item in images)


def test_pull_image_verifies_sha256_and_reuses_cache(tmp_path: Path):
    blob = b"fake-ubuntu-cloud-image"
    digest = hashlib.sha256(blob).hexdigest()
    image = CloudImage(
        release="jammy",
        version="22.04",
        arch="amd64",
        cloud="qemu",
        serial="20240701",
        ftype="disk1.img",
        path="releases/jammy/release-20240701/ubuntu-22.04-server-cloudimg-amd64.img",
        sha256=digest,
        size=len(blob),
    )
    calls: list[str] = []

    def download(url: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes(blob)

    first = pull_image(image, tmp_path, downloader=download)
    second = pull_image(image, tmp_path, downloader=download)
    assert first == second
    assert sha256_file(first) == digest
    assert len(calls) == 1
    assert calls[0] == image.url


def test_pull_image_rejects_checksum_mismatch(tmp_path: Path):
    image = CloudImage(
        release="jammy",
        version="22.04",
        arch="amd64",
        cloud="qemu",
        serial="20240701",
        ftype="disk1.img",
        path="releases/jammy/x.img",
        sha256="0" * 64,
        size=1,
    )

    def download(url: str, dest: Path) -> None:
        dest.write_bytes(b"nope")

    from cloudimageforge.exceptions import ArchiveAPIError
    import pytest

    with pytest.raises(ArchiveAPIError, match="SHA-256"):
        pull_image(image, tmp_path, downloader=download)
