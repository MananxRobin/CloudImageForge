"""Validate package interoperability across Ubuntu 22.04 and 24.04."""

from __future__ import annotations

from dataclasses import dataclass

from cloudimageforge.archive import UbuntuArchiveClient
from cloudimageforge.depends import BinaryPackage, resolve
from cloudimageforge.exceptions import InteropError
from cloudimageforge.releases import UbuntuRelease, get_release
from cloudimageforge.staging import binary_from_control, merge_index


@dataclass
class ReleaseInterop:
    release: str
    version: str
    ok: bool
    missing: list[str]


@dataclass
class InteropReport:
    package: str
    results: list[ReleaseInterop]

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.results)

    def raise_for_status(self) -> None:
        if self.ok:
            return
        failed = [item for item in self.results if not item.ok]
        details = "; ".join(
            f"{item.release} ({item.version}): missing {', '.join(item.missing)}"
            for item in failed
        )
        raise InteropError(
            f"{self.package} is not installable on every target release: {details}"
        )


def validate_interop(
    binary: BinaryPackage | str,
    releases: tuple[UbuntuRelease | str, ...],
    *,
    client: UbuntuArchiveClient | None = None,
) -> InteropReport:
    """Confirm Depends can be satisfied from each target series' Archive."""
    pkg = binary if isinstance(binary, BinaryPackage) else binary_from_control(binary)
    archive = client or UbuntuArchiveClient()
    results: list[ReleaseInterop] = []
    for item in releases:
        rel = item if isinstance(item, UbuntuRelease) else get_release(item)
        index = merge_index(archive.clean_image_index(rel), archive.index(rel))
        resolved = resolve(pkg.depends, index)
        results.append(
            ReleaseInterop(
                release=rel.series,
                version=rel.version,
                ok=resolved.ok,
                missing=list(resolved.missing),
            )
        )
    return InteropReport(package=pkg.name, results=results)
