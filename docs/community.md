# Community coordination

CloudImageForge is an open pipeline for people who ship Ubuntu cloud images
and debs together. Coordination happens here so jammy and noble do not
diverge silently.

## Where to talk

- **Issues** — broken apt sources, Archive dataset drift, hypervisor failures.
- **Pull requests** — code, fixtures, and README updates for new edge cases.
- **Discussions / mailing notes** — series planning (22.04 vs 24.04 pockets).

Label issues with `jammy`, `noble`, `apt`, `packaging`, or `bootcheck` so
the other series' testers can find them.

## Release captains

Each Ubuntu series needs someone to:

1. Confirm SimpleStreams still lists `disk1.img` / LXD squashfs for that series.
2. Re-run `scripts/sysadmin-check.sh` after Archive pocket copies.
3. Refuse a promote from staging if the fallback check reports
   `host_only_resolution`.

## Adding a cloud

`SUPPORTED_CLOUDS` in `cloudimageforge.releases` and `CLOUD_FTYPES` in
`cloudimageforge.images` must be updated together. Prefer official Ubuntu
SimpleStreams (`cloud-images.ubuntu.com`) over vendor-only catalogs.

## Security

Report issues that would publish a broken apt source or a package missing
Depends to the maintainers before opening a public issue if a running
guest could be left unable to `apt-get update`.
