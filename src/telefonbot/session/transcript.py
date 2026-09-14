"""Gespraechsprotokoll.

Ein Telefonbot ohne Protokoll ist im Betrieb nicht zu verbessern -- und ein
Protokoll ohne Datenschutz ist an einer Universitaet nicht zu betreiben.
Deshalb: strukturierte Ereignisse, als sensibel markierte Slots werden
maskiert, und Rohaudio wird nur gespeichert, wenn es ausdruecklich
eingeschaltet ist.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REDACTED = "***"


@dataclass
class TranscriptEvent:
    """Ein Ereignis im Gespraech."""

    at: str
    kind: str  # "bot" | "user" | "dtmf" | "action" | "system"
    text: str = ""
    node_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Transcript:
    """Alle Ereignisse eines Anrufs."""

    call_id: str
    flow_id: str
    started_at: str = field(default_factory=lambda: _now())
    caller: str = ""
    events: list[TranscriptEvent] = field(default_factory=list)
    sensitive_slots: set[str] = field(default_factory=set)

    def add(self, kind: str, text: str = "", *, node_id: str = "", **data: Any) -> TranscriptEvent:
        event = TranscriptEvent(at=_now(), kind=kind, text=text, node_id=node_id, data=data)
        self.events.append(event)
        return event

    def dialogue(self) -> list[tuple[str, str]]:
        """Nur der Wortwechsel -- praktisch fuer Tests und Qualitaetskontrolle."""
        return [(e.kind, e.text) for e in self.events if e.kind in ("bot", "user") and e.text]

    def to_dict(self, *, slots: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "anruf": self.call_id,
            "flow": self.flow_id,
            "start": self.started_at,
            "anrufer": _mask_number(self.caller),
            "slots": self.redacted_slots(slots or {}),
            "ereignisse": [
                {
                    "at": e.at,
                    "typ": e.kind,
                    "text": e.text,
                    "knoten": e.node_id,
                    **({"daten": e.data} if e.data else {}),
                }
                for e in self.events
            ],
        }

    def redacted_slots(self, slots: dict[str, Any]) -> dict[str, Any]:
        return {
            name: (REDACTED if name in self.sensitive_slots else value)
            for name, value in slots.items()
        }


class TranscriptWriter:
    """Schreibt Transkripte als JSON-Zeilen; eine Datei pro Tag."""

    def __init__(self, directory: str | Path = "var/transkripte", *, enabled: bool = True) -> None:
        self.directory = Path(directory)
        self.enabled = enabled

    def write(self, transcript: Transcript, slots: dict[str, Any] | None = None) -> Path | None:
        if not self.enabled:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
        line = json.dumps(transcript.to_dict(slots=slots), ensure_ascii=False)
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            log.error("Transkript nicht schreibbar: %s", exc)
            return None
        return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _mask_number(number: str) -> str:
    """Rufnummern nur gekuerzt protokollieren (Datensparsamkeit)."""
    digits = "".join(c for c in number if c.isdigit())
    if len(digits) < 4:
        return REDACTED if digits else number
    return f"{digits[:3]}{'*' * (len(digits) - 6)}{digits[-3:]}" if len(digits) > 6 else REDACTED
