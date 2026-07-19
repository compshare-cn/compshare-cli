from __future__ import annotations

import argparse
import re
import tarfile
import zipfile
from pathlib import Path
from typing import Iterable, Optional

VERSION = r"[0-9]+\.[0-9]+\.[0-9]+(?:[a-zA-Z0-9.+-]*)?"


class VersionConsistencyError(RuntimeError):
    """Raised when release version sources disagree."""


def _extract(pattern: str, text: str, label: str, *, flags: int = 0) -> str:
    match = re.search(pattern, text, flags)
    if match is None:
        raise VersionConsistencyError(f"Unable to find the version in {label}.")
    return match.group(1)


def _assert_versions(expected: str, versions: Iterable[tuple[str, str]]) -> None:
    mismatches = [(label, value) for label, value in versions if value != expected]
    if mismatches:
        details = ", ".join(f"{label}={value}" for label, value in mismatches)
        raise VersionConsistencyError(f"Expected version {expected}; mismatched {details}.")


def check_source(root: Path) -> str:
    init_text = (root / "src/compshare_cli/__init__.py").read_text(encoding="utf-8")
    changelog_text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    pyproject_text = (root / "pyproject.toml").read_text(encoding="utf-8")

    runtime_version = _extract(
        rf'^__version__\s*=\s*["\']({VERSION})["\']',
        init_text,
        "compshare_cli.__version__",
        flags=re.MULTILINE,
    )
    changelog_version = _extract(
        rf"^##\s+({VERSION})\s*$",
        changelog_text,
        "CHANGELOG.md",
        flags=re.MULTILINE,
    )
    if not re.search(
        r'^dynamic\s*=\s*\[\s*["\']version["\']\s*\]\s*$', pyproject_text, re.MULTILINE
    ):
        raise VersionConsistencyError("pyproject.toml must declare project.version as dynamic.")
    if not re.search(
        r'^version\s*=\s*\{\s*attr\s*=\s*["\']compshare_cli\.__version__["\']\s*\}\s*$',
        pyproject_text,
        re.MULTILINE,
    ):
        raise VersionConsistencyError(
            "pyproject.toml must derive package metadata from compshare_cli.__version__."
        )
    _assert_versions(runtime_version, (("CHANGELOG.md", changelog_version),))
    return runtime_version


def _member(names: Iterable[str], suffix: str, artifact: Path) -> str:
    matches = [name for name in names if name.endswith(suffix)]
    if not matches:
        raise VersionConsistencyError(
            f"Expected {suffix} in {artifact.name}, but it was not found."
        )
    matches.sort(key=lambda name: (name.count("/"), len(name), name))
    if len(matches) > 1 and matches[0].count("/") == matches[1].count("/"):
        raise VersionConsistencyError(
            f"Expected one shallowest {suffix} in {artifact.name}, found {len(matches)}."
        )
    return matches[0]


def _metadata_version(text: str, label: str) -> str:
    return _extract(rf"^Version:\s*({VERSION})\s*$", text, label, flags=re.MULTILINE)


def _runtime_version(text: str, label: str) -> str:
    return _extract(
        rf'^__version__\s*=\s*["\']({VERSION})["\']',
        text,
        label,
        flags=re.MULTILINE,
    )


def _check_wheel(path: Path, expected: str) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        metadata_name = _member(names, ".dist-info/METADATA", path)
        init_name = _member(names, "compshare_cli/__init__.py", path)
        metadata_text = archive.read(metadata_name).decode("utf-8")
        init_text = archive.read(init_name).decode("utf-8")
    _assert_versions(
        expected,
        (
            (f"{path.name}:metadata", _metadata_version(metadata_text, path.name)),
            (f"{path.name}:__version__", _runtime_version(init_text, path.name)),
        ),
    )


def _check_sdist(path: Path, expected: str) -> None:
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
        metadata_name = _member(names, "/PKG-INFO", path)
        init_name = _member(names, "/src/compshare_cli/__init__.py", path)
        metadata = archive.extractfile(metadata_name)
        init = archive.extractfile(init_name)
        if metadata is None or init is None:
            raise VersionConsistencyError(f"Unable to read required files from {path.name}.")
        metadata_text = metadata.read().decode("utf-8")
        init_text = init.read().decode("utf-8")
    _assert_versions(
        expected,
        (
            (f"{path.name}:metadata", _metadata_version(metadata_text, path.name)),
            (f"{path.name}:__version__", _runtime_version(init_text, path.name)),
        ),
    )


def check_distributions(directory: Path, expected: str) -> None:
    wheels = sorted(directory.glob("*.whl"))
    sdists = sorted(directory.glob("*.tar.gz"))
    if not wheels or not sdists:
        raise VersionConsistencyError(
            f"Expected at least one wheel and one source distribution in {directory}."
        )
    for wheel in wheels:
        _check_wheel(wheel, expected)
    for sdist in sdists:
        _check_sdist(sdist, expected)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check release version consistency.")
    parser.add_argument("--tag", help="Release tag, for example v0.3.3.")
    parser.add_argument("--dist", type=Path, help="Directory containing built distributions.")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    expected = check_source(root)
    if args.tag and args.tag != f"v{expected}":
        raise VersionConsistencyError(
            f"Release tag {args.tag} does not match package version v{expected}."
        )
    if args.dist:
        check_distributions(args.dist, expected)
    print(f"Release version {expected} is consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
