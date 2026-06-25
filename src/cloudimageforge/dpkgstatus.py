"""Parse a dpkg status file into a PackageIndex (developer host vs clean image)."""

from __future__ import annotations

from pathlib import Path

from cloudimageforge.depends import BinaryPackage, PackageIndex
from cloudimageforge.packaging import read_control


def parse_dpkg_status(text: str, release: str) -> PackageIndex:
    index = PackageIndex(release=release)
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        fields = read_control(block)
        status = fields.get("Status", "install ok installed")
        if "installed" not in status.split():
            continue
        name = fields.get("Package")
        version = fields.get("Version")
        if not name or not version:
            continue
        index.add(
            BinaryPackage(
                name=name,
                version=version,
                depends=fields.get("Depends", ""),
                essential=fields.get("Essential", "").lower() == "yes",
                architecture=fields.get("Architecture", "amd64"),
                description=fields.get("Description", ""),
            )
        )
    return index


def load_dpkg_status(path: Path, release: str) -> PackageIndex:
    return parse_dpkg_status(path.read_text(encoding="utf-8"), release)
