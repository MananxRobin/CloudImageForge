"""Render and lint Ubuntu apt sources for jammy (list) and noble (DEB822)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cloudimageforge.exceptions import BrokenAptSourceError
from cloudimageforge.releases import UbuntuRelease, get_release

VALID_COMPONENTS = ("main", "restricted", "universe", "multiverse")
VALID_POCKETS = ("release", "updates", "security", "proposed", "backports")
_LIST_LINE = re.compile(
    r"^(?P<disabled>#\s*)?(?P<type>deb-src|deb)\s+(?:\[(?P<options>[^\]]+)\]\s+)?"
    r"(?P<uri>\S+)\s+(?P<suite>\S+)(?:\s+(?P<components>.+))?$"
)


@dataclass
class AptSource:
    types: tuple[str, ...]
    uris: tuple[str, ...]
    suites: tuple[str, ...]
    components: tuple[str, ...]
    signed_by: str | None = None
    disabled: bool = False


@dataclass
class AptLintIssue:
    severity: str  # "error" or "warning"
    code: str
    message: str
    line: int | None = None


@dataclass
class AptSources:
    release: UbuntuRelease
    sources: list[AptSource] = field(default_factory=list)

    def render(self, fmt: str | None = None) -> str:
        style = fmt or self.release.apt_format
        if style == "deb822":
            return render_deb822(self.sources)
        return render_list(self.sources)


def default_cloud_sources(
    release: UbuntuRelease | str,
    *,
    components: tuple[str, ...] = ("main", "universe"),
    pockets: tuple[str, ...] = ("release", "updates", "security"),
    include_src: bool = False,
) -> AptSources:
    """Return the apt sources a clean Ubuntu cloud image should ship."""
    rel = release if isinstance(release, UbuntuRelease) else get_release(release)
    types = ("deb", "deb-src") if include_src else ("deb",)
    signed = "/usr/share/keyrings/ubuntu-archive-keyring.gpg"
    archive_suites = []
    security_suites = []
    for pocket in pockets:
        if pocket not in VALID_POCKETS:
            raise BrokenAptSourceError(f"Unknown apt pocket {pocket!r}.")
        if pocket == "release":
            archive_suites.append(rel.series)
        elif pocket == "security":
            security_suites.append(f"{rel.series}-security")
        else:
            archive_suites.append(f"{rel.series}-{pocket}")
    sources: list[AptSource] = []
    if archive_suites:
        sources.append(
            AptSource(
                types=types,
                uris=(rel.default_mirror,),
                suites=tuple(archive_suites),
                components=components,
                signed_by=signed,
            )
        )
    if security_suites:
        sources.append(
            AptSource(
                types=types,
                uris=(rel.security_mirror,),
                suites=tuple(security_suites),
                components=components,
                signed_by=signed,
            )
        )
    return AptSources(release=rel, sources=sources)


def render_list(sources: list[AptSource]) -> str:
    lines: list[str] = []
    for src in sources:
        for uri in src.uris:
            for suite in src.suites:
                for kind in src.types:
                    options = []
                    if src.signed_by:
                        options.append(f"signed-by={src.signed_by}")
                    opt = f" [{' '.join(options)}]" if options else ""
                    prefix = "# " if src.disabled else ""
                    lines.append(
                        f"{prefix}{kind}{opt} {uri} {suite} {' '.join(src.components)}"
                    )
    return "\n".join(lines) + ("\n" if lines else "")


def render_deb822(sources: list[AptSource]) -> str:
    stanzas: list[str] = []
    for src in sources:
        rows = [
            f"Types: {' '.join(src.types)}",
            f"URIs: {' '.join(src.uris)}",
            f"Suites: {' '.join(src.suites)}",
            f"Components: {' '.join(src.components)}",
        ]
        if src.signed_by:
            rows.append(f"Signed-By: {src.signed_by}")
        if src.disabled:
            rows.append("Enabled: no")
        stanzas.append("\n".join(rows))
    return "\n\n".join(stanzas) + ("\n" if stanzas else "")


def parse_sources(text: str) -> list[AptSource]:
    if "Types:" in text or "URIs:" in text:
        return _parse_deb822(text)
    return _parse_list(text)


def _parse_list(text: str) -> list[AptSource]:
    sources: list[AptSource] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _LIST_LINE.match(line)
        if not match:
            if line.startswith("#"):
                continue
            raise BrokenAptSourceError(f"Unparseable apt sources line: {raw}")
        options = match.group("options") or ""
        signed_by = None
        for opt in options.split():
            if opt.startswith("signed-by="):
                signed_by = opt.split("=", 1)[1]
        components = tuple((match.group("components") or "").split())
        sources.append(
            AptSource(
                types=(match.group("type"),),
                uris=(match.group("uri"),),
                suites=(match.group("suite"),),
                components=components,
                signed_by=signed_by,
                disabled=bool(match.group("disabled")),
            )
        )
    return sources


def _parse_deb822(text: str) -> list[AptSource]:
    sources: list[AptSource] = []
    current: dict[str, str] = {}

    def flush() -> None:
        if not current:
            return
        types = tuple(current.get("types", "deb").split())
        uris = tuple(current.get("uris", "").split())
        suites = tuple(current.get("suites", "").split())
        components = tuple(current.get("components", "").split())
        enabled = current.get("enabled", "yes").lower() not in {"no", "false"}
        sources.append(
            AptSource(
                types=types,
                uris=uris,
                suites=suites,
                components=components,
                signed_by=current.get("signed-by"),
                disabled=not enabled,
            )
        )

    for raw in text.splitlines():
        if not raw.strip():
            flush()
            current = {}
            continue
        if ":" not in raw:
            raise BrokenAptSourceError(f"Unparseable DEB822 apt line: {raw}")
        key, value = raw.split(":", 1)
        current[key.strip().lower()] = value.strip()
    flush()
    return sources


def lint_sources(
    text: str,
    release: UbuntuRelease | str | None = None,
) -> list[AptLintIssue]:
    """Catch broken apt sources before they reach a clean cloud image."""
    issues: list[AptLintIssue] = []
    rel = get_release(release) if isinstance(release, str) else release
    try:
        sources = parse_sources(text)
    except BrokenAptSourceError as exc:
        return [AptLintIssue("error", "parse", str(exc))]

    if not sources:
        issues.append(AptLintIssue("error", "empty", "No apt sources were found."))
        return issues

    for index, src in enumerate(sources, start=1):
        if src.disabled:
            continue
        if not src.uris:
            issues.append(AptLintIssue("error", "missing-uri", "Source has no URI.", index))
        if not src.suites:
            issues.append(AptLintIssue("error", "missing-suite", "Source has no suite.", index))
        if not src.components:
            issues.append(
                AptLintIssue("error", "missing-components", "Source has no components.", index)
            )
        for component in src.components:
            if component not in VALID_COMPONENTS:
                issues.append(
                    AptLintIssue(
                        "error",
                        "unknown-component",
                        f"Unknown component {component!r}; did you mean one of {VALID_COMPONENTS}?",
                        index,
                    )
                )
        if not src.signed_by:
            issues.append(
                AptLintIssue(
                    "warning",
                    "unsigned",
                    "Source has no signed-by keyring; apt update will fail on Ubuntu 24.04.",
                    index,
                )
            )
        for suite in src.suites:
            series = suite.split("-", 1)[0]
            if rel and series != rel.series:
                issues.append(
                    AptLintIssue(
                        "error",
                        "suite-mismatch",
                        f"Suite {suite!r} does not match image release {rel.series} ({rel.version}).",
                        index,
                    )
                )
            if suite.endswith("-security"):
                for uri in src.uris:
                    if "archive.ubuntu.com" in uri:
                        issues.append(
                            AptLintIssue(
                                "error",
                                "security-mirror",
                                "Security pocket must use security.ubuntu.com, not archive.ubuntu.com.",
                                index,
                            )
                        )
            if suite in {"jamy", "nobl", "impish", "focal"} or (
                rel and suite.startswith(rel.series[:3]) and not suite.startswith(rel.series)
            ):
                if rel and not suite.startswith(rel.series):
                    issues.append(
                        AptLintIssue(
                            "error",
                            "typo-suite",
                            f"Suite {suite!r} looks like a typo for {rel.series}.",
                            index,
                        )
                    )
        for uri in src.uris:
            if " " in uri or not re.match(r"^[a-z][a-z0-9+.-]*://", uri):
                issues.append(
                    AptLintIssue("error", "bad-uri", f"Invalid apt URI {uri!r}.", index)
                )
    return issues


def assert_sources_healthy(text: str, release: UbuntuRelease | str | None = None) -> None:
    errors = [issue for issue in lint_sources(text, release) if issue.severity == "error"]
    if errors:
        details = "; ".join(issue.message for issue in errors)
        raise BrokenAptSourceError(details)
