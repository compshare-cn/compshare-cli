import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from compshare_cli import __version__

ROOT = Path(__file__).resolve().parents[1] / "connector" / "compshare"


def _load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_workbuddy_connector_structure_and_versions() -> None:
    assert {path.name for path in ROOT.iterdir()} == {
        "connector-meta.json",
        "icon.svg",
        "mcp.json",
        "skills",
        "token-schema.json",
    }
    meta = _load("connector-meta.json")
    assert meta["type"] == "mcp"
    assert meta["auth_mode"] == "token"
    assert meta["source"] == "compshare"
    assert meta["version"] == __version__
    assert meta["minWorkbuddyVersion"] == "5.0.0"
    assert 2 <= len(meta["examples_zh"]) <= 5
    assert len(meta["examples_zh"]) == len(meta["examples_en"])

    skill = ROOT / "skills" / "compshare" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    version = re.search(r'(?m)^version:\s*["\']?([^"\'\n]+)', frontmatter)
    assert version is not None
    assert version.group(1) == __version__
    for field in ("name", "description", "description_zh", "description_en", "author"):
        assert re.search(rf"(?m)^{field}:\s*.+$", frontmatter)


def test_workbuddy_token_placeholders_match_schema() -> None:
    mcp = _load("mcp.json")
    schema = _load("token-schema.json")
    servers = mcp["mcpServers"]
    assert list(servers) == ["compshare"]
    server = servers["compshare"]
    assert server["type"] == "stdio"
    assert server["command"] == "uvx"
    assert f"compshare-cli[mcp]=={__version__}" in server["args"]
    assert server["runtime"] == {"type": "node", "version": "20"}

    fields = {field["key"]: field for field in schema["fields"]}
    placeholders = {
        match.group(1)
        for value in server["env"].values()
        if (match := re.fullmatch(r"\$\{([A-Z0-9_]+)\}", value))
    }
    assert placeholders == set(fields) == set(server["env"])
    assert fields["COMPSHARE_PUBLIC_KEY"]["required"] is True
    assert fields["COMPSHARE_PRIVATE_KEY"]["required"] is True
    assert fields["COMPSHARE_MINIMAX_API_KEY"]["required"] is False
    assert all(field["type"] == "password" for field in fields.values())


def test_workbuddy_icon_is_valid_svg() -> None:
    root = ET.parse(ROOT / "icon.svg").getroot()
    assert root.tag.endswith("svg")
    assert root.attrib["viewBox"] == "0 0 64 64"
