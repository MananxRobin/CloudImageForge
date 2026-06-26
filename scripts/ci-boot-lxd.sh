#!/bin/sh
# Launch a real Ubuntu cloud image in LXD and run apt-get update.
set -eu

ciforge bootcheck --release jammy --backend lxd
ciforge bootcheck --release noble --backend lxd

echo "==> broken apt source must fail inside the guest"
if ciforge bootcheck --release jammy --backend lxd --apt-source tests/fixtures/broken-apt.list; then
    echo "error: LXD guest accepted a broken apt source" >&2
    exit 1
fi

echo "LXD boot check passed"
