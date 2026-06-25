from cloudimageforge.apt import (
    assert_sources_healthy,
    default_cloud_sources,
    lint_sources,
    parse_sources,
)
from cloudimageforge.exceptions import BrokenAptSourceError
import pytest


def test_jammy_default_sources_use_list_format_and_security_mirror():
    text = default_cloud_sources("jammy").render()
    assert "deb [signed-by=" in text
    assert "http://archive.ubuntu.com/ubuntu jammy main universe" in text
    assert "http://archive.ubuntu.com/ubuntu jammy-updates" in text
    assert "http://security.ubuntu.com/ubuntu jammy-security" in text
    assert "archive.ubuntu.com/ubuntu jammy-security" not in text


def test_noble_default_sources_use_deb822():
    text = default_cloud_sources("noble").render()
    assert text.startswith("Types: deb")
    assert "Suites: noble noble-updates" in text
    assert "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg" in text
    assert "security.ubuntu.com" in text


def test_lint_catches_typo_suite_on_clean_image():
    broken = "deb http://archive.ubuntu.com/ubuntu jamy main universe\n"
    issues = lint_sources(broken, "jammy")
    codes = {issue.code for issue in issues}
    assert "suite-mismatch" in codes or "typo-suite" in codes
    with pytest.raises(BrokenAptSourceError):
        assert_sources_healthy(broken, "jammy")


def test_lint_catches_security_pocket_on_archive_mirror():
    broken = (
        "deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] "
        "http://archive.ubuntu.com/ubuntu jammy-security main\n"
    )
    issues = lint_sources(broken, "jammy")
    assert any(issue.code == "security-mirror" for issue in issues)


def test_lint_catches_unknown_component():
    broken = (
        "deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] "
        "http://archive.ubuntu.com/ubuntu noble unverse\n"
    )
    issues = lint_sources(broken, "noble")
    assert any(issue.code == "unknown-component" for issue in issues)


def test_lint_healthy_jammy_sources_pass():
    text = default_cloud_sources("jammy").render()
    assert lint_sources(text, "jammy") == []


def test_parse_roundtrip_list_and_deb822():
    jammy = default_cloud_sources("jammy").render("list")
    assert parse_sources(jammy)
    noble = default_cloud_sources("noble").render("deb822")
    parsed = parse_sources(noble)
    assert parsed[0].suites[0] == "noble"
