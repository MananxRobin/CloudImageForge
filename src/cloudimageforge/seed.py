"""NoCloud cloud-init seed used to inject apt sources into a QEMU guest."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from cloudimageforge.apt import guest_apt_path
from cloudimageforge.exceptions import BootCheckError
from cloudimageforge.releases import UbuntuRelease, get_release

MARKER_OK = "CIFORGE_BOOTCHECK=OK"
MARKER_FAIL = "CIFORGE_BOOTCHECK=FAIL"


def cloud_init_user_data(release: UbuntuRelease | str, sources_text: str) -> str:
    """Write apt sources into the guest and run apt-get update on first boot."""
    rel = release if isinstance(release, UbuntuRelease) else get_release(release)
    path = guest_apt_path(rel)
    body = "\n".join(f"      {line}" if line else "      " for line in sources_text.splitlines())
    return f"""#cloud-config
hostname: ciforge-check
manage_etc_hosts: true
package_update: false
package_upgrade: false
ssh_pwauth: false
growpart:
  mode: auto
  devices: ["/"]
resize_rootfs: true
apt:
  preserve_sources_list: true
write_files:
  - path: /etc/ciforge/apt-sources
    permissions: '0644'
    content: |
{body}
runcmd:
  - |
    mkdir -p /etc/apt/sources.list.d
    find /etc/apt/sources.list.d -type f -delete
    printf '' > /etc/apt/sources.list
    install -D -m 0644 /etc/ciforge/apt-sources {path}
    if apt-get update; then
      echo {MARKER_OK}
    else
      echo {MARKER_FAIL}
    fi
    poweroff
"""


def cloud_init_meta_data(instance_id: str = "ciforge-check") -> str:
    return f"instance-id: {instance_id}\nlocal-hostname: {instance_id}\n"


def create_nocloud_seed(work: Path, user_data: str, meta_data: str) -> Path:
    """Build a cidata volume (VFAT via cloud-localds, else ISO 9660)."""
    work.mkdir(parents=True, exist_ok=True)
    seed_dir = work / "cidata"
    seed_dir.mkdir(exist_ok=True)
    user_path = seed_dir / "user-data"
    meta_path = seed_dir / "meta-data"
    user_path.write_text(user_data, encoding="utf-8")
    meta_path.write_text(meta_data, encoding="utf-8")

    if shutil.which("cloud-localds"):
        image = work / "seed.img"
        _run(["cloud-localds", str(image), str(user_path), str(meta_path)])
        return image

    iso = work / "seed.iso"
    if shutil.which("xorriso"):
        _run(
            [
                "xorriso",
                "-as",
                "mkisofs",
                "-V",
                "cidata",
                "-J",
                "-R",
                "-o",
                str(iso),
                str(seed_dir),
            ]
        )
        return iso
    if shutil.which("genisoimage"):
        _run(
            [
                "genisoimage",
                "-output",
                str(iso),
                "-volid",
                "cidata",
                "-joliet",
                "-rock",
                str(seed_dir),
            ]
        )
        return iso
    if shutil.which("mkisofs"):
        _run(
            [
                "mkisofs",
                "-output",
                str(iso),
                "-volid",
                "cidata",
                "-joliet",
                "-rock",
                str(seed_dir),
            ]
        )
        return iso
    if shutil.which("hdiutil"):
        _run(
            [
                "hdiutil",
                "makehybrid",
                "-iso",
                "-joliet",
                "-default-volume-name",
                "CIDATA",
                "-o",
                str(iso),
                str(seed_dir),
            ]
        )
        return iso
    raise BootCheckError(
        "Cannot build a NoCloud seed. Install cloud-image-utils, xorriso, genisoimage, or hdiutil."
    )


def _run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, text=True, capture_output=True)
    except FileNotFoundError as exc:
        raise BootCheckError(f"{command[0]} is not installed") from exc
    except subprocess.CalledProcessError as exc:
        raise BootCheckError(f"{' '.join(command)} failed:\n{exc.stderr or exc.stdout}") from exc
