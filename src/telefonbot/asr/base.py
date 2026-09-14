"""Schnittstelle zur Spracherkennung."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from telefonbot.audio.pcm import Samples


@dataclass(frozen=True)
class Transcript:
    """Ergebnis einer Erkennung."""

    text: str
    confidence: float = 1.0
    """0..1. Die Dialogsteuerung fragt unterhalb von ``min_confidence`` nach."""
    language: str = "de"
    duration_s: float = 0.0
    no_speech_prob: float = 0.0
    words: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.text.strip()


class ASR(Protocol):
    """Was ein Erkenner koennen muss."""

    sample_rate: int
    """Erwartete Abtastrate; die Gespraechssteuerung rechnet darauf um."""

    async def transcribe(self, samples: Samples, sample_rate: int) -> Transcript: ...

    async def warmup(self) -> None:
        """Modell laden, bevor der erste Anrufer wartet."""
        ...
