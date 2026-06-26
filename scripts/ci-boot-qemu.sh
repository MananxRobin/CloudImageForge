#!/bin/sh
# Pull an Ubuntu cloud image and boot it in QEMU with a NoCloud apt seed.
set -eu

if [ -e /dev/kvm ]; then
    sudo chmod 666 /dev/kvm || true
fi

timeout_s=900
if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    echo "KVM usable"
    timeout_s=300
else
    echo "No usable KVM; using TCG"
fi

echo "==> pull jammy qemu cloud image"
img=$(ciforge image pull --release jammy --cloud qemu | awk -F' -> ' '{print $NF}')
echo "image=$img"

echo "==> boot with healthy apt sources"
ciforge bootcheck --release jammy --backend qemu --image "$img" --no-pull --timeout "$timeout_s"

echo "==> broken apt source must fail inside the guest"
if ciforge bootcheck --release jammy --backend qemu --image "$img" --no-pull --timeout "$timeout_s" \
    --apt-source tests/fixtures/broken-apt.list; then
    echo "error: QEMU guest accepted a broken apt source" >&2
    exit 1
fi

echo "QEMU boot check passed"
