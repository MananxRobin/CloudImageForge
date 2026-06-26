"""Ubuntu cloud image catalog from SimpleStreams (cloud-images.ubuntu.com)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cloudimageforge.archive import USER_AGENT
from cloudimageforge.exceptions import ArchiveAPIError, BootCheckError, UnsupportedReleaseError
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

DEFAULT_IMAGE_CACHE = Path.home() / ".cache" / "cloudimageforge" / "images"
Downloader = Callable[[str, Path], None]


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path, timeout: float = 600.0) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, tmp.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        tmp.replace(dest)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ArchiveAPIError(f"Failed to download {url}: {exc}") from exc


def pull_image(
    image: CloudImage,
    dest_dir: Path | None = None,
    *,
    downloader: Downloader | None = None,
) -> Path:
    """Download a cloud image into the local cache and verify its SHA-256."""
    dest_dir = Path(dest_dir) if dest_dir else DEFAULT_IMAGE_CACHE
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(image.path).name
    fetch = downloader or (lambda url, path: _download(url, path))
    if dest.exists() and image.sha256 and sha256_file(dest) == image.sha256:
        return dest
    fetch(image.url, dest)
    if image.sha256 and sha256_file(dest) != image.sha256:
        dest.unlink(missing_ok=True)
        raise ArchiveAPIError(
            f"SHA-256 mismatch for {dest.name}: expected {image.sha256}"
        )
    return dest


QCOW2_MAGIC = b"QFI\xfb"


def backing_format(path: Path) -> str:
    """Detect the real disk format. Ubuntu cloud images are qcow2 even when named .img."""
    if path.exists():
        try:
            with path.open("rb") as handle:
                if handle.read(4) == QCOW2_MAGIC:
                    return "qcow2"
        except OSError:
            pass
    qemu_img = shutil.which("qemu-img")
    if qemu_img and path.exists():
        try:
            result = subprocess.run(
                [qemu_img, "info", "--output=json", str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
            fmt = json.loads(result.stdout).get("format")
            if fmt:
                return str(fmt)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, TypeError):
            pass
    suffix = path.suffix.lower()
    if suffix in {".qcow2", ".qcow"}:
        return "qcow2"
    return "raw"


def create_overlay(backing: Path, overlay: Path, extra: str = "+8G") -> Path:
    """Disposable qcow2 overlay so boot checks do not dirty the pulled image.

    Ubuntu cloud images are nearly full; grow the virtual disk so cloud-init
    can expand the rootfs before apt-get update.
    """
    qemu_img = shutil.which("qemu-img")
    if not qemu_img:
        raise BootCheckError("qemu-img is required (install qemu-utils).")
    overlay.parent.mkdir(parents=True, exist_ok=True)
    if overlay.exists():
        overlay.unlink()
    create = [
        qemu_img,
        "create",
        "-f",
        "qcow2",
        "-F",
        backing_format(backing),
        "-b",
        str(backing.resolve()),
        str(overlay),
    ]
    try:
        subprocess.run(create, check=True, text=True, capture_output=True)
        if extra:
            subprocess.run(
                [qemu_img, "resize", str(overlay), extra],
                check=True,
                text=True,
                capture_output=True,
            )
    except subprocess.CalledProcessError as exc:
        raise BootCheckError(f"qemu-img overlay failed: {exc.stderr or exc.stdout}") from exc
    return overlay
