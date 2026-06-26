from cloudimageforge.apt import default_cloud_sources
from cloudimageforge.bootcheck import bootcheck, lxd_commands, qemu_commands, run_lxd_bootcheck
from cloudimageforge.exceptions import BootCheckError
from cloudimageforge.releases import get_release
from cloudimageforge.seed import MARKER_OK
from pathlib import Path
import io
import subprocess
import pytest


def test_simulate_boot_catches_broken_apt_source_before_release():
    broken = "deb http://archive.ubuntu.com/ubuntu jamy main\n"
    report = bootcheck("jammy", backend="simulate", sources=broken)
    assert report.ok is False
    assert report.apt_errors
    with pytest.raises(BootCheckError):
        report.raise_for_status()


def test_simulate_boot_accepts_default_cloud_sources():
    text = default_cloud_sources("noble").render()
    report = bootcheck("noble", backend="simulate", sources=text)
    assert report.ok is True
    assert report.backend == "simulate"


def test_lxd_and_qemu_commands_are_real_sysadmin_invocations():
    cmds = lxd_commands(get_release("jammy"), "ciforge-check")
    assert cmds[0] == ["lxc", "launch", "ubuntu:22.04", "ciforge-check"]
    assert ["lxc", "exec", "ciforge-check", "--", "apt-get", "update"] in cmds

    qemu = qemu_commands(Path("noble.qcow2"), Path("seed.img"), kvm=False)
    assert qemu[0] == "qemu-system-x86_64"
    assert "accel=tcg" in qemu
    assert qemu[qemu.index("-cpu") + 1] == "max"
    assert "noble.qcow2" in " ".join(qemu)
    assert "-netdev" in qemu
    assert "virtio-net-pci,netdev=net0" in qemu

    uefi = qemu_commands(
        Path("noble.qcow2"),
        Path("seed.img"),
        kvm=False,
        firmware=Path("/usr/share/OVMF/OVMF_CODE_4M.fd"),
        firmware_vars=Path("OVMF_VARS.fd"),
    )
    assert "q35,accel=tcg" in uefi
    assert "if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd" in uefi


def test_lxd_dry_run_does_not_require_hypervisor():
    report = bootcheck("jammy", backend="lxd", dry_run=True)
    assert report.ok is True
    assert report.command[0] == "lxc"


def test_lxd_boot_injects_sources_and_runs_apt_update(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr("cloudimageforge.bootcheck.subprocess.run", fake_run)
    report = run_lxd_bootcheck(get_release("jammy"), "deb http://archive.ubuntu.com/ubuntu jammy main\n", name="ciforge-unit")
    assert report.ok is True
    assert report.backend == "lxd"
    assert ["lxc", "launch", "ubuntu:22.04", "ciforge-unit"] in calls
    assert any(cmd[:4] == ["lxc", "exec", "ciforge-unit", "--"] and "apt-get" in cmd for cmd in calls)
    assert any("tee" in cmd and cmd[-1] == "/etc/apt/sources.list" for cmd in calls)
    assert ["lxc", "delete", "--force", "ciforge-unit"] in calls


def test_qemu_serial_ok_marker_completes_bootcheck(monkeypatch, tmp_path: Path):
    image = tmp_path / "disk.img"
    image.write_bytes(b"img")
    overlay = tmp_path / "work" / "overlay.qcow2"

    monkeypatch.setattr("cloudimageforge.bootcheck.shutil.which", lambda name: f"/usr/bin/{name}")

    def fake_overlay(backing, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"qcow")
        return dest

    monkeypatch.setattr("cloudimageforge.bootcheck.create_overlay", fake_overlay)
    monkeypatch.setattr(
        "cloudimageforge.bootcheck.create_nocloud_seed",
        lambda work, user_data, meta_data: (work / "seed.iso").write_text("seed") or (work / "seed.iso"),
    )

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            self.stdout = io.StringIO(f"cloud-init starting\n{MARKER_OK}\n")
            self._cmd = cmd

        def poll(self):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr("cloudimageforge.bootcheck.subprocess.Popen", FakePopen)
    from cloudimageforge.bootcheck import run_qemu_bootcheck

    report = run_qemu_bootcheck(
        get_release("jammy"),
        default_cloud_sources("jammy").render(),
        image,
        timeout=5,
        work=tmp_path / "work",
    )
    assert report.ok is True
    assert report.backend == "qemu"
    assert MARKER_OK in report.log
    assert overlay.exists() or report.command[0] == "qemu-system-x86_64"
