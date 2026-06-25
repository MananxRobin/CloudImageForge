from cloudimageforge.packaging import build_package, read_control, sbuild_command, write_deb_from_tree
from cloudimageforge.releases import get_release
from pathlib import Path


CONTROL = """Package: ciforge-hello
Version: 0.1.0
Section: utils
Priority: optional
Architecture: all
Maintainer: CloudImageForge <ciforge@example.com>
Depends: python3 (>= 3.10)
Description: Sample Ubuntu cloud image helper
"""


def _tree(root: Path) -> Path:
    debian = root / "DEBIAN"
    debian.mkdir(parents=True)
    (debian / "control").write_text(CONTROL, encoding="utf-8")
    bindir = root / "usr" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "ciforge-hello").write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
    return root


def test_builtin_dpkg_deb_writer_emits_ar_archive(tmp_path: Path):
    pkg = _tree(tmp_path / "pkg")
    deb = write_deb_from_tree(pkg, tmp_path / "out")
    data = deb.read_bytes()
    assert data.startswith(b"!<arch>\n")
    assert b"debian-binary" in data
    assert b"control.tar.gz" in data
    assert deb.name == "ciforge-hello_0.1.0_all.deb"
    assert read_control(CONTROL)["Package"] == "ciforge-hello"


def test_build_package_dpkg_deb_backend(tmp_path: Path):
    pkg = _tree(tmp_path / "pkg")
    result = build_package(pkg, tmp_path / "dist", backend="dpkg-deb")
    assert result.backend == "dpkg-deb"
    assert result.artifact.suffix == ".deb"
    assert result.artifact.exists()


def test_sbuild_and_pbuilder_commands_target_ubuntu_series():
    dsc = Path("ciforge-hello_0.1.0.dsc")
    sbuild = sbuild_command(dsc, get_release("jammy"))
    assert sbuild[:3] == ["sbuild", "-d", "jammy"]
    from cloudimageforge.packaging import pbuilder_command
    pbuilder = pbuilder_command(dsc, get_release("noble"))
    assert pbuilder[0] == "pbuilder"
    assert "noble" in pbuilder
