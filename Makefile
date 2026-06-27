PYTHON ?= python3
export PYTHONPATH := src

.PHONY: test functional sysadmin package

test:
	$(PYTHON) -m pytest tests/unit tests/functional

functional:
	$(PYTHON) -m pytest tests/functional -m functional

sysadmin:
	bash scripts/sysadmin-check.sh

package:
	$(PYTHON) -m cloudimageforge package build examples/ciforge-hello --dest dist
