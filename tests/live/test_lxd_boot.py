"""Live hypervisor tests. Skipped unless lxc/qemu are installed."""

from __future__ import annotations

import shutil

import pytest

from cloudimageforge.bootcheck import bootcheck

pytestmark = pytest.mark.live


@pytest.mark.skipif(shutil.which("lxc") is None, reason="lxc is not installed")
def test_lxd_boots_jammy_and_runs_apt_update():
    report = bootcheck("jammy", backend="lxd", timeout=240)
    assert report.backend == "lxd"
    report.raise_for_status()


@pytest.mark.skipif(shutil.which("lxc") is None, reason="lxc is not installed")
def test_lxd_catches_broken_apt_source_in_guest():
    report = bootcheck(
        "jammy",
        backend="lxd",
        sources="deb http://archive.ubuntu.com/ubuntu jamy main\n",
        timeout=240,
    )
    assert report.ok is False
    assert report.apt_errors
