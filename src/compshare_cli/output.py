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
    "authorization",
    "command",
    "cookie",
    "eip",
    "filebrowserpassword",
    "hostip",
    "ip",
    "ipaddress",
    "ipaddr",
    "ipv4",
    "ipv6",
    "logincommand",
    "password",
    "privateip",
    "privatekey",
    "publicip",
    "secret",
    "secretkey",
    "ssh",
    "sshcommand",
    "sshlogincommand",
    "token",
    "url",
}


def _normalized_key(key: Any) -> str:
    return "".join(character for character in str(key).casefold() if character.isalnum())


def _is_sensitive_key(key: Any) -> bool:
    normalized = _normalized_key(key)
    return (
        normalized in SENSITIVE_KEYS
        or normalized.endswith("password")
        or normalized.endswith("secret")
        or normalized.endswith("token")
        or normalized.endswith("url")
    )


def sanitized(value: Any, *, show_sensitive: bool = False) -> Any:
    if show_sensitive:
        return value
    if isinstance(value, dict):
        return {
            key: "***" if _is_sensitive_key(key) else sanitized(item) for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitized(item) for item in value]
    return value


def _write_json(payload: Dict[str, Any]) -> None:
    """Write one UTF-8 JSON document independently of the console code page."""
    document = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    stream = sys.stdout
    binary = getattr(stream, "buffer", None)
    if binary is not None:
        stream.flush()
        binary.write(document.encode("utf-8"))
        binary.flush()
        return
    # String-only test/application streams have no byte encoding contract. Escaping
    # non-ASCII keeps this fallback valid UTF-8 under every ASCII-compatible encoding.
    stream.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    stream.flush()


class Renderer:
    def __init__(self, json_output: bool, show_sensitive: bool = False) -> None:
        self.json_output = json_output
        self.show_sensitive = show_sensitive
        self.console = Console()

    def data(
        self,
        response: Dict[str, Any],
        *,
        rows: Optional[Iterable[Dict[str, Any]]] = None,
        columns: Optional[Sequence[Tuple[str, str]]] = None,
    ) -> None:
        safe = sanitized(response, show_sensitive=self.show_sensitive)
        if self.json_output:
            _write_json(safe)
            return
        if rows is not None and columns:
            self.table(rows, columns)
            return
        self.console.print_json(json.dumps(safe, ensure_ascii=False, default=str))

    def table(
        self,
        rows: Optional[Iterable[Dict[str, Any]]],
        columns: Sequence[Tuple[str, str]],
    ) -> None:
        table = Table(show_header=True, header_style="bold")
        for key, label in columns:
            justify = "right" if key in {"CPU", "GPU", "Size", "Price", "InstancePrice"} else "left"
            table.add_column(tr(label), justify=justify)
        count = 0
        for row in rows or ():
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
        grid.add_column(overflow="fold")
        for label, value in fields:
            grid.add_row(tr(label), self._cell(value, key=label))
        self.console.print(Panel(grid, title=tr(title), border_style="blue"))

    def error(self, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        if self.json_output:
            payload: Dict[str, Any] = {"ok": False, "error": message}
            if details:
                payload["details"] = sanitized(
                    details,
                    show_sensitive=self.show_sensitive,
                )
            _write_json(payload)
        else:
            Console(stderr=True).print(f"[red]{tr('Error')}:[/red] {message}")

    def _cell(self, value: Any, *, key: Optional[str] = None) -> str:
        if value is None:
            return "-"
        if key and not self.show_sensitive and _is_sensitive_key(key):
            return "***"
        if isinstance(value, bool):
            return tr("yes") if value else tr("no")
        if isinstance(value, (dict, list)):
            return json.dumps(
                sanitized(value, show_sensitive=self.show_sensitive),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        if key and "time" in key.casefold() and isinstance(value, (int, float)):
            return datetime.fromtimestamp(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        if key and key.casefold() in {"state", "status"}:
            state = str(value)
            normalized = state.casefold()
            display = tr(state)
            if normalized in {"running", "available", "success", "succeeded"}:
                return f"[green]{display}[/green]"
            if normalized in {"failed", "error", "terminated"}:
                return f"[red]{display}[/red]"
            if normalized not in {"stopped", "closed"}:
                return f"[yellow]{display}[/yellow]"
        return str(value)
