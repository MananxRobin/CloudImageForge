"""Build .deb packages with dpkg-deb, sbuild, or pbuilder."""

from __future__ import annotations

import gzip
import io
import os
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

from cloudimageforge.exceptions import PackageBuildError
from cloudimageforge.releases import UbuntuRelease, get_release

BACKENDS = ("dpkg-deb", "sbuild", "pbuilder")


@dataclass
class BuildResult:
    backend: str
    artifact: Path
    command: list[str]
    log: str = ""


def read_control(control_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current: str | None = None
    for line in control_text.splitlines():
        if not line:
            continue
        if line[0] in {" ", "\t"} and current:
            fields[current] = fields[current] + "\n" + line.strip()
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current = key.strip()
        fields[current] = value.strip()
    return fields


def _ar_member(name: str, data: bytes, mtime: int) -> bytes:
    header = (
        f"{name:<16}{mtime:<12}{0:<6}{0:<6}{0o100644:<8}{len(data):<10}`\n"
    ).encode("ascii")
    payload = data if len(data) % 2 == 0 else data + b"\n"
    return header + payload


def write_deb_from_tree(package_dir: Path, dest: Path) -> Path:
    """Create a .deb using the ar + tar format that dpkg-deb emits."""
    debian = package_dir / "DEBIAN"
    control_file = debian / "control"
    if not control_file.is_file():
        raise PackageBuildError(f"No DEBIAN/control in {package_dir}")
    fields = read_control(control_file.read_text(encoding="utf-8"))
    name = fields.get("Package")
    version = fields.get("Version")
    arch = fields.get("Architecture", "all")
    if not name or not version:
        raise PackageBuildError("DEBIAN/control must include Package and Version.")
    dest.mkdir(parents=True, exist_ok=True)
    deb_path = dest / f"{name}_{version}_{arch}.deb"
    mtime = int(os.environ.get("SOURCE_DATE_EPOCH", int(time.time())))

    control_buf = io.BytesIO()
    with tarfile.open(fileobj=control_buf, mode="w") as tar:
        for path in sorted(debian.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(debian).as_posix()
            info = tarfile.TarInfo(name=rel)
            data = path.read_bytes()
            info.size = len(data)
            info.mtime = mtime
            info.mode = 0o755 if rel in {"postinst", "prerm", "preinst", "postrm"} else 0o644
            tar.addfile(info, io.BytesIO(data))
    control_tar = gzip.compress(control_buf.getvalue(), mtime=mtime)

    data_buf = io.BytesIO()
    with tarfile.open(fileobj=data_buf, mode="w") as tar:
        for path in sorted(package_dir.rglob("*")):
            if debian in path.parents or path == debian:
                continue
            if not path.is_file():
                continue
            rel = path.relative_to(package_dir).as_posix()
            info = tarfile.TarInfo(name=rel)
            payload = path.read_bytes()
            info.size = len(payload)
            info.mtime = mtime
            info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            tar.addfile(info, io.BytesIO(payload))
    data_tar = gzip.compress(data_buf.getvalue(), mtime=mtime)

    blob = b"!<arch>\n"
    blob += _ar_member("debian-binary", b"2.0\n", mtime)
    blob += _ar_member("control.tar.gz", control_tar, mtime)
    blob += _ar_member("data.tar.gz", data_tar, mtime)
    deb_path.write_bytes(blob)
    return deb_path


def _run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise PackageBuildError(
            f"{command[0]} is not installed. Install it or use --backend dpkg-deb."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise PackageBuildError(
            f"{' '.join(command)} failed:\n{exc.stderr or exc.stdout}"
        ) from exc


def build_dpkg_deb(package_dir: Path, dest: Path) -> BuildResult:
    package_dir = package_dir.resolve()
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    dpkg_deb = shutil.which("dpkg-deb")
    command = ["dpkg-deb", "--root-owner-group", "-b", str(package_dir), str(dest)]
    if dpkg_deb:
        proc = _run(command)
        debs = sorted(dest.glob("*.deb"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not debs:
            raise PackageBuildError("dpkg-deb succeeded but produced no .deb.")
        return BuildResult("dpkg-deb", debs[0], command, proc.stdout)
    artifact = write_deb_from_tree(package_dir, dest)
    return BuildResult("dpkg-deb", artifact, command, "built with built-in dpkg-deb writer")


def sbuild_command(dsc: Path, release: UbuntuRelease) -> list[str]:
    return [
        "sbuild",
        "-d",
        release.series,
        "--no-run-lintian",
        "--no-apt-update",
        str(dsc),
    ]


def pbuilder_command(dsc: Path, release: UbuntuRelease) -> list[str]:
    return [
        "pbuilder",
        "build",
        "--distribution",
        release.series,
        "--basetgz",
        f"/var/cache/pbuilder/{release.series}-base.tgz",
        str(dsc),
    ]


def build_package(
    package_dir: Path,
    dest: Path,
    *,
    backend: str = "dpkg-deb",
    release: UbuntuRelease | str = "noble",
    dsc: Path | None = None,
    dry_run: bool = False,
) -> BuildResult:
    if backend not in BACKENDS:
        raise PackageBuildError(f"Unknown packaging backend {backend!r}. Choose {BACKENDS}.")
    rel = release if isinstance(release, UbuntuRelease) else get_release(release)
    if backend == "dpkg-deb":
        if dry_run:
            return BuildResult("dpkg-deb", dest, ["dpkg-deb", "-b", str(package_dir), str(dest)])
        return build_dpkg_deb(package_dir, dest)
    if dsc is None:
        raise PackageBuildError(f"{backend} requires a .dsc (pass --dsc).")
    command = sbuild_command(dsc, rel) if backend == "sbuild" else pbuilder_command(dsc, rel)
    if dry_run:
        return BuildResult(backend, dest, command, "dry-run")
    proc = _run(command)
    debs = sorted(dest.glob("*.deb"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not debs:
        # sbuild writes to the current directory by default
        debs = sorted(Path.cwd().glob("*.deb"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not debs:
        raise PackageBuildError(f"{backend} produced no .deb artifacts.")
    return BuildResult(backend, debs[0], command, proc.stdout)
