# Contributing to CloudImageForge

This repository is how we coordinate Ubuntu 22.04 (jammy) and 24.04 (noble)
cloud image work, apt source changes, and deb packaging.

## Release matrix

Every change that affects a binary package must be validated on **both**
series before it can leave staging:

| Series | Version | Apt format | Cloud images |
| ------ | ------- | ---------- | ------------ |
| jammy  | 22.04   | `sources.list` | qemu, lxd, aws, azure, gcp |
| noble  | 24.04   | DEB822 `ubuntu.sources` | qemu, lxd, aws, azure, gcp |

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
ciforge validate --control debian/control --releases jammy,noble
ciforge bootcheck --release jammy --backend simulate
```

## Staging is mandatory

Do not add a `publish` path that skips `ciforge stage check`. The fallback
check exists because a dependency resolved on a developer host and failed on
a clean cloud image. Document new instances of that failure in
`docs/staging.md` and add a fixture under `tests/fixtures/`.

## Pull requests

1. One concern per PR (apt sources, Archive dataset, packaging backend, or CI).
2. Unit tests for the resolver and apt linter must stay green without QEMU.
3. Functional tests must show either a successful promote from staging or a
   deliberate `PublishBlockedError`.
4. If you touch apt sources, include a `ciforge apt lint` snippet in the PR.

## Ubuntu Archive dataset

Offline resolution uses `src/cloudimageforge/data/archive_snapshot.json`,
derived from Launchpad `getPublishedSources` / binary metadata. When you
refresh versions, keep jammy and noble in the same commit so interoperability
tests stay honest.

Live API access:

```bash
ciforge archive query hello --release jammy --live
```

## Hypervisor tests

CI boots real guests:

- LXD: `lxc launch ubuntu:22.04` / `ubuntu:24.04`, injects apt sources, `apt-get update`
- QEMU: `ciforge image pull` of the jammy cloud image, NoCloud seed, serial marker

Locally:

```bash
ciforge bootcheck --release jammy --backend lxd
ciforge image pull --release jammy --cloud qemu
ciforge bootcheck --release jammy --backend qemu
```

## Code of conduct

Be precise, assume good intent, and keep discussion on the package and the
image — not the person. See [docs/community.md](docs/community.md).
