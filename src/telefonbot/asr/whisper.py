"""Spracherkennung mit faster-whisper (lokal, ohne Cloud).

Warum faster-whisper: Whisper large-v3 ist fuer deutsches Telefonaudio nach wie
vor der robusteste frei verfuegbare Erkenner, und die CTranslate2-Umsetzung
laeuft mit int8-Quantisierung auch ohne GPU in brauchbarer Geschwindigkeit.
Alles bleibt auf dem Rechner der LMU -- kein Audio verlaesst das Haus.

Modellwahl (Anhaltswerte, GPU): ``large-v3`` fuer beste Qualitaet,
``distil-large-v3`` wenn Latenz wichtiger ist, ``medium``/``small`` fuer reinen
CPU-Betrieb. Konkrete Zahlen fuer die eigene Hardware liefert
``scripts/benchmark_asr.py``.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass

from telefonbot.asr.base import Transcript
from telefonbot.audio.pcm import Samples, duration_s, resample

log = logging.getLogger(__name__)


@dataclass
class WhisperConfig:
    """Einstellungen des Erkenners."""

    model: str = "large-v3"
    device: str = "auto"  # "cuda" | "cpu" | "auto"
    compute_type: str = "int8_float16"
    language: str = "de"
    beam_size: int = 5
    vad_filter: bool = True
    initial_prompt: str = ""
    """Fachbegriffe vorgeben ("Matrikelnummer, Pruefungsamt, Sprechstunde") --
    hebt die Trefferquote bei Eigennamen deutlich."""
    model_dir: str | None = None
    """Lokales Modellverzeichnis; noetig auf Rechnern ohne Internetzugang."""


class FasterWhisperASR:
    """Adapter auf ``faster_whisper.WhisperModel``."""

    sample_rate = 16000

    def __init__(self, config: WhisperConfig | None = None) -> None:
        self.config = config or WhisperConfig()
        self._model = None
        self._lock = asyncio.Lock()

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # erst hier: schweres Paket

            log.info("Lade Whisper-Modell %s (%s)", self.config.model, self.config.device)
            self._model = WhisperModel(
                self.config.model,
                device=self.config.device,
                compute_type=self.config.compute_type,
                download_root=self.config.model_dir,
            )
        return self._model

    async def warmup(self) -> None:
        """Modell im Hintergrund laden, damit der erste Anruf nicht wartet."""
        async with self._lock:
            await asyncio.to_thread(self._load)

    async def transcribe(self, samples: Samples, sample_rate: int) -> Transcript:
        if not samples:
            return Transcript(text="", confidence=0.0)
        audio = resample(samples, sample_rate, self.sample_rate) if sample_rate != self.sample_rate else samples
        seconds = duration_s(audio, self.sample_rate)
        return await asyncio.to_thread(self._transcribe_sync, audio, seconds)

    def _transcribe_sync(self, audio: Samples, seconds: float) -> Transcript:
        import numpy as np

        model = self._load()
        pcm = np.asarray(audio, dtype=np.float32) / 32768.0
        segments, info = model.transcribe(
            pcm,
            language=self.config.language,
            beam_size=self.config.beam_size,
            vad_filter=self.config.vad_filter,
            initial_prompt=self.config.initial_prompt or None,
            condition_on_previous_text=False,
        )
        texts: list[str] = []
        logprobs: list[float] = []
        no_speech: list[float] = []
        for segment in segments:
            texts.append(segment.text.strip())
            logprobs.append(segment.avg_logprob)
            no_speech.append(segment.no_speech_prob)

        text = " ".join(t for t in texts if t).strip()
        return Transcript(
            text=text,
            confidence=_confidence(logprobs, no_speech),
            language=getattr(info, "language", self.config.language),
            duration_s=seconds,
            no_speech_prob=max(no_speech) if no_speech else 0.0,
            words=text.split(),
        )


def _confidence(logprobs: list[float], no_speech: list[float]) -> float:
    """Aus Whisper-Rohwerten eine Konfidenz zwischen 0 und 1 bilden.

    Whisper liefert keine kalibrierte Konfidenz. ``exp(avg_logprob)`` ist ein
    brauchbarer Ersatz; sehr hohe ``no_speech_prob`` zieht das Ergebnis nach
    unten, weil dann meist Leitungsrauschen erkannt wurde.
    """
    if not logprobs:
        return 0.0
    mean_logprob = sum(logprobs) / len(logprobs)
    base = math.exp(max(min(mean_logprob, 0.0), -5.0))
    penalty = 1.0 - min(max(no_speech) if no_speech else 0.0, 1.0)
    return round(max(0.0, min(1.0, base * penalty)), 3)
