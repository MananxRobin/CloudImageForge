from cloudimageforge.depends import (
    BinaryPackage,
    PackageIndex,
    compare_versions,
    parse_depends,
    resolve,
    version_satisfies,
)


def test_parse_depends_and_alternatives():
    groups = parse_depends("python3 (>= 3.10), libc6 | libc6-udeb")
    assert groups[0][0].name == "python3"
    assert groups[0][0].operator == ">="
    assert groups[1][0].name == "libc6"
    assert groups[1][1].name == "libc6-udeb"


def test_python312_does_not_satisfy_jammy_python310():
    assert version_satisfies("3.10.6-1~22.04.1", ">=", "3.12") is False
    assert version_satisfies("3.12.3-0ubuntu2", ">=", "3.12") is True
    assert compare_versions("3.10.6", "3.12") < 0


def test_resolve_missing_package():
    index = PackageIndex(release="jammy")
    index.add(BinaryPackage("libc6", "2.35"))
    result = resolve("liblocalfoo1, libc6", index)
    assert result.ok is False
    assert result.missing == ["liblocalfoo1"]
