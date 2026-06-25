from pathlib import Path

import pytest

from cloudimageforge.archive import UbuntuArchiveClient
from cloudimageforge.depends import BinaryPackage
from cloudimageforge.exceptions import InteropError, PublishBlockedError, StagingRequiredError
from cloudimageforge.pipeline import run_pipeline

HELLO = """Package: ciforge-hello
Version: 0.1.0
Section: utils
Priority: optional
Architecture: all
Maintainer: CloudImageForge <ciforge@example.com>
Depends: python3 (>= 3.10), libc6
Description: Interoperable helper for jammy and noble cloud images
"""

HOST_ONLY = """Package: ciforge-agent
Version: 0.1.0
Section: utils
Priority: optional
Architecture: all
Maintainer: CloudImageForge <ciforge@example.com>
Depends: python3 (>= 3.10), liblocalfoo1
Description: Looks fine on a dirty host, fails on a clean image
"""


def _pkg(root: Path, control: str) -> Path:
    debian = root / "DEBIAN"
    debian.mkdir(parents=True)
    (debian / "control").write_text(control, encoding="utf-8")
    dest = root / "usr" / "share" / "doc" / "pkg"
    dest.mkdir(parents=True)
    (dest / "README").write_text("ok\n", encoding="utf-8")
    return root


@pytest.mark.functional
def test_pipeline_publishes_after_clean_image_checks(tmp_path: Path):
    pkg = _pkg(tmp_path / "hello", HELLO)
    result = run_pipeline(
        pkg,
        releases=("jammy", "noble"),
        dest=tmp_path / "dist",
        staging_root=tmp_path / "staging",
        boot_backend="simulate",
    )
    assert result.build.artifact.exists()
    assert result.boot.ok is True
    assert result.interop.ok is True
    assert result.published is not None
    assert result.published.exists()


@pytest.mark.functional
def test_pipeline_blocks_host_only_dependency(tmp_path: Path):
    pkg = _pkg(tmp_path / "agent", HOST_ONLY)
    client = UbuntuArchiveClient()
    host = client.index("jammy")
    host.add(BinaryPackage("liblocalfoo1", "1.0-1local"))
    with pytest.raises((PublishBlockedError, StagingRequiredError, InteropError)):
        run_pipeline(
            pkg,
            releases=("jammy",),
            dest=tmp_path / "dist",
            staging_root=tmp_path / "staging",
            boot_backend="simulate",
            host_index=host,
        )
