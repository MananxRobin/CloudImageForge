# Architecture

```
                  Ubuntu Archive (Launchpad API + snapshot)
                                    |
                                    v
  SimpleStreams  -->  image catalog (jammy/noble, qemu/lxd/aws/azure/gcp)
                                    |
  debian/control -->  dpkg-deb / sbuild / pbuilder
                                    |
                                    v
                         staging archive (local pocket)
                                    |
              +---------------------+---------------------+
              |                                           |
              v                                           v
     fallback check                              boot check
     host dpkg status vs                         LXD / QEMU / simulate
     clean image + Archive                       apt-get update
              |                                           |
              +---------------------+---------------------+
                                    |
                                    v
                              publish (promote)
```

## Units

| Module | Responsibility |
| ------ | ---------------- |
| `releases` | jammy (22.04) and noble (24.04) only |
| `apt` | render/lint `sources.list` and DEB822 |
| `archive` | Launchpad `getPublishedSources` + bundled dataset |
| `images` | SimpleStreams product files |
| `depends` | Debian Depends parser and solver |
| `packaging` | `dpkg-deb`, `sbuild`, `pbuilder` |
| `staging` | Launchpad-style pocket + fallback check |
| `validate` | installability on every requested series |
| `bootcheck` | LXD/QEMU/simulate guest apt health |
| `pipeline` | build → validate → stage → boot → publish |

## Clean image model

A clean cloud image is not an empty chroot. It has Essential packages plus
`apt`, `python3-minimal`, `ubuntu-keyring`, and `gpgv`, then the Ubuntu
Archive. It does **not** have whatever happened to be installed on the
developer host. That difference is the whole point of staging.
