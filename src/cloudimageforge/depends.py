"""Debian Depends parsing and resolution against an apt package index."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_VERSIONED = re.compile(
    r"^\s*([a-z0-9][a-z0-9+\-.]+)(?:\s*\(\s*(<<|<=|=|>=|>>)\s*([^)]+?)\s*\))?\s*$"
)


@dataclass(frozen=True)
class DepAtom:
    name: str
    operator: str | None = None
    version: str | None = None

    def __str__(self) -> str:
        if self.operator and self.version:
            return f"{self.name} ({self.operator} {self.version})"
        return self.name


@dataclass
class BinaryPackage:
    name: str
    version: str
    depends: str = ""
    essential: bool = False
    component: str = "main"
    architecture: str = "amd64"
    description: str = ""


@dataclass
class PackageIndex:
    """An apt-like package index for one Ubuntu series."""

    release: str
    packages: dict[str, BinaryPackage] = field(default_factory=dict)

    def add(self, package: BinaryPackage) -> None:
        self.packages[package.name] = package

    def get(self, name: str) -> BinaryPackage | None:
        return self.packages.get(name)

    def names(self) -> set[str]:
        return set(self.packages)


@dataclass
class ResolveResult:
    ok: bool
    missing: list[str]
    satisfied_by: dict[str, str]

    @property
    def host_only(self) -> bool:
        return False


def parse_depends(field: str) -> list[list[DepAtom]]:
    """Parse a Depends field into AND-of-OR groups of atoms.

    ``foo, bar | baz (>= 1.0)`` becomes ``[[foo], [bar, baz (>= 1.0)]]``.
    Substvars such as ``${shlibs:Depends}`` are ignored until expanded.
    """
    if not field or not field.strip():
        return []
    groups: list[list[DepAtom]] = []
    for and_part in field.split(","):
        and_part = and_part.strip()
        if not and_part or and_part.startswith("${"):
            continue
        alternatives: list[DepAtom] = []
        for or_part in and_part.split("|"):
            token = or_part.strip()
            if not token or token.startswith("${"):
                continue
            # Drop architecture qualifiers: python3:any, foo [amd64]
            token = token.split("[", 1)[0].strip()
            token = token.split(":", 1)[0].strip() if ":" in token and "(" not in token.split(":")[0] else token
            if ":" in token and "(" not in token:
                token = token.split(":", 1)[0].strip()
            match = _VERSIONED.match(token)
            if not match:
                continue
            alternatives.append(DepAtom(match.group(1), match.group(2), match.group(3)))
        if alternatives:
            groups.append(alternatives)
    return groups


def _debian_order(ch: str) -> tuple[int, str]:
    if ch == "~":
        return (0, ch)
    if ch.isdigit():
        return (1, ch)
    if ch.isalpha():
        return (2, ch)
    return (3, ch)


def compare_versions(left: str, right: str) -> int:
    """Return -1/0/1 using a simplified Debian version comparison."""

    def split_epoch(value: str) -> tuple[int, str]:
        if ":" in value:
            epoch, rest = value.split(":", 1)
            if epoch.isdigit():
                return int(epoch), rest
        return 0, value

    def tokens(value: str) -> list[str]:
        parts: list[str] = []
        buf = ""
        digit = None
        for ch in value:
            is_digit = ch.isdigit()
            if digit is None:
                buf, digit = ch, is_digit
                continue
            if is_digit == digit:
                buf += ch
            else:
                parts.append(buf)
                buf, digit = ch, is_digit
        if buf:
            parts.append(buf)
        return parts

    le, lv = split_epoch(left)
    re, rv = split_epoch(right)
    if le != re:
        return -1 if le < re else 1
    # Strip debian revision for a first pass, then compare full strings
    # including revision so 1.0-1 < 1.0-2.
    lt, rt = tokens(lv), tokens(rv)
    n = max(len(lt), len(rt))
    for i in range(n):
        a = lt[i] if i < len(lt) else "0" if (rt[i].isdigit() if i < len(rt) else False) else ""
        b = rt[i] if i < len(rt) else "0" if (lt[i].isdigit() if i < len(lt) else False) else ""
        if i >= len(lt):
            a = "0" if rt[i].isdigit() else ""
        if i >= len(rt):
            b = "0" if lt[i].isdigit() else ""
        if a.isdigit() and b.isdigit():
            ai, bi = int(a), int(b)
            if ai != bi:
                return -1 if ai < bi else 1
            continue
        if a.isdigit() != b.isdigit():
            # digits sort after letters in Debian versions except tilde
            if a.isdigit():
                return 1 if b != "" else 1
            return -1
        for ca, cb in zip(a, b):
            oa, ob = _debian_order(ca), _debian_order(cb)
            if oa != ob:
                return -1 if oa < ob else 1
        if len(a) != len(b):
            return -1 if len(a) < len(b) else 1
    return 0


def version_satisfies(have: str, operator: str | None, needed: str | None) -> bool:
    if not operator or not needed:
        return True
    cmp = compare_versions(have, needed)
    if operator == ">=":
        return cmp >= 0
    if operator == "<=":
        return cmp <= 0
    if operator == ">>":
        return cmp > 0
    if operator == "<<":
        return cmp < 0
    if operator == "=":
        return cmp == 0
    return False


def resolve(depends_field: str, index: PackageIndex) -> ResolveResult:
    """Resolve Depends against *index* (host dpkg status or a clean image)."""
    missing: list[str] = []
    satisfied_by: dict[str, str] = {}
    for group in parse_depends(depends_field):
        picked = None
        for atom in group:
            pkg = index.get(atom.name)
            if pkg is None:
                continue
            if version_satisfies(pkg.version, atom.operator, atom.version):
                picked = atom
                satisfied_by[str(atom)] = f"{pkg.name}={pkg.version}"
                break
        if picked is None:
            missing.append(" | ".join(str(atom) for atom in group))
    return ResolveResult(ok=not missing, missing=missing, satisfied_by=satisfied_by)
