"""Ubuntu Archive client backed by the Launchpad API and a local dataset."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from importlib import resources
from typing import Any, Callable

from cloudimageforge.depends import BinaryPackage, PackageIndex
from cloudimageforge.exceptions import ArchiveAPIError
from cloudimageforge.releases import UbuntuRelease, get_release

LAUNCHPAD_PRIMARY = "https://api.launchpad.net/devel/ubuntu/+archive/primary"
USER_AGENT = "CloudImageForge/0.1.0 (+https://github.com/MananxRobin/CloudImageForge)"

Fetch = Callable[[str], Any]


def _default_fetch(url: str, timeout: float = 30.0) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ArchiveAPIError(f"Launchpad API HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise ArchiveAPIError(f"Launchpad API unreachable: {exc.reason}") from exc


def load_bundled_dataset() -> dict[str, Any]:
    path = resources.files("cloudimageforge").joinpath("data/archive_snapshot.json")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def index_from_dataset(dataset: dict[str, Any], release: UbuntuRelease | str) -> PackageIndex:
    rel = release if isinstance(release, UbuntuRelease) else get_release(release)
    series_data = dataset.get("releases", dataset).get(rel.series)
    if not series_data:
        raise ArchiveAPIError(f"No Ubuntu Archive snapshot for {rel.series}.")
    index = PackageIndex(release=rel.series)
    for name, meta in series_data["packages"].items():
        index.add(
            BinaryPackage(
                name=name,
                version=meta["version"],
                depends=meta.get("depends", ""),
                essential=bool(meta.get("essential", False)),
                component=meta.get("component", "main"),
                architecture=meta.get("architecture", "amd64"),
                description=meta.get("description", ""),
            )
        )
    return index


def essential_index(dataset: dict[str, Any], release: UbuntuRelease | str) -> PackageIndex:
    """Clean-image dpkg status: Essential packages plus apt/python3-minimal."""
    full = index_from_dataset(dataset, release)
    clean = PackageIndex(release=full.release)
    for name, pkg in full.packages.items():
        if pkg.essential or name in {"apt", "python3-minimal", "ubuntu-keyring", "gpgv"}:
            clean.add(pkg)
    return clean


class UbuntuArchiveClient:
    """Query published sources via Launchpad and resolve binaries from the dataset."""

    def __init__(
        self,
        *,
        fetch: Fetch | None = None,
        dataset: dict[str, Any] | None = None,
        primary_url: str = LAUNCHPAD_PRIMARY,
    ) -> None:
        self._fetch = fetch or _default_fetch
        self._dataset = dataset if dataset is not None else load_bundled_dataset()
        self.primary_url = primary_url

    def get_published_sources(
        self,
        source_name: str,
        release: UbuntuRelease | str,
        *,
        pocket: str = "Release",
        exact_match: bool = True,
        status: str = "Published",
    ) -> list[dict[str, Any]]:
        rel = release if isinstance(release, UbuntuRelease) else get_release(release)
        query = urllib.parse.urlencode(
            {
                "ws.op": "getPublishedSources",
                "source_name": source_name,
                "exact_match": str(exact_match).lower(),
                "status": status,
                "pocket": pocket,
                "distro_series": rel.archive_series_url,
                "ws.size": 75,
            }
        )
        payload = self._fetch(f"{self.primary_url}?{query}")
        if not isinstance(payload, dict):
            raise ArchiveAPIError("Launchpad getPublishedSources returned a non-object.")
        return list(payload.get("entries", []))

    def query_binary(self, name: str, release: UbuntuRelease | str) -> BinaryPackage:
        index = index_from_dataset(self._dataset, release)
        pkg = index.get(name)
        if pkg is None:
            rel = release if isinstance(release, UbuntuRelease) else get_release(release)
            raise ArchiveAPIError(
                f"{name!r} is not in the Ubuntu Archive dataset for {rel.series}."
            )
        return pkg

    def index(self, release: UbuntuRelease | str) -> PackageIndex:
        return index_from_dataset(self._dataset, release)

    def clean_image_index(self, release: UbuntuRelease | str) -> PackageIndex:
        return essential_index(self._dataset, release)
