from __future__ import annotations

import json
import sys
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from rich.console import Console
from rich.table import Table

SENSITIVE_KEYS = {
    "privatekey",
    "private_key",
}


def sanitized(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***" if key.casefold() in SENSITIVE_KEYS else sanitized(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitized(item) for item in value]
    return value


class Renderer:
    def __init__(self, json_output: bool) -> None:
        self.json_output = json_output
        self.console = Console()

    def data(
        self,
        response: Dict[str, Any],
        *,
        rows: Optional[Iterable[Dict[str, Any]]] = None,
        columns: Optional[Sequence[Tuple[str, str]]] = None,
    ) -> None:
        safe = sanitized(response)
        if self.json_output:
            sys.stdout.write(json.dumps(safe, ensure_ascii=False, separators=(",", ":")) + "\n")
            return
        if rows is not None and columns:
            self.table(rows, columns)
            return
        self.console.print_json(json.dumps(safe, ensure_ascii=False, default=str))

    def table(
        self,
        rows: Iterable[Dict[str, Any]],
        columns: Sequence[Tuple[str, str]],
    ) -> None:
        table = Table(show_header=True, header_style="bold")
        for _, label in columns:
            table.add_column(label)
        count = 0
        for row in rows:
            count += 1
            table.add_row(*(self._cell(row.get(key)) for key, _ in columns))
        if count:
            self.console.print(table)
        else:
            self.console.print("No results.")

    def success(self, message: str, response: Dict[str, Any]) -> None:
        if self.json_output:
            self.data(response)
        else:
            self.console.print(f"[green]✓[/green] {message}")

    def error(self, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        if self.json_output:
            payload: Dict[str, Any] = {"ok": False, "error": message}
            if details:
                payload["details"] = sanitized(details)
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        else:
            Console(stderr=True).print(f"[red]Error:[/red] {message}")

    @staticmethod
    def _cell(value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return str(value)
