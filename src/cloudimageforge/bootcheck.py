"""Boot a cloud image in LXD/QEMU (or simulate) and catch broken apt sources."""

from __future__ import annotations

import os
import select
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from cloudimageforge.apt import AptSources, default_cloud_sources, guest_apt_path, lint_sources
from cloudimageforge.exceptions import BootCheckError
from cloudimageforge.images import CloudImageCatalog, create_overlay, pull_image
from cloudimageforge.releases import UbuntuRelease, get_release
from cloudimageforge.seed import MARKER_FAIL, MARKER_OK, cloud_init_meta_data, cloud_init_user_data, create_nocloud_seed
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
    guest = guest_apt_path(release)
    return [
        ["lxc", "launch", alias, name],
        ["lxc", "exec", name, "--", "cloud-init", "status", "--wait"],
        ["lxc", "exec", name, "--", "tee", guest],
        ["lxc", "exec", name, "--", "apt-get", "update"],
        ["lxc", "delete", "--force", name],
    ]


OVMF_CODE_PATHS = (
    Path("/usr/share/OVMF/OVMF_CODE_4M.fd"),
    Path("/usr/share/OVMF/OVMF_CODE.fd"),
    Path("/usr/share/ovmf/OVMF.fd"),
    Path("/usr/share/qemu/OVMF.fd"),
)
OVMF_VARS_PATHS = (
    Path("/usr/share/OVMF/OVMF_VARS_4M.fd"),
    Path("/usr/share/OVMF/OVMF_VARS.fd"),
)


def kvm_usable() -> bool:
    """True only when /dev/kvm exists *and* this user can open it."""
    path = Path("/dev/kvm")
    return path.exists() and os.access(path, os.R_OK | os.W_OK)


def find_ovmf() -> tuple[Path, Path | None] | None:
    code = next((path for path in OVMF_CODE_PATHS if path.exists()), None)
    if code is None:
        return None
    variables = next((path for path in OVMF_VARS_PATHS if path.exists()), None)
    return code, variables


def qemu_commands(
    image: Path,
    seed: Path,
    *,
    memory_mb: int = 2048,
    kvm: bool | None = None,
    firmware: Path | None = None,
    firmware_vars: Path | None = None,
) -> list[str]:
    use_kvm = kvm_usable() if kvm is None else kvm
    accel = "kvm" if use_kvm else "tcg"
    cpu = "host" if use_kvm else "max"
    machine = f"q35,accel={accel}" if firmware else f"accel={accel}"
    firmware_args: list[str] = []
    if firmware and firmware_vars:
        firmware_args = [
            "-drive",
            f"if=pflash,format=raw,readonly=on,file={firmware}",
            "-drive",
            f"if=pflash,format=raw,file={firmware_vars}",
        ]
    elif firmware:
        firmware_args = ["-bios", str(firmware)]
    return [
        "qemu-system-x86_64",
        "-machine",
        machine,
        "-cpu",
        cpu,
        "-smp",
        "2",
        "-m",
        str(memory_mb),
        "-nographic",
        "-no-reboot",
        *firmware_args,
        "-nic",
        "user,model=virtio-net-pci,romfile=",
        "-drive",
        f"file={image},if=virtio,format=qcow2,discard=unmap",
        "-drive",
        f"file={seed},if=virtio,format=raw,readonly=on",
    ]


def simulate_boot(
    release: UbuntuRelease | str,
    sources_text: str | None = None,
    *,
    staging: StagingArchive | None = None,
) -> BootCheckReport:
    """Fast pre-flight used in unit tests and as a gate before a live boot."""
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


def _lxc(*args: str, check: bool = True, timeout: int = 180, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["lxc", *args],
            check=check,
            text=True,
            capture_output=True,
            timeout=timeout,
            input=input_text,
        )
    except FileNotFoundError as exc:
        raise BootCheckError("lxc is not installed; install LXD or use --backend simulate.") from exc
    except subprocess.TimeoutExpired as exc:
        raise BootCheckError(f"lxc {' '.join(args)} timed out") from exc
    except subprocess.CalledProcessError as exc:
        raise BootCheckError(
            f"lxc {' '.join(args)} failed:\n{exc.stderr or exc.stdout}"
        ) from exc


def run_lxd_bootcheck(
    release: UbuntuRelease,
    sources_text: str,
    *,
    name: str,
    timeout: int = 180,
) -> BootCheckReport:
    """Launch ubuntu:{version}, inject apt sources, run apt-get update."""
    alias = f"ubuntu:{release.version}"
    guest = guest_apt_path(release)
    log_parts: list[str] = []
    command = ["lxc", "launch", alias, name]
    subprocess.run(["lxc", "delete", "--force", name], check=False, capture_output=True, text=True)
    try:
        launched = _lxc("launch", alias, name, timeout=timeout)
        log_parts.append(launched.stdout)
        waited = _lxc("exec", name, "--", "cloud-init", "status", "--wait", timeout=timeout)
        log_parts.append(waited.stdout)
        _lxc("exec", name, "--", "tee", guest, timeout=timeout, input_text=sources_text)
        if release.apt_format == "deb822":
            _lxc("exec", name, "--", "sh", "-c", "printf '' > /etc/apt/sources.list", timeout=timeout)
        update = subprocess.run(
            ["lxc", "exec", name, "--", "apt-get", "update"],
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        log_parts.append(update.stdout or "")
        log_parts.append(update.stderr or "")
        ok = update.returncode == 0
        errors = [] if ok else [f"apt-get update failed in LXD guest {name} (exit {update.returncode})"]
        return BootCheckReport(
            backend="lxd",
            release=release.series,
            ok=ok,
            apt_errors=errors,
            command=command,
            log="\n".join(part for part in log_parts if part),
        )
    finally:
        subprocess.run(["lxc", "delete", "--force", name], check=False, capture_output=True, text=True)


def _read_qemu_serial(proc: subprocess.Popen[str], timeout: int) -> tuple[str, str | None]:
    output: list[str] = []
    deadline = time.time() + timeout
    stdout = proc.stdout
    if stdout is None:
        raise BootCheckError("QEMU produced no serial console.")
    while time.time() < deadline:
        if proc.poll() is not None:
            remainder = stdout.read() or ""
            output.append(remainder)
            break
        ready, _, _ = select.select([stdout], [], [], 1.0)
        if not ready:
            continue
        line = stdout.readline()
        if not line:
            continue
        output.append(line)
        if MARKER_OK in line:
            return "".join(output), MARKER_OK
        if MARKER_FAIL in line:
            return "".join(output), MARKER_FAIL
    joined = "".join(output)
    if MARKER_OK in joined:
        return joined, MARKER_OK
    if MARKER_FAIL in joined:
        return joined, MARKER_FAIL
    return joined, None


def _stop_qemu(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def _run_qemu_once(command: list[str], timeout: int) -> tuple[str, str | None]:
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        raise BootCheckError("qemu-system-x86_64 is not installed.") from exc
    try:
        return _read_qemu_serial(proc, timeout)
    finally:
        _stop_qemu(proc)


def run_qemu_bootcheck(
    release: UbuntuRelease,
    sources_text: str,
    image: Path,
    *,
    timeout: int = 600,
    work: Path | None = None,
) -> BootCheckReport:
    """Boot a pulled Ubuntu cloud image with a NoCloud seed and watch serial."""
    if shutil.which("qemu-system-x86_64") is None:
        raise BootCheckError(
            "qemu-system-x86_64 is not installed; install qemu-system-x86 or use --backend simulate."
        )
    if not image.exists():
        raise BootCheckError(f"Cloud image not found: {image}")

    cleanup_work = work is None
    work = Path(work) if work else Path(tempfile.mkdtemp(prefix="ciforge-qemu-"))
    overlay = work / "overlay.qcow2"
    create_overlay(image, overlay)
    seed = create_nocloud_seed(
        work,
        cloud_init_user_data(release, sources_text),
        cloud_init_meta_data(f"ciforge-{release.series}"),
    )
    firmware = None
    firmware_vars = None
    ovmf = find_ovmf()
    if ovmf is not None:
        firmware, vars_src = ovmf
        if vars_src is not None:
            firmware_vars = work / "OVMF_VARS.fd"
            shutil.copyfile(vars_src, firmware_vars)
    command = qemu_commands(
        overlay, seed, firmware=firmware, firmware_vars=firmware_vars
    )
    try:
        log, marker = _run_qemu_once(command, timeout)
        if marker is None and "failed to initialize kvm" in log:
            command = qemu_commands(
                overlay, seed, kvm=False, firmware=firmware, firmware_vars=firmware_vars
            )
            log, marker = _run_qemu_once(command, timeout)
    finally:
        if cleanup_work:
            shutil.rmtree(work, ignore_errors=True)

    if marker == MARKER_OK:
        return BootCheckReport(
            backend="qemu",
            release=release.series,
            ok=True,
            command=command,
            log=log,
        )
    if marker == MARKER_FAIL:
        return BootCheckReport(
            backend="qemu",
            release=release.series,
            ok=False,
            apt_errors=["apt-get update failed in the QEMU guest"],
            command=command,
            log=log,
        )
    raise BootCheckError(
        f"QEMU guest did not report apt-get update within {timeout}s. Serial log:\n{log[-4000:]}"
    )


def bootcheck(
    release: UbuntuRelease | str,
    *,
    backend: str = "simulate",
    sources: AptSources | str | None = None,
    staging: StagingArchive | None = None,
    image: Path | None = None,
    name: str | None = None,
    dry_run: bool = False,
    timeout: int | None = None,
    pull: bool = True,
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

    instance = name or f"ciforge-{rel.series}-{uuid.uuid4().hex[:8]}"

    if backend == "simulate" or dry_run:
        report = simulate_boot(rel, sources_text, staging=staging)
        if dry_run and backend != "simulate":
            if backend == "lxd":
                cmds = lxd_commands(rel, instance)
                report.command = cmds[0]
                report.backend = "lxd"
                report.log = "dry-run: " + " && ".join(" ".join(c) for c in cmds)
            else:
                report.command = qemu_commands(image or Path("cloudimg.qcow2"), Path("seed.img"))
                report.backend = "qemu"
                report.log = "dry-run: " + " ".join(report.command)
        return report

    if backend == "lxd":
        return run_lxd_bootcheck(rel, sources_text, name=instance, timeout=timeout or 180)

    disk = image
    if disk is None and pull:
        catalog = CloudImageCatalog()
        disk = pull_image(catalog.latest(rel, cloud="qemu"))
    if disk is None:
        raise BootCheckError("QEMU boot check requires --image or a successful image pull.")
    return run_qemu_bootcheck(rel, sources_text, Path(disk), timeout=timeout or 600)
