"""ciforge command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cloudimageforge import __version__
from cloudimageforge.apt import default_cloud_sources, lint_sources
from cloudimageforge.archive import UbuntuArchiveClient
from cloudimageforge.bootcheck import bootcheck
from cloudimageforge.dpkgstatus import load_dpkg_status
from cloudimageforge.exceptions import CloudImageForgeError
from cloudimageforge.images import CloudImageCatalog
from cloudimageforge.packaging import build_package
from cloudimageforge.pipeline import run_pipeline
from cloudimageforge.releases import get_release, parse_release_list
from cloudimageforge.staging import StagingArchive
from cloudimageforge.validate import validate_interop


def _print(msg: str) -> None:
    sys.stdout.write(msg if msg.endswith("\n") else msg + "\n")


def cmd_image_list(args: argparse.Namespace) -> int:
    catalog = CloudImageCatalog(products=_load_json(args.stream) if args.stream else None)
    images = catalog.list_images(args.release, cloud=args.cloud, arch=args.arch)
    if not images:
        _print("No images matched.")
        return 1
    for image in images[: args.limit]:
        _print(
            f"{image.release} {image.version} {image.arch} {image.cloud} "
            f"serial={image.serial} {image.ftype} {image.path}"
        )
    return 0


def cmd_image_latest(args: argparse.Namespace) -> int:
    catalog = CloudImageCatalog(products=_load_json(args.stream) if args.stream else None)
    image = catalog.latest(args.release, cloud=args.cloud, arch=args.arch)
    _print(json.dumps(image.__dict__, indent=2))
    return 0


def cmd_apt_render(args: argparse.Namespace) -> int:
    rel = get_release(args.release)
    components = tuple(item.strip() for item in args.components.split(",") if item.strip())
    pockets = tuple(item.strip() for item in args.pockets.split(",") if item.strip())
    sources = default_cloud_sources(rel, components=components, pockets=pockets)
    _print(sources.render(args.format))
    return 0


def cmd_apt_lint(args: argparse.Namespace) -> int:
    text = Path(args.path).read_text(encoding="utf-8") if args.path != "-" else sys.stdin.read()
    issues = lint_sources(text, args.release)
    if not issues:
        _print("apt sources are healthy.")
        return 0
    for issue in issues:
        loc = f"stanza {issue.line}: " if issue.line else ""
        _print(f"{issue.severity}: {issue.code}: {loc}{issue.message}")
    return 1 if any(issue.severity == "error" for issue in issues) else 0


def cmd_archive_query(args: argparse.Namespace) -> int:
    client = UbuntuArchiveClient()
    if args.live:
        entries = client.get_published_sources(args.package, args.release, pocket=args.pocket)
        if not entries:
            _print(f"No published sources for {args.package} on {args.release}.")
            return 1
        for entry in entries:
            _print(
                f"{entry.get('source_package_name')} "
                f"{entry.get('source_package_version')} "
                f"{entry.get('component_name')} {entry.get('pocket')} {entry.get('status')}"
            )
        return 0
    pkg = client.query_binary(args.package, args.release)
    _print(f"{pkg.name} {pkg.version} component={pkg.component} depends={pkg.depends or '-'}")
    return 0


def cmd_package_build(args: argparse.Namespace) -> int:
    result = build_package(
        Path(args.path),
        Path(args.dest),
        backend=args.backend,
        release=args.release,
        dsc=Path(args.dsc) if args.dsc else None,
        dry_run=args.dry_run,
    )
    _print(f"backend={result.backend} artifact={result.artifact}")
    _print("command: " + " ".join(result.command))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    control = Path(args.control).read_text(encoding="utf-8")
    report = validate_interop(control, parse_release_list(args.releases))
    for item in report.results:
        status = "ok" if item.ok else "FAIL"
        missing = f" missing={item.missing}" if item.missing else ""
        _print(f"{item.release} ({item.version}): {status}{missing}")
    report.raise_for_status()
    return 0


def _staging(args: argparse.Namespace) -> StagingArchive:
    return StagingArchive(root=Path(args.staging))


def cmd_stage_add(args: argparse.Namespace) -> int:
    archive = _staging(args)
    control = Path(args.control).read_text(encoding="utf-8")
    if args.deb:
        archive.add_deb(Path(args.deb), control)
    else:
        archive.add_from_control(control)
    _print(f"staged {archive.staged[-1].name} {archive.staged[-1].version} in {archive.root}")
    return 0


def cmd_stage_check(args: argparse.Namespace) -> int:
    archive = _staging(args)
    host = None
    if args.host_status:
        host = load_dpkg_status(Path(args.host_status), get_release(args.release).series)
    report = archive.check(args.release, host=host)
    _print(report.message)
    if report.missing_on_clean:
        _print("missing on clean image: " + ", ".join(report.missing_on_clean))
    report.raise_for_status()
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    archive = _staging(args)
    if args.release:
        archive.check(args.release)
    path = archive.publish()
    _print(f"published from staging: {path}")
    return 0


def cmd_bootcheck(args: argparse.Namespace) -> int:
    sources = Path(args.apt_source).read_text(encoding="utf-8") if args.apt_source else None
    staging = StagingArchive(root=Path(args.staging)) if args.staging else None
    if staging and args.control:
        staging.add_from_control(Path(args.control).read_text(encoding="utf-8"))
    report = bootcheck(
        args.release,
        backend=args.backend,
        sources=sources,
        staging=staging,
        image=Path(args.image) if args.image else None,
        dry_run=args.dry_run,
    )
    _print(f"backend={report.backend} release={report.release} ok={report.ok}")
    _print(report.log)
    for err in report.apt_errors:
        _print("apt error: " + err)
    report.raise_for_status()
    return 0


def cmd_pipeline(args: argparse.Namespace) -> int:
    dest = Path(args.dest)
    staging = Path(args.staging) if args.staging else dest / "staging"
    result = run_pipeline(
        Path(args.path),
        releases=parse_release_list(args.releases),
        backend=args.backend,
        dest=dest,
        staging_root=staging,
        boot_backend=args.boot_backend,
    )
    _print(f"built {result.build.artifact}")
    _print(f"boot {result.boot.backend} ok={result.boot.ok}")
    _print(f"published {result.published}")
    return 0


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ciforge",
        description=(
            "Create and manage Ubuntu 22.04/24.04 cloud images, apt sources, "
            "and deb packages using the Ubuntu Archive."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    image = sub.add_parser("image", help="Ubuntu cloud image catalog (SimpleStreams)")
    image_sub = image.add_subparsers(dest="image_command", required=True)
    il = image_sub.add_parser("list", help="List cloud images for a release")
    il.add_argument("--release", default="noble")
    il.add_argument("--cloud", default="qemu")
    il.add_argument("--arch", default="amd64")
    il.add_argument("--limit", type=int, default=10)
    il.add_argument("--stream", help="Local SimpleStreams JSON instead of cloud-images.ubuntu.com")
    il.set_defaults(func=cmd_image_list)
    ilat = image_sub.add_parser("latest", help="Show the newest image serial")
    ilat.add_argument("--release", default="noble")
    ilat.add_argument("--cloud", default="qemu")
    ilat.add_argument("--arch", default="amd64")
    ilat.add_argument("--stream")
    ilat.set_defaults(func=cmd_image_latest)

    apt = sub.add_parser("apt", help="Configure and lint apt sources for cloud images")
    apt_sub = apt.add_subparsers(dest="apt_command", required=True)
    ar = apt_sub.add_parser("render", help="Write default cloud-image apt sources")
    ar.add_argument("--release", default="noble")
    ar.add_argument("--components", default="main,universe")
    ar.add_argument("--pockets", default="release,updates,security")
    ar.add_argument("--format", choices=("list", "deb822"), default=None)
    ar.set_defaults(func=cmd_apt_render)
    al = apt_sub.add_parser("lint", help="Catch a broken apt source before release")
    al.add_argument("path")
    al.add_argument("--release", default="noble")
    al.set_defaults(func=cmd_apt_lint)

    archive = sub.add_parser("archive", help="Query the Ubuntu Archive / Launchpad API dataset")
    archive_sub = archive.add_subparsers(dest="archive_command", required=True)
    aq = archive_sub.add_parser("query", help="Look up a binary or published source")
    aq.add_argument("package")
    aq.add_argument("--release", default="jammy")
    aq.add_argument("--pocket", default="Release")
    aq.add_argument("--live", action="store_true", help="Call Launchpad getPublishedSources")
    aq.set_defaults(func=cmd_archive_query)

    pkg = sub.add_parser("package", help="Build debs with dpkg-deb, sbuild, or pbuilder")
    pkg_sub = pkg.add_subparsers(dest="package_command", required=True)
    pb = pkg_sub.add_parser("build", help="Build a binary package")
    pb.add_argument("path", help="Directory containing DEBIAN/control")
    pb.add_argument("--backend", default="dpkg-deb", choices=("dpkg-deb", "sbuild", "pbuilder"))
    pb.add_argument("--release", default="noble")
    pb.add_argument("--dest", default="dist")
    pb.add_argument("--dsc")
    pb.add_argument("--dry-run", action="store_true")
    pb.set_defaults(func=cmd_package_build)

    val = sub.add_parser("validate", help="Check installability on jammy and noble")
    val.add_argument("--control", required=True)
    val.add_argument("--releases", default="jammy,noble")
    val.set_defaults(func=cmd_validate)

    stage = sub.add_parser("stage", help="Launchpad-style staging archive")
    stage_sub = stage.add_subparsers(dest="stage_command", required=True)
    sa = stage_sub.add_parser("add", help="Add a package to staging")
    sa.add_argument("--control", required=True)
    sa.add_argument("--deb")
    sa.add_argument("--staging", default=".ciforge/staging")
    sa.set_defaults(func=cmd_stage_add)
    sc = stage_sub.add_parser("check", help="Fallback check on a clean image before release")
    sc.add_argument("--release", default="jammy")
    sc.add_argument("--staging", default=".ciforge/staging")
    sc.add_argument("--host-status", help="dpkg status of the developer host")
    sc.set_defaults(func=cmd_stage_check)

    pub = sub.add_parser("publish", help="Promote staging only after the fallback check")
    pub.add_argument("--staging", default=".ciforge/staging")
    pub.add_argument("--release")
    pub.set_defaults(func=cmd_publish)

    boot = sub.add_parser("bootcheck", help="Boot LXD/QEMU (or simulate) and test apt")
    boot.add_argument("--release", default="jammy")
    boot.add_argument("--backend", default="simulate", choices=("simulate", "lxd", "qemu"))
    boot.add_argument("--apt-source")
    boot.add_argument("--staging")
    boot.add_argument("--control")
    boot.add_argument("--image")
    boot.add_argument("--dry-run", action="store_true")
    boot.set_defaults(func=cmd_bootcheck)

    pipe = sub.add_parser("pipeline", help="Build, stage, boot-check, and publish")
    pipe.add_argument("path")
    pipe.add_argument("--releases", default="jammy,noble")
    pipe.add_argument("--backend", default="dpkg-deb")
    pipe.add_argument("--boot-backend", default="simulate")
    pipe.add_argument("--dest", default="dist")
    pipe.add_argument("--staging")
    pipe.set_defaults(func=cmd_pipeline)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except CloudImageForgeError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
