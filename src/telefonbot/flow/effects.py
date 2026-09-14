"""Effekte, die die Engine zurueckgibt.

Die Engine selbst ist synchron und seiteneffektfrei: Sie sagt nur, *was* zu tun
ist (sprechen, zuhoeren, Aktion aufrufen, verbinden, auflegen). Wer das mit
Audio, Telefonie oder Fachsystemen umsetzt, steht in :mod:`telefonbot.session`.
Dadurch laesst sich der komplette Gespraechsverlauf ohne Audio testen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from telefonbot.flow.model import ExpectSpec


@dataclass(frozen=True)
class Speak:
    """Text ausgeben (TTS)."""

    text: str
    node_id: str
    barge_in: bool = True
    """Darf der Anrufer die Ansage unterbrechen?"""
    is_reprompt: bool = False


@dataclass(frozen=True)
class Collect:
    """Auf eine Antwort des Anrufers warten."""

    expect: ExpectSpec
    node_id: str
    timeout_s: float
    slot: str | None = None
    attempt: int = 1


@dataclass(frozen=True)
class Invoke:
    """Eine registrierte Fachaktion ausfuehren (Terminbuchung, Ticket, ...)."""

    action: str
    args: dict[str, Any]
    node_id: str
    assign: str | None = None


@dataclass(frozen=True)
class Transfer:
    """An einen Menschen oder eine andere Nebenstelle weiterleiten."""

    target: str
    node_id: str


@dataclass(frozen=True)
class Hangup:
    """Gespraech beenden."""

    node_id: str
    reason: str = "completed"


Effect = Speak | Collect | Invoke | Transfer | Hangup


@dataclass(frozen=True)
class Turn:
    """Ergebnis eines Engine-Schritts: Ansagen plus genau ein Abschluss-Effekt.

    ``effects`` enthaelt die Ansagen in Reihenfolge; ``pending`` ist der Effekt,
    auf den die Engine eine Rueckmeldung erwartet (``Collect``/``Invoke``) bzw.
    der das Gespraech beendet (``Transfer``/``Hangup``).
    """

    effects: list[Effect] = field(default_factory=list)
    pending: Effect | None = None

    @property
    def finished(self) -> bool:
        return isinstance(self.pending, (Transfer, Hangup))

    @property
    def all_effects(self) -> list[Effect]:
        return [*self.effects, *([self.pending] if self.pending else [])]

    def spoken_text(self) -> str:
        """Alle Ansagen dieses Schritts als ein String (praktisch fuer Tests)."""
        return " ".join(e.text for e in self.all_effects if isinstance(e, Speak))
