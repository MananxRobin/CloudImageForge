PYTHON ?= python3

.PHONY: install test functional sysadmin package

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest tests/unit tests/functional

functional:
	$(PYTHON) -m pytest tests/functional -m functional

sysadmin:
	bash scripts/sysadmin-check.sh

package:
	$(PYTHON) -m cloudimageforge package build examples/ciforge-hello --dest dist
