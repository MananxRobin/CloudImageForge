# CloudImageForge

[![CI](https://github.com/MananxRobin/CloudImageForge/actions/workflows/ci.yml/badge.svg)](https://github.com/MananxRobin/CloudImageForge/actions)

Python on Linux tool for Ubuntu 22.04 (jammy) and 24.04 (noble) cloud images:
apt sources, Debian packaging (`dpkg-deb`, `sbuild`, `pbuilder`), and
installability checks against the Ubuntu Archive (Launchpad
`getPublishedSources`) dataset.

Packages are **never published directly**. They go through a Launchpad-style
staging archive. A fallback check boots a clean image (LXD or QEMU; CI uses
the same resolver a guest would) so an apt dependency that resolved on a
developer laptop cannot fail on a fresh cloud image after release.

## Why staging (read this before you publish)

An apt dependency **resolved locally but failed on a clean image**.

The developer workstation already had `liblocalfoo1` installed from a local
build. `apt-get install ./ciforge-agent.deb` succeeded. The same binary on a
fresh Ubuntu 22.04 cloud image failed: `liblocalfoo1` is not in the Ubuntu
Archive, and the image's apt sources do not include the laptop.

Direct publish would have shipped that breakage to every public-cloud guest.
CloudImageForge therefore:

1. Builds the deb (`dpkg-deb`, or `sbuild`/`pbuilder` against the target series).
2. Lands it in a **staging** pocket (Launchpad PPA / proposed-style).
3. Runs the **fallback check** against a clean jammy/noble package index
   (Essential packages + Archive), not against the host `dpkg` status.
4. Boots the image (**LXD** or **QEMU**) and runs `apt-get update` so a
   broken apt source is caught before release.
5. Promotes from staging only when both checks pass.

Reproduce the edge case:

```bash
ciforge stage add --control examples/host-only-agent/DEBIAN/control
ciforge stage check --release jammy --host-status tests/fixtures/host-dpkg-status
# error: Dependencies [liblocalfoo1] resolved on the local host but are not
# installable on a clean Ubuntu jammy image.
ciforge publish   # refused
```

A known-broken apt source is rejected the same way:

```bash
ciforge bootcheck --release jammy --backend simulate \
    --apt-source tests/fixtures/broken-apt.list
```

## Install

On Ubuntu, build the native Debian package (Launchpad / `dput`) and install it:

```bash
sudo apt install dpkg-dev debhelper dh-python python3-all python3-setuptools python3-pytest
bash scripts/build-source-package.sh dist   # .dsc + .tar.xz
dpkg-buildpackage -us -uc                   # cloudimageforge_0.1.0_all.deb
sudo apt install ../cloudimageforge_0.1.0_all.deb
ciforge --help
```

From a git checkout, run the tree directly:

```bash
export PYTHONPATH=src PATH="$PWD/bin:$PATH"
sudo apt install python3-pytest
ciforge --help
python3 -m pytest tests/unit tests/functional
```

Run `autopkgtest` via `debian/tests/`.

## Pipeline

```bash
# Catalog and pull Ubuntu cloud images (SimpleStreams)
ciforge image list --release jammy --cloud qemu
ciforge image pull --release jammy --cloud qemu
ciforge image list --release noble --cloud lxd

# Apt sources as a clean cloud image would see them
ciforge apt render --release jammy --format list
ciforge apt render --release noble --format deb822
ciforge apt lint path/to/sources --release noble

# Ubuntu Archive dataset (offline snapshot) or live Launchpad API
ciforge archive query python3 --release jammy
ciforge archive query hello --release noble --live

# Build
ciforge package build examples/ciforge-hello --backend dpkg-deb
ciforge package dsc examples/ciforge-hello-src --dest dist
ciforge package build examples/ciforge-hello-src --backend sbuild --release noble
ciforge package build examples/ciforge-hello-src --backend pbuilder --release noble --dry-run

# Interoperability across 22.04 and 24.04
ciforge validate --control examples/ciforge-hello/DEBIAN/control --releases jammy,noble

# Stage, fallback-check, boot, publish
ciforge pipeline examples/ciforge-hello --releases jammy,noble
ciforge bootcheck --release jammy --backend lxd
ciforge bootcheck --release jammy --backend qemu
ciforge bootcheck --release jammy --backend lxd --apt-source tests/fixtures/broken-apt.list
```

`sbuild --chroot-mode=unshare` and `pbuilder` build against chroots populated from the Ubuntu Archive. `dpkg-deb` is the local binary backend. If `dpkg-deb` is not installed, CloudImageForge writes a `.deb` with the same `ar` + `control.tar.gz` + `data.tar.gz` layout.

Live boot checks pull a jammy/noble image, inject apt sources (cloud-init NoCloud for QEMU, `lxc exec tee` for LXD), and run `apt-get update` in the guest. A typo'd suite such as `jamy` fails inside that guest before release.

## Tests and CI

| Job | What it runs |
| --- | --- |
| unit | `pytest tests/unit` on Ubuntu 22.04 / Python 3.10 and 24.04 / 3.12 |
| functional | end-to-end build → stage → bootcheck → publish |
| autopkgtest | `debian/tests/smoke` and `debian/tests/staging-fallback` |
| sysadmin-check | `scripts/sysadmin-check.sh`: resolver fallback + apt lint |
| boot-lxd | real `lxc launch ubuntu:22.04` / `24.04`, inject sources, `apt-get update` |
| boot-qemu | `ciforge image pull` + QEMU NoCloud seed + serial `CIFORGE_BOOTCHECK` |
| sbuild | `sbuild --chroot-mode=unshare -d noble` on `examples/ciforge-hello-src` |
| pbuilder | `pbuilder create/build` noble chroot from the Ubuntu Archive |
| debian-source | native `dpkg-buildpackage -S` (`.dsc` for Launchpad) |

```bash
python3 -m pytest tests/unit tests/functional
bash scripts/sysadmin-check.sh
bash scripts/ci-boot-lxd.sh    # requires LXD
bash scripts/ci-boot-qemu.sh   # requires qemu-system-x86
```

## Community

This repository is the coordination point for image and packaging work
across jammy and noble. See [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/community.md](docs/community.md) for the release matrix, how to
propose Archive dataset updates, and how we review staging failures.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE) and [debian/copyright](debian/copyright).
