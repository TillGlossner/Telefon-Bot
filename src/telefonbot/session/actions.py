"""Fachaktionen, die ein Dialogbaum ausloesen kann.

Der Baum kennt nur Namen ("create_appointment"); was dahinter passiert, wird
hier registriert. So bleibt der Baum frei von Systemwissen und die Anbindung an
Kalender, Ticketsystem oder CampusOnline austauschbar.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

ActionHandler = Callable[[dict[str, Any], "ActionContext"], Awaitable[Any]]


class ActionError(RuntimeError):
    """Die Fachaktion ist fehlgeschlagen; der Baum entscheidet ueber ``on_error``."""


class ActionContext:
    """Was eine Aktion ueber den laufenden Anruf wissen darf."""

    def __init__(self, call_id: str, caller: str, slots: dict[str, Any]) -> None:
        self.call_id = call_id
        self.caller = caller
        self.slots = slots


class ActionRegistry:
    """Verzeichnis der verfuegbaren Fachaktionen."""

    def __init__(self, *, timeout_s: float = 8.0) -> None:
        self._handlers: dict[str, ActionHandler] = {}
        self.timeout_s = timeout_s
        """Fachsysteme duerfen ein Telefonat nicht haengen lassen."""

    def register(self, name: str, handler: ActionHandler) -> None:
        if name in self._handlers:
            raise ValueError(f"Aktion '{name}' ist bereits registriert")
        self._handlers[name] = handler

    def __contains__(self, name: str) -> bool:
        return name in self._handlers

    @property
    def names(self) -> list[str]:
        return sorted(self._handlers)

    async def run(self, name: str, args: dict[str, Any], context: ActionContext) -> Any:
        """Fuehrt eine Aktion mit Zeitgrenze aus."""
        handler = self._handlers.get(name)
        if handler is None:
            raise ActionError(f"Unbekannte Aktion '{name}' (bekannt: {', '.join(self.names) or '-'})")
        try:
            return await asyncio.wait_for(handler(args, context), timeout=self.timeout_s)
        except asyncio.TimeoutError as exc:
            raise ActionError(f"Aktion '{name}' hat laenger als {self.timeout_s}s gebraucht") from exc
        except ActionError:
            raise
        except Exception as exc:  # Fachsystemfehler darf das Gespraech nicht abbrechen
            raise ActionError(f"Aktion '{name}' fehlgeschlagen: {exc}") from exc


# ------------------------------------------------------------- Standardaktionen


def make_file_ticket_action(directory: str | Path) -> ActionHandler:
    """Schreibt den Vorgang als JSON-Datei -- Fallback ohne angebundenes System."""

    async def handler(args: dict[str, Any], context: ActionContext) -> str:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        created = datetime.now(timezone.utc)
        ticket_id = f"V-{created.strftime('%Y%m%d-%H%M%S')}-{context.call_id[:8]}"
        payload = {
            "ticket_id": ticket_id,
            "erstellt": created.isoformat(),
            "anruf": context.call_id,
            "anrufer": context.caller,
            "daten": args,
        }
        (path / f"{ticket_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("Vorgang %s abgelegt", ticket_id)
        return ticket_id

    return handler


def make_http_action(url: str, *, method: str = "POST", token: str = "") -> ActionHandler:
    """Uebergibt die gesammelten Daten an ein internes System (z.B. Ticketsystem).

    Bewusst ``urllib`` statt requests: keine zusaetzliche Abhaengigkeit, und der
    blockierende Aufruf laeuft in einem Thread.
    """

    async def handler(args: dict[str, Any], context: ActionContext) -> Any:
        import urllib.error
        import urllib.request

        body = json.dumps({"anruf": context.call_id, "daten": args}).encode("utf-8")
        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"Bearer {token}")

        def call() -> Any:
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    raw = response.read().decode("utf-8")
            except urllib.error.URLError as exc:
                raise ActionError(f"{url} nicht erreichbar: {exc}") from exc
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw

        return await asyncio.to_thread(call)

    return handler


async def noop_action(args: dict[str, Any], context: ActionContext) -> None:
    """Platzhalter fuer Baeume, die noch kein Fachsystem haben."""
    log.info("noop-Aktion mit %s", args)
    return None


def default_registry(ticket_dir: str | Path = "var/vorgaenge") -> ActionRegistry:
    """Registry mit den Aktionen, die ohne Fremdsystem funktionieren."""
    registry = ActionRegistry()
    registry.register("noop", noop_action)
    registry.register("create_ticket", make_file_ticket_action(ticket_dir))
    registry.register("create_appointment", make_file_ticket_action(ticket_dir))
    return registry
