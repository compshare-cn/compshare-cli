import re
from pathlib import Path

import pytest

from compshare_cli.actions import (
    COMING_SOON_ACTIONS,
    IMAGE_ACTIONS,
    INSTANCE_ACTIONS,
    PUBLIC_ACTIONS,
    STORAGE_ACTIONS,
    TEAM_ACTIONS,
    UNAVAILABLE_ACTIONS,
)


def test_public_action_counts() -> None:
    assert len(INSTANCE_ACTIONS) == 27
    assert len(IMAGE_ACTIONS) == 16
    assert len(STORAGE_ACTIONS) == 8
    assert len(TEAM_ACTIONS) == 17
    assert len(PUBLIC_ACTIONS) == 68


def test_every_available_public_action_is_wired_into_a_command() -> None:
    command_dir = Path(__file__).parents[1] / "src" / "compshare_cli" / "commands"
    source = "\n".join(path.read_text(encoding="utf-8") for path in command_dir.glob("*.py"))
    missing = {
        action
        for action in PUBLIC_ACTIONS - COMING_SOON_ACTIONS - UNAVAILABLE_ACTIONS
        if f'"{action}"' not in source
    }
    assert missing == set()


def test_coming_soon_actions_are_public() -> None:
    assert COMING_SOON_ACTIONS <= PUBLIC_ACTIONS


@pytest.mark.parametrize(
    ("directory", "expected"),
    [
        ("instance", INSTANCE_ACTIONS),
        ("image", IMAGE_ACTIONS),
        ("data", STORAGE_ACTIONS),
        ("team", TEAM_ACTIONS),
    ],
)
def test_action_registry_matches_local_public_docs(directory: str, expected: frozenset) -> None:
    docs = Path(__file__).parents[2] / "compshare-docs" / "pages" / "gpus" / directory
    if not docs.exists():
        pytest.skip("sibling compshare-docs checkout is not available")
    documented = set()
    for path in docs.glob("*.md"):
        match = re.search(r"^#\s+([A-Za-z][A-Za-z0-9]+)\s+", path.read_text(encoding="utf-8"), re.M)
        if match and match.group(1) != "US3CLI":
            documented.add(match.group(1))
    unavailable = UNAVAILABLE_ACTIONS - PUBLIC_ACTIONS if directory == "image" else set()
    documented_available = documented - set(unavailable)
    # Production can gain actions before the public docs checkout is updated, but every
    # documented, available action must remain represented in the CLI registry.
    assert documented_available == set(expected) & documented
