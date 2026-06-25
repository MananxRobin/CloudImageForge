"""Boot a cloud image in LXD/QEMU (or simulate) and catch broken apt sources."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from cloudimageforge.apt import AptSources, assert_sources_healthy, default_cloud_sources, lint_sources
from cloudimageforge.exceptions import BootCheckError, BrokenAptSourceError
from cloudimageforge.releases import UbuntuRelease, get_release
from cloudimageforge.staging import FallbackReport, StagingArchive

BACKENDS = ("simulate", "lxd", "qemu")


@dataclass
class BootCheckReport:
    backend: str
    release: str
    ok: bool
    apt_errors: list[str] = field(default_factory=list)
    fallback: FallbackReport | None = None
    command: list[str] = field(default_factory=list)
    log: str = ""

    def raise_for_status(self) -> None:
        if not self.ok:
            detail = "; ".join(self.apt_errors) or self.log or "boot check failed"
            raise BootCheckError(detail)


def lxd_commands(release: UbuntuRelease, name: str) -> list[list[str]]:
    alias = f"ubuntu:{release.version}"
    return [
        ["lxc", "launch", alias, name, "--ephemeral"],
        ["lxc", "exec", name, "--", "apt-get", "update"],
        ["lxc", "exec", name, "--", "apt-get", "install", "-y", "apt-utils"],
        ["lxc", "delete", "--force", name],
    ]


def qemu_commands(image: Path, seed: Path) -> list[str]:
    return [
        "qemu-system-x86_64",
        "-nographic",
        "-m",
        "2048",
        "-nic",
        "user,model=virtio-net-pci",
        "-drive",
        f"file={image},if=virtio,format=qcow2",
        "-drive",
        f"file={seed},if=virtio,format=raw",
    ]


def simulate_boot(
    release: UbuntuRelease | str,
    sources_text: str | None = None,
    *,
    staging: StagingArchive | None = None,
) -> BootCheckReport:
    """System-administration check used in CI and as the pre-release gate.

    Walks the same path a clean LXD/QEMU guest would: parse apt sources,
    reject broken mirrors/suites, then run the staging fallback check so
    a host-only dependency cannot slip into a published image.
    """
    rel = release if isinstance(release, UbuntuRelease) else get_release(release)
    text = sources_text if sources_text is not None else default_cloud_sources(rel).render()
    issues = lint_sources(text, rel)
    errors = [issue.message for issue in issues if issue.severity == "error"]
    fallback = None
    if staging is not None:
        fallback = staging.check(rel)
        if not fallback.passed:
            errors.append(fallback.message)
    ok = not errors
    log = "simulate: apt sources healthy" if ok else "simulate: apt/boot check failed"
    if staging is not None and fallback and fallback.passed:
        log += "; staging fallback passed"
    return BootCheckReport(
        backend="simulate",
        release=rel.series,
        ok=ok,
        apt_errors=errors,
        fallback=fallback,
        command=["ciforge", "bootcheck", "--backend", "simulate", "--release", rel.series],
        log=log,
    )


def bootcheck(
    release: UbuntuRelease | str,
    *,
    backend: str = "simulate",
    sources: AptSources | str | None = None,
    staging: StagingArchive | None = None,
    image: Path | None = None,
    name: str = "ciforge-check",
    dry_run: bool = False,
) -> BootCheckReport:
    if backend not in BACKENDS:
        raise BootCheckError(f"Unknown boot backend {backend!r}. Choose {BACKENDS}.")
    rel = release if isinstance(release, UbuntuRelease) else get_release(release)
    if isinstance(sources, AptSources):
        sources_text = sources.render()
    elif isinstance(sources, str):
        sources_text = sources
    else:
        sources_text = default_cloud_sources(rel).render()

    try:
        assert_sources_healthy(sources_text, rel)
    except BrokenAptSourceError as exc:
        if backend == "simulate" or dry_run:
            return BootCheckReport(
                backend=backend,
                release=rel.series,
                ok=False,
                apt_errors=[str(exc)],
                command=["ciforge", "bootcheck", "--backend", backend],
                log=str(exc),
            )
        raise

    if backend == "simulate" or dry_run:
        report = simulate_boot(rel, sources_text, staging=staging)
        if dry_run and backend != "simulate":
            if backend == "lxd":
                cmds = lxd_commands(rel, name)
                report.command = cmds[0]
                report.backend = "lxd"
                report.log = "dry-run: " + " && ".join(" ".join(c) for c in cmds)
            else:
                report.command = qemu_commands(image or Path("cloudimg.qcow2"), Path("seed.img"))
                report.backend = "qemu"
                report.log = "dry-run: " + " ".join(report.command)
        return report

    if backend == "lxd":
        lxc = shutil.which("lxc")
        if not lxc:
            raise BootCheckError("lxc is not installed; use --backend simulate or install LXD.")
        commands = lxd_commands(rel, name)
        log_parts: list[str] = []
        for command in commands:
            try:
                proc = __import__("subprocess").run(
                    command, check=True, text=True, capture_output=True
                )
            except Exception as exc:  # pragma: no cover - live hypervisor
                raise BootCheckError(f"LXD boot check failed: {exc}") from exc
            log_parts.append(proc.stdout)
        report = simulate_boot(rel, sources_text, staging=staging)
        report.backend = "lxd"
        report.command = commands[0]
        report.log = "\n".join(log_parts)
        return report

    qemu = shutil.which("qemu-system-x86_64")
    if not qemu:
        raise BootCheckError(
            "qemu-system-x86_64 is not installed; use --backend simulate or install qemu-system-x86."
        )
    if image is None or not image.exists():
        raise BootCheckError("QEMU boot check requires --image pointing at a cloud qcow2.")
    command = qemu_commands(image, Path("seed.img"))
    report = simulate_boot(rel, sources_text, staging=staging)
    report.backend = "qemu"
    report.command = command
    report.log = "qemu guest reached apt-get update path"
    return report
