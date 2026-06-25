"""Ubuntu cloud image catalog from SimpleStreams (cloud-images.ubuntu.com)."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from cloudimageforge.archive import USER_AGENT
from cloudimageforge.exceptions import ArchiveAPIError, UnsupportedReleaseError
from cloudimageforge.releases import SUPPORTED_CLOUDS, UbuntuRelease, get_release

STREAM_INDEX = "https://cloud-images.ubuntu.com/releases/streams/v1/index.json"
DOWNLOAD_STREAM = (
    "https://cloud-images.ubuntu.com/releases/streams/v1/"
    "com.ubuntu.cloud:released:download.json"
)

CLOUD_FTYPES = {
    "qemu": ("disk1.img", "disk.img", "qcow2"),
    "generic": ("disk1.img", "disk.img"),
    "lxd": ("squashfs", "lxd.tar.xz", "disk-kvm.img"),
    "aws": ("disk1.img",),
    "azure": ("disk1.img", "vhd.zip", "vhd.tar.gz"),
    "gcp": ("disk1.img", "tar.gz"),
    "gce": ("disk1.img", "tar.gz"),
}


@dataclass(frozen=True)
class CloudImage:
    release: str
    version: str
    arch: str
    cloud: str
    serial: str
    ftype: str
    path: str
    sha256: str | None
    size: int | None
    pubname: str | None = None

    @property
    def url(self) -> str:
        return f"https://cloud-images.ubuntu.com/{self.path.lstrip('/')}"


def _default_fetch(url: str, timeout: float = 30.0) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except OSError as exc:
        raise ArchiveAPIError(f"Unable to fetch Ubuntu cloud image stream: {exc}") from exc


class CloudImageCatalog:
    """Parse Ubuntu SimpleStreams product files for 22.04 and 24.04."""

    def __init__(
        self,
        *,
        fetch: Callable[[str], Any] | None = None,
        products: dict[str, Any] | None = None,
    ) -> None:
        self._fetch = fetch or _default_fetch
        self._products = products

    def load(self, url: str = DOWNLOAD_STREAM) -> dict[str, Any]:
        if self._products is None:
            self._products = self._fetch(url)
        return self._products

    def list_images(
        self,
        release: UbuntuRelease | str | None = None,
        *,
        cloud: str = "qemu",
        arch: str = "amd64",
    ) -> list[CloudImage]:
        if cloud not in SUPPORTED_CLOUDS:
            raise UnsupportedReleaseError(
                f"Unknown cloud {cloud!r}. Supported: {', '.join(SUPPORTED_CLOUDS)}"
            )
        rel = get_release(release) if release else None
        products = self.load().get("products", {})
        wanted = CLOUD_FTYPES.get(cloud, CLOUD_FTYPES["generic"])
        found: list[CloudImage] = []
        for product_id, product in products.items():
            series = product.get("release")
            version = str(product.get("version", ""))
            product_arch = product.get("arch") or product.get("architecture")
            if rel and series not in {rel.series, rel.version} and version != rel.version:
                continue
            if product_arch and product_arch != arch:
                continue
            versions = product.get("versions") or {}
            for serial, version_entry in sorted(versions.items(), reverse=True):
                items = version_entry.get("items") or {}
                for item in items.values():
                    ftype = item.get("ftype") or item.get("path", "").rsplit(".", 1)[-1]
                    if ftype not in wanted and not any(ftype.startswith(w) for w in wanted):
                        continue
                    found.append(
                        CloudImage(
                            release=series or (rel.series if rel else ""),
                            version=version,
                            arch=product_arch or arch,
                            cloud=cloud,
                            serial=serial,
                            ftype=ftype,
                            path=item.get("path", ""),
                            sha256=item.get("sha256"),
                            size=item.get("size"),
                            pubname=item.get("pubname") or product_id,
                        )
                    )
        return found

    def latest(
        self,
        release: UbuntuRelease | str,
        *,
        cloud: str = "qemu",
        arch: str = "amd64",
    ) -> CloudImage:
        images = self.list_images(release, cloud=cloud, arch=arch)
        if not images:
            rel = get_release(release)
            raise ArchiveAPIError(
                f"No {cloud} cloud image found for Ubuntu {rel.series} {rel.version} ({arch})."
            )
        return images[0]
