#!/bin/sh
# Build a native Debian source package suitable for dput / a Launchpad PPA.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"

if ! command -v dpkg-buildpackage >/dev/null 2>&1; then
    echo "dpkg-buildpackage is required (apt install dpkg-dev debhelper dh-python)" >&2
    exit 1
fi

outdir="${1:-dist}"
mkdir -p "$outdir"

dpkg-buildpackage -S -us -uc -d

mv -f ../cloudimageforge_*.dsc ../cloudimageforge_*.tar.* ../cloudimageforge_*.changes "$outdir/" 2>/dev/null || true
ls -l "$outdir"/cloudimageforge_*
echo "Debian source package written to $outdir"
