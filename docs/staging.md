# Staging fallback check

## What happened

A binary built on a developer workstation installed with `apt-get install
./foo.deb`. The same binary on a freshly booted Ubuntu 22.04 cloud image
failed to configure. `apt` on the host had already satisfied `liblocalfoo1`
(a local `.deb` never copied to the Archive). The clean image only saw
`archive.ubuntu.com` / `security.ubuntu.com` and could not install it.

A second failure mode showed up in the same investigation: a typo'd suite
(`jamy` instead of `jammy`) in an extra apt source. `apt-get update` never
ran on the host because the source was added only in the image template.

## What we do instead of direct publish

1. Copy the binary into a staging pocket (`ciforge stage add`).
2. Resolve Depends twice:
   - **Host index** — `dpkg` status from the workstation (`--host-status`).
   - **Clean index** — Essential packages + Ubuntu Archive snapshot for the
     target series.
3. If the host succeeds and the clean image fails, raise
   `StagingRequiredError` with reason `host_only_resolution` and **refuse
   publish**.
4. Boot LXD/QEMU (or the CI simulator) with the image apt sources and fail
   the job on `suite-mismatch`, `security-mirror`, or parse errors.

## Fallback check before release

`scripts/sysadmin-check.sh` is the gate. It must fail on:

- `tests/fixtures/broken-apt.list` (suite `jamy`)
- `examples/host-only-agent` plus `tests/fixtures/host-dpkg-status`

and must pass on `examples/ciforge-hello` for jammy and noble.

There is no supported flag to skip this check. Direct publish after a local
`apt-get install` is how the original breakage escaped.
