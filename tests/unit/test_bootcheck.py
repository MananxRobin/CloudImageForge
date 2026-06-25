from cloudimageforge.apt import default_cloud_sources
from cloudimageforge.bootcheck import bootcheck, lxd_commands, qemu_commands
from cloudimageforge.exceptions import BootCheckError
from cloudimageforge.releases import get_release
from pathlib import Path
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
    assert cmds[0] == ["lxc", "launch", "ubuntu:22.04", "ciforge-check", "--ephemeral"]
    assert ["lxc", "exec", "ciforge-check", "--", "apt-get", "update"] in cmds
    qemu = qemu_commands(Path("noble.qcow2"), Path("seed.img"))
    assert qemu[0] == "qemu-system-x86_64"
    assert "noble.qcow2" in " ".join(qemu)


def test_lxd_dry_run_does_not_require_hypervisor():
    report = bootcheck("jammy", backend="lxd", dry_run=True)
    assert report.ok is True
    assert report.command[0] == "lxc"
