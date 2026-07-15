from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from compshare_cli.i18n import tr

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
        for key, label in columns:
            justify = "right" if key in {"CPU", "GPU", "Size", "Price", "InstancePrice"} else "left"
            table.add_column(tr(label), justify=justify)
        count = 0
        for row in rows:
            count += 1
            table.add_row(*(self._cell(row.get(key), key=key) for key, _ in columns))
        if count:
            self.console.print(table)
        else:
            self.console.print(
                tr("No results. Try adjusting the filters or checking the selected region.")
            )

    def success(self, message: str, response: Dict[str, Any]) -> None:
        if self.json_output:
            self.data(response)
        else:
            self.console.print(f"[green]✓[/green] {message}")

    def details(
        self,
        title: str,
        fields: Sequence[Tuple[str, Any]],
        *,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Render a compact human detail card while preserving raw JSON output."""
        if self.json_output:
            self.data(response or {key: value for key, value in fields})
            return
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold cyan", no_wrap=True)
        grid.add_column()
        for label, value in fields:
            grid.add_row(tr(label), self._cell(value, key=label))
        self.console.print(Panel(grid, title=tr(title), border_style="blue"))

    def error(self, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        if self.json_output:
            payload: Dict[str, Any] = {"ok": False, "error": message}
            if details:
                payload["details"] = sanitized(details)
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        else:
            Console(stderr=True).print(f"[red]{tr('Error')}:[/red] {message}")

    @staticmethod
    def _cell(value: Any, *, key: Optional[str] = None) -> str:
        if value is None:
            return "-"
        if isinstance(value, bool):
            return tr("yes") if value else tr("no")
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if key and "time" in key.casefold() and isinstance(value, (int, float)):
            return datetime.fromtimestamp(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        if key and key.casefold() in {"state", "status"}:
            state = str(value)
            normalized = state.casefold()
            if normalized in {"running", "available", "success", "succeeded"}:
                return f"[green]{state}[/green]"
            if normalized in {"failed", "error", "terminated"}:
                return f"[red]{state}[/red]"
            if normalized not in {"stopped", "closed"}:
                return f"[yellow]{state}[/yellow]"
        return str(value)
