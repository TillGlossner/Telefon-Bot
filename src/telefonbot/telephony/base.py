"""Transport-Abstraktion zwischen Telefonanlage und Dialogsteuerung.

Der Gespraechsablauf soll nicht wissen, ob am anderen Ende Asterisk, eine
WAV-Datei oder ein Test haengt. Deshalb genau eine schmale Schnittstelle:
Ereignisse herein, Audio hinaus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol

from telefonbot.audio.pcm import Samples


@dataclass(frozen=True)
class AudioFrame:
    """Ein Block Audio vom Anrufer."""

    samples: Samples


@dataclass(frozen=True)
class DtmfDigit:
    """Eine gedrueckte Taste."""

    digit: str


@dataclass(frozen=True)
class CallEnded:
    """Die Gegenstelle hat aufgelegt."""

    reason: str = "remote_hangup"


InboundEvent = AudioFrame | DtmfDigit | CallEnded


@dataclass
class CallInfo:
    """Metadaten des Anrufs, soweit die Telefonanlage sie liefert."""

    call_id: str = "local"
    caller: str = ""
    called: str = ""
    extra: dict[str, str] = field(default_factory=dict)


class AudioTransport(Protocol):
    """Was ein Telefonkanal koennen muss."""

    sample_rate: int
    frame_ms: int
    info: CallInfo

    def events(self) -> AsyncIterator[InboundEvent]:
        """Strom eingehender Ereignisse (Audio, Tasten, Auflegen)."""
        ...

    async def send_audio(self, samples: Samples) -> None:
        """Audio an den Anrufer ausgeben."""
        ...

    async def stop_audio(self) -> None:
        """Laufende Ausgabe sofort abbrechen (Barge-in)."""
        ...

    async def hangup(self, reason: str = "completed") -> None:
        """Gespraech beenden."""
        ...
