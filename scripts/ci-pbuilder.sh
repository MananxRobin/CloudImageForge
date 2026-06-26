#!/bin/sh
# Create a noble pbuilder chroot from the Ubuntu Archive and build ciforge-hello.
set -eu

BASE="$HOME/.cache/cloudimageforge/pbuilder/noble-base.tgz"
mkdir -p "$(dirname "$BASE")"
if [ ! -f "$BASE" ]; then
    sudo pbuilder create --distribution noble --basetgz "$BASE"
fi

mkdir -p dist
ciforge package dsc examples/ciforge-hello-src --dest dist
dsc=$(ls dist/*.dsc | head -n 1)
sudo pbuilder build --distribution noble --basetgz "$BASE" --buildresult "$(pwd)/dist" "$dsc"
ls -l dist/*.deb
echo "pbuilder build passed"
