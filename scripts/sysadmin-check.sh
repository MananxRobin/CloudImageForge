#!/bin/sh
# System administration check: boot (or simulate) a clean Ubuntu cloud image
# and refuse release if apt sources are broken or a dependency only exists
# on the developer host.
set -eu

echo "==> render default apt sources for jammy (22.04) and noble (24.04)"
ciforge apt render --release jammy --format list | tee /tmp/ciforge-jammy.list
ciforge apt render --release noble --format deb822 | tee /tmp/ciforge-noble.sources
ciforge apt lint /tmp/ciforge-jammy.list --release jammy
ciforge apt lint /tmp/ciforge-noble.sources --release noble

echo "==> bootcheck must reject a broken apt source before release"
if ciforge bootcheck --release jammy --backend simulate --apt-source tests/fixtures/broken-apt.list; then
    echo "error: broken apt source was not caught" >&2
    exit 1
fi

echo "==> simulated clean-image boot with healthy sources"
ciforge bootcheck --release jammy --backend simulate
ciforge bootcheck --release noble --backend simulate

echo "==> pipeline for an Archive-satisfiable package"
work=$(mktemp -d)
ciforge pipeline examples/ciforge-hello --releases jammy,noble --dest "$work/dist"

echo "==> fallback check: liblocalfoo1 resolves on the host, not on a clean image"
staging=$(mktemp -d)
ciforge stage add --control examples/host-only-agent/DEBIAN/control --staging "$staging"
if ciforge stage check --release jammy --staging "$staging" --host-status tests/fixtures/host-dpkg-status; then
    echo "error: host-only dependency was not blocked" >&2
    exit 1
fi
if ciforge publish --staging "$staging"; then
    echo "error: direct publish succeeded; staging is mandatory" >&2
    exit 1
fi

echo "sysadmin check passed: broken apt sources and host-only deps cannot ship"
