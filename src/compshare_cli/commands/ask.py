from __future__ import annotations

from typing import Any, Dict, List

from compshare_cli.output import Renderer
from compshare_cli.qa import ask_question
from compshare_cli.runtime import Runtime


def _source_lines(response: Dict[str, Any]) -> str:
    lines: List[str] = []
    for index, raw in enumerate(response.get("citations") or [], start=1):
        if not isinstance(raw, dict):
            continue
        number = raw.get("number") or index
        title = raw.get("title") or raw.get("document_id")
        if title:
            lines.append(f"[{number}] {title}")
    return "\n".join(lines)


def run(state: Runtime, question: str) -> None:
    response = ask_question(question)
    Renderer(state.json_output, state.show_sensitive).details(
        "Answer",
        [
            ("ANSWER", response["answer"]),
            ("SOURCES", _source_lines(response) or None),
        ],
        response=response,
    )
