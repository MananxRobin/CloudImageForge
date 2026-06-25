from cloudimageforge.cli import main
from pathlib import Path
import json


def test_cli_apt_lint_catches_broken_source(tmp_path: Path, capsys):
    sources = tmp_path / "broken.list"
    sources.write_text("deb http://archive.ubuntu.com/ubuntu jamy main\n", encoding="utf-8")
    rc = main(["apt", "lint", str(sources), "--release", "jammy"])
    err = capsys.readouterr()
    assert rc == 1
    assert "error" in err.out


def test_cli_apt_render_noble(capsys):
    rc = main(["apt", "render", "--release", "noble"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Types: deb" in out
    assert "noble-security" in out


def test_cli_archive_query(capsys):
    rc = main(["archive", "query", "hello", "--release", "jammy"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "hello" in out


def test_cli_image_list_from_stream(capsys):
    stream = Path(__file__).resolve().parents[1] / "fixtures" / "simplestreams.json"
    rc = main(["image", "list", "--release", "jammy", "--stream", str(stream)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "jammy" in out
    assert "disk1.img" in out


def test_cli_stage_check_and_blocked_publish(tmp_path: Path, capsys):
    control = tmp_path / "control"
    control.write_text(
        "Package: ciforge-agent\nVersion: 0.1.0\nArchitecture: all\n"
        "Depends: liblocalfoo1\nDescription: host-only dep\n",
        encoding="utf-8",
    )
    status = tmp_path / "status"
    status.write_text(
        "Package: liblocalfoo1\nVersion: 1.0-1local\nStatus: install ok installed\n"
        "Architecture: amd64\n\n"
        "Package: python3\nVersion: 3.10.6-1~22.04.1\nStatus: install ok installed\n"
        "Architecture: amd64\n",
        encoding="utf-8",
    )
    staging = tmp_path / "staging"
    assert main(["stage", "add", "--control", str(control), "--staging", str(staging)]) == 0
    rc = main(
        [
            "stage",
            "check",
            "--release",
            "jammy",
            "--staging",
            str(staging),
            "--host-status",
            str(status),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "clean Ubuntu jammy image" in captured.err
    rc = main(["publish", "--staging", str(staging)])
    assert rc == 2
