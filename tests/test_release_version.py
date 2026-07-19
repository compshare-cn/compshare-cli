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
