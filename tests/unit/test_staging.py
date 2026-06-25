from cloudimageforge.archive import UbuntuArchiveClient
from cloudimageforge.depends import BinaryPackage
from cloudimageforge.exceptions import PublishBlockedError, StagingRequiredError
from cloudimageforge.staging import StagingArchive, fallback_check, merge_index
from pathlib import Path
import pytest

HOST_ONLY = """Package: ciforge-agent
Version: 0.1.0
Architecture: all
Depends: python3 (>= 3.10), liblocalfoo1
Description: Agent that accidentally depends on a host-only library
"""

CLEAN = """Package: ciforge-hello
Version: 0.1.0
Architecture: all
Depends: python3 (>= 3.10), libc6
Description: Hello package installable on jammy and noble
"""


def test_dependency_resolves_on_host_but_fails_on_clean_image():
    client = UbuntuArchiveClient()
    archive = client.index("jammy")
    clean = merge_index(client.clean_image_index("jammy"), archive)
    host = merge_index(archive, client.clean_image_index("jammy"))
    host.add(BinaryPackage("liblocalfoo1", "1.0-1local", description="built on the developer laptop"))
    binary = BinaryPackage("ciforge-agent", "0.1.0", depends="python3 (>= 3.10), liblocalfoo1")
    report = fallback_check(binary, host, clean)
    assert report.passed is False
    assert report.reason == "host_only_resolution"
    assert "liblocalfoo1" in report.missing_on_clean[0]
    assert "clean Ubuntu jammy image" in report.message
    with pytest.raises(StagingRequiredError, match="Launchpad-style staging"):
        report.raise_for_status()


def test_direct_publish_blocked_until_fallback_passes(tmp_path: Path):
    staging = StagingArchive(root=tmp_path)
    staging.add_from_control(HOST_ONLY)
    client = UbuntuArchiveClient()
    host = client.index("jammy")
    host.add(BinaryPackage("liblocalfoo1", "1.0-1local"))
    report = staging.check("jammy", host=host)
    assert report.passed is False
    with pytest.raises(PublishBlockedError, match="Refusing direct publish"):
        staging.publish()


def test_archive_satisfiable_package_can_publish(tmp_path: Path):
    staging = StagingArchive(root=tmp_path)
    staging.add_from_control(CLEAN)
    report = staging.check("jammy")
    assert report.passed is True
    published = staging.publish()
    assert published.read_text(encoding="utf-8").startswith("promoted")


def test_staging_persists_across_cli_style_reloads(tmp_path: Path):
    first = StagingArchive(root=tmp_path)
    first.add_from_control(CLEAN)
    first.check("noble")
    second = StagingArchive(root=tmp_path)
    assert second.staged[0].name == "ciforge-hello"
    assert second.last_report is not None
    assert second.last_report.passed is True
    second.publish()
