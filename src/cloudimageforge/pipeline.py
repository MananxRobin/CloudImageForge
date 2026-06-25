"""End-to-end release pipeline: build, stage, boot-check, then publish."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cloudimageforge.apt import default_cloud_sources
from cloudimageforge.archive import UbuntuArchiveClient
from cloudimageforge.bootcheck import BootCheckReport, bootcheck
from cloudimageforge.exceptions import PublishBlockedError
from cloudimageforge.packaging import BuildResult, build_package
from cloudimageforge.releases import UbuntuRelease, get_release, parse_release_list
from cloudimageforge.staging import StagingArchive
from cloudimageforge.validate import InteropReport, validate_interop


@dataclass
class PipelineResult:
    build: BuildResult
    boot: BootCheckReport
    interop: InteropReport
    published: Path | None


def run_pipeline(
    package_dir: Path,
    *,
    releases: tuple[UbuntuRelease | str, ...] = ("jammy", "noble"),
    backend: str = "dpkg-deb",
    dest: Path | None = None,
    staging_root: Path | None = None,
    boot_backend: str = "simulate",
    client: UbuntuArchiveClient | None = None,
    host_index=None,
) -> PipelineResult:
    """Build a deb, validate interoperability, stage, boot-check, publish.

    Direct publish is refused unless the clean-image fallback check passes.
    """
    targets = tuple(item if isinstance(item, UbuntuRelease) else get_release(item) for item in releases)
    primary = targets[-1]
    dest = dest or Path("dist")
    staging = StagingArchive(root=staging_root or dest / "staging", client=client or UbuntuArchiveClient())
    control = (package_dir / "DEBIAN" / "control").read_text(encoding="utf-8")

    interop = validate_interop(control, targets, client=staging.client)
    interop.raise_for_status()

    build = build_package(package_dir, dest, backend=backend, release=primary)
    staging.add_deb(build.artifact, control)

    boot_reports = []
    for rel in targets:
        sources = default_cloud_sources(rel).render()
        report = bootcheck(
            rel,
            backend=boot_backend,
            sources=sources,
            staging=staging,
        )
        boot_reports.append(report)
        if not report.ok:
            raise PublishBlockedError(
                f"Boot check failed on {rel.series}: " + "; ".join(report.apt_errors)
            )

    # Re-run fallback with an explicit host index when tests inject extra host packages.
    if host_index is not None:
        report = staging.check(primary, host=host_index)
        report.raise_for_status()
    else:
        # Default host looks like a developer workstation: archive + staged +
        # whatever is already on the machine. The clean image does not get
        # host-only packages; that comparison is staging.check().
        staging.check(primary).raise_for_status()

    published = staging.publish()
    return PipelineResult(build=build, boot=boot_reports[-1], interop=interop, published=published)


def releases_from_arg(value: str) -> tuple[UbuntuRelease, ...]:
    return parse_release_list(value)
