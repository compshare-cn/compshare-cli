import json
import shutil
import subprocess
import sys
from pathlib import Path

from compshare_cli import __version__


def test_release_version_sources_are_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts/check_release_version.py")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert f"Release version {__version__} is consistent." in completed.stdout


def test_release_version_rejects_stale_plugin(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    for name in (
        "scripts/check_release_version.py",
        "src/compshare_cli/__init__.py",
        "CHANGELOG.md",
        "pyproject.toml",
        "plugin.json",
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    plugin_path = tmp_path / "plugin.json"
    plugin = json.loads(plugin_path.read_text(encoding="utf-8"))
    plugin["version"] = "0.0.0"
    plugin_path.write_text(json.dumps(plugin), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(tmp_path / "scripts/check_release_version.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "plugin.json=0.0.0" in completed.stderr
