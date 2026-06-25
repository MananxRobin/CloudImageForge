"""Ubuntu 22.04 and 24.04 cloud-image targets."""

from __future__ import annotations

from dataclasses import dataclass

from cloudimageforge.exceptions import UnsupportedReleaseError

SUPPORTED_CLOUDS = ("aws", "azure", "gcp", "gce", "lxd", "qemu", "generic")


@dataclass(frozen=True)
class UbuntuRelease:
    series: str
    version: str
    codename: str
    archive_series_url: str
    default_mirror: str
    security_mirror: str
    apt_format: str  # "list" (22.04) or "deb822" (24.04)


JAMMY = UbuntuRelease(
    series="jammy",
    version="22.04",
    codename="Jammy Jellyfish",
    archive_series_url="https://api.launchpad.net/devel/ubuntu/jammy",
    default_mirror="http://archive.ubuntu.com/ubuntu",
    security_mirror="http://security.ubuntu.com/ubuntu",
    apt_format="list",
)

NOBLE = UbuntuRelease(
    series="noble",
    version="24.04",
    codename="Noble Numbat",
    archive_series_url="https://api.launchpad.net/devel/ubuntu/noble",
    default_mirror="http://archive.ubuntu.com/ubuntu",
    security_mirror="http://security.ubuntu.com/ubuntu",
    apt_format="deb822",
)

_BY_KEY: dict[str, UbuntuRelease] = {
    "jammy": JAMMY,
    "22.04": JAMMY,
    "22.04 lts": JAMMY,
    "noble": NOBLE,
    "24.04": NOBLE,
    "24.04 lts": NOBLE,
}

SUPPORTED_RELEASES = (JAMMY, NOBLE)


def get_release(name: str) -> UbuntuRelease:
    key = name.strip().lower()
    try:
        return _BY_KEY[key]
    except KeyError as exc:
        supported = ", ".join(f"{r.series} ({r.version})" for r in SUPPORTED_RELEASES)
        raise UnsupportedReleaseError(
            f"Unsupported Ubuntu release {name!r}. CloudImageForge targets {supported}."
        ) from exc


def parse_release_list(value: str) -> tuple[UbuntuRelease, ...]:
    parts = [item.strip() for item in value.split(",") if item.strip()]
    if not parts:
        raise UnsupportedReleaseError("At least one Ubuntu release is required.")
    return tuple(get_release(item) for item in parts)
