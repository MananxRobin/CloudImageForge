"""Launchpad-style staging archive and the clean-image fallback check."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from cloudimageforge.archive import UbuntuArchiveClient
from cloudimageforge.depends import BinaryPackage, PackageIndex, resolve
from cloudimageforge.exceptions import PublishBlockedError, StagingRequiredError
from cloudimageforge.packaging import read_control
from cloudimageforge.releases import UbuntuRelease, get_release


@dataclass
class FallbackReport:
    passed: bool
    host_ok: bool
    clean_ok: bool
    missing_on_clean: list[str]
    satisfied_on_host: dict[str, str]
    release: str
    reason: str
    message: str

    def raise_for_status(self) -> None:
        if not self.passed:
            raise StagingRequiredError(self.message)


def fallback_check(
    binary: BinaryPackage,
    host: PackageIndex,
    clean: PackageIndex,
) -> FallbackReport:
    """Compare resolution on a dirty host vs a clean cloud image.

    This is the edge case that forced Launchpad-style staging: an apt
    dependency can resolve locally because the package is already
    installed (or comes from a developer PPA) and still fail on a
    freshly booted Ubuntu cloud image that only sees the Archive.
    """
    host_result = resolve(binary.depends, host)
    clean_result = resolve(binary.depends, clean)
    release = clean.release
    if host_result.ok and not clean_result.ok:
        missing = ", ".join(clean_result.missing)
        message = (
            f"Dependencies [{missing}] resolved on the local host but are not "
            f"installable on a clean Ubuntu {release} image. Publish to a "
            "Launchpad-style staging archive and re-run the fallback check "
            "before release."
        )
        return FallbackReport(
            passed=False,
            host_ok=True,
            clean_ok=False,
            missing_on_clean=list(clean_result.missing),
            satisfied_on_host=dict(host_result.satisfied_by),
            release=release,
            reason="host_only_resolution",
            message=message,
        )
    if not host_result.ok:
        missing = ", ".join(host_result.missing)
        return FallbackReport(
            passed=False,
            host_ok=False,
            clean_ok=clean_result.ok,
            missing_on_clean=list(clean_result.missing),
            satisfied_on_host={},
            release=release,
            reason="unresolvable",
            message=f"Dependencies [{missing}] do not resolve on the host either.",
        )
    return FallbackReport(
        passed=True,
        host_ok=True,
        clean_ok=True,
        missing_on_clean=[],
        satisfied_on_host=dict(host_result.satisfied_by),
        release=release,
        reason="ok",
        message=f"Dependencies install on a clean Ubuntu {release} image.",
    )


def binary_from_control(control_text: str) -> BinaryPackage:
    fields = read_control(control_text)
    name = fields.get("Package")
    version = fields.get("Version")
    if not name or not version:
        raise StagingRequiredError("Control file is missing Package or Version.")
    return BinaryPackage(
        name=name,
        version=version,
        depends=fields.get("Depends", ""),
        architecture=fields.get("Architecture", "all"),
        description=fields.get("Description", ""),
    )


def merge_index(base: PackageIndex, extra: PackageIndex) -> PackageIndex:
    merged = PackageIndex(release=base.release, packages=dict(base.packages))
    for pkg in extra.packages.values():
        merged.add(pkg)
    return merged


@dataclass
class StagingArchive:
    """A local Launchpad-style staging pocket that must pass before publish."""

    root: Path
    client: UbuntuArchiveClient = field(default_factory=UbuntuArchiveClient)
    staged: list[BinaryPackage] = field(default_factory=list)
    last_report: FallbackReport | None = None
    promoted: bool = False

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self._load()

    def _load(self) -> None:
        if not self.root.exists():
            return
        loaded: list[BinaryPackage] = []
        for path in sorted(self.root.glob("*.control")):
            loaded.append(binary_from_control(path.read_text(encoding="utf-8")))
        if loaded:
            self.staged = loaded
        marker = self.root / "published"
        self.promoted = marker.is_file()
        report_path = self.root / "last-check.json"
        if report_path.is_file():
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.last_report = FallbackReport(**payload)

    def _save_report(self) -> None:
        if self.last_report is None:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "passed": self.last_report.passed,
            "host_ok": self.last_report.host_ok,
            "clean_ok": self.last_report.clean_ok,
            "missing_on_clean": self.last_report.missing_on_clean,
            "satisfied_on_host": self.last_report.satisfied_on_host,
            "release": self.last_report.release,
            "reason": self.last_report.reason,
            "message": self.last_report.message,
        }
        (self.root / "last-check.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def add_from_control(self, control_text: str) -> BinaryPackage:
        binary = binary_from_control(control_text)
        self.staged = [pkg for pkg in self.staged if pkg.name != binary.name]
        self.staged.append(binary)
        self.promoted = False
        self.last_report = None
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "pool").mkdir(exist_ok=True)
        (self.root / f"{binary.name}.control").write_text(control_text, encoding="utf-8")
        for stale in ("last-check.json", "published"):
            path = self.root / stale
            if path.exists():
                path.unlink()
        return binary

    def add_deb(self, deb_path: Path, control_text: str) -> BinaryPackage:
        binary = self.add_from_control(control_text)
        target = self.root / "pool" / deb_path.name
        target.write_bytes(deb_path.read_bytes())
        return binary

    def staged_index(self, release: str) -> PackageIndex:
        index = PackageIndex(release=release)
        for pkg in self.staged:
            index.add(pkg)
        return index

    def check(
        self,
        release: UbuntuRelease | str,
        *,
        host: PackageIndex | None = None,
        include_staged_on_clean: bool = False,
    ) -> FallbackReport:
        rel = release if isinstance(release, UbuntuRelease) else get_release(release)
        if not self.staged:
            raise StagingRequiredError("Staging archive is empty.")
        clean = self.client.clean_image_index(rel)
        archive = self.client.index(rel)
        if include_staged_on_clean:
            clean = merge_index(merge_index(clean, archive), self.staged_index(rel.series))
        else:
            # A clean image sees Essential packages plus the Ubuntu Archive,
            # but not developer-only packages sitting on the host.
            clean = merge_index(clean, archive)
        if host is None:
            host = merge_index(archive, self.staged_index(rel.series))
        reports = [fallback_check(pkg, host, clean) for pkg in self.staged]
        failed = next((item for item in reports if not item.passed), None)
        self.last_report = failed or reports[-1]
        self._save_report()
        return self.last_report

    def publish(self) -> Path:
        if self.last_report is None:
            raise PublishBlockedError(
                "Refusing direct publish. Run the staging fallback check first."
            )
        if not self.last_report.passed:
            raise PublishBlockedError(
                "Refusing direct publish: " + self.last_report.message
            )
        self.promoted = True
        marker = self.root / "published"
        marker.write_text("promoted from staging\n", encoding="utf-8")
        return marker
