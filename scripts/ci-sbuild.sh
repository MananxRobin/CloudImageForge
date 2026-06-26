#!/bin/sh
# Build ciforge-hello with sbuild unshare against a noble Ubuntu Archive chroot.
set -eu

if ! grep -q "^${USER}:" /etc/subuid 2>/dev/null; then
    echo "${USER}:100000:65536" | sudo tee -a /etc/subuid
    echo "${USER}:100000:65536" | sudo tee -a /etc/subgid
fi

mkdir -p "$HOME/.cache/sbuild" dist
chroot="$HOME/.cache/sbuild/noble-amd64.tar.zst"
if [ ! -f "$chroot" ]; then
    echo "==> mmdebstrap noble buildd chroot (main+universe)"
    mmdebstrap --verbose --variant=buildd \
        --components=main,universe \
        --include=ca-certificates,dumb-init,dose-distcheck \
        noble "$chroot"
fi

ciforge package dsc examples/ciforge-hello-src --dest dist
dscname=$(basename "$(ls dist/*.dsc | head -n 1)")

echo "==> sbuild --chroot-mode=unshare -d noble"
(
    cd dist
    sbuild --chroot-mode=unshare --dist=noble --no-run-lintian --nolog "$dscname"
)

ls -l dist/*.deb
echo "sbuild unshare build passed"
