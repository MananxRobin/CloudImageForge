from cloudimageforge.exceptions import InteropError
from cloudimageforge.validate import validate_interop
import pytest

NOBLE_ONLY = """Package: ciforge-py312
Version: 0.1.0
Architecture: all
Depends: python3 (>= 3.12)
Description: Requires a Python that jammy does not ship
"""

BOTH = """Package: ciforge-hello
Version: 0.1.0
Architecture: all
Depends: python3 (>= 3.10), libc6
Description: Installable on 22.04 and 24.04
"""


def test_interop_rejects_python312_on_jammy():
    report = validate_interop(NOBLE_ONLY, ("jammy", "noble"))
    assert report.ok is False
    jammy = next(item for item in report.results if item.release == "jammy")
    noble = next(item for item in report.results if item.release == "noble")
    assert jammy.ok is False
    assert noble.ok is True
    with pytest.raises(InteropError, match="jammy"):
        report.raise_for_status()


def test_interop_accepts_python310_floor():
    report = validate_interop(BOTH, ("jammy", "noble"))
    assert report.ok is True
