from cloudimageforge.images import CloudImageCatalog
from pathlib import Path
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
    assert noble.release == "noble"
    assert noble.serial >= jammy.serial or noble.version == "24.04"


def test_lxd_images_use_squashfs():
    products = json.loads(FIXTURE.read_text(encoding="utf-8"))
    catalog = CloudImageCatalog(products=products)
    images = catalog.list_images("noble", cloud="lxd")
    assert any(item.ftype == "squashfs" for item in images)
