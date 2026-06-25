from cloudimageforge.exceptions import UnsupportedReleaseError
from cloudimageforge.releases import JAMMY, NOBLE, get_release, parse_release_list
import pytest


def test_jammy_and_noble_are_supported():
    assert get_release("22.04") is JAMMY
    assert get_release("jammy") is JAMMY
    assert get_release("24.04") is NOBLE
    assert get_release("noble") is NOBLE
    assert JAMMY.apt_format == "list"
    assert NOBLE.apt_format == "deb822"


def test_unsupported_release_is_rejected():
    with pytest.raises(UnsupportedReleaseError, match="focal"):
        get_release("focal")


def test_parse_release_list():
    releases = parse_release_list("jammy, noble")
    assert [item.series for item in releases] == ["jammy", "noble"]
