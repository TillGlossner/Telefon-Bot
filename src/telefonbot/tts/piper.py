"""Sprachsynthese mit Piper (lokal, CPU, deutsche Stimmen).

Piper ist fuer Telefonie die pragmatische Wahl: es laeuft in Echtzeit auf der
CPU, klingt fuer Ansagen gut genug und braucht keine GPU -- wichtig, wenn der
Bot neben der Telefonanlage auf einer kleinen VM laeuft. Stimmen liegen als
zwei Dateien vor (``*.onnx`` und ``*.onnx.json``) und lassen sich einmalig
herunterladen; danach ist kein Internetzugang mehr noetig.

Alternative fuer natuerlichere Stimmen: XTTS/Kokoro auf GPU -- gleiche
Schnittstelle, deutlich hoehere Latenz und Hardwareanforderung.
"""

from __future__ import annotations

import asyncio
import logging
from array import array
from dataclasses import dataclass

from telefonbot.audio.pcm import Samples, bytes_to_samples, resample
from telefonbot.tts.base import Speech

log = logging.getLogger(__name__)


@dataclass
class PiperConfig:
    """Einstellungen der Sprachausgabe."""

    voice_path: str = "models/piper/de_DE-thorsten-high.onnx"
    output_sample_rate: int = 8000
    """Telefonie laeuft mit 8 kHz; Piper synthetisiert je nach Stimme mit 16-22 kHz."""
    length_scale: float = 1.0
    """>1 spricht langsamer -- am Telefon oft verstaendlicher."""
    noise_scale: float = 0.667
    noise_w: float = 0.8


class PiperTTS:
    """Adapter auf ``piper.PiperVoice``."""

    def __init__(self, config: PiperConfig | None = None) -> None:
        self.config = config or PiperConfig()
        self.sample_rate = self.config.output_sample_rate
        self._voice = None
        self._native_rate: int | None = None

    def _load(self):
        if self._voice is None:
            from piper import PiperVoice  # erst hier: optionales Paket

            log.info("Lade Piper-Stimme %s", self.config.voice_path)
            self._voice = PiperVoice.load(self.config.voice_path)
            self._native_rate = self._voice.config.sample_rate
        return self._voice

    async def warmup(self) -> None:
        await asyncio.to_thread(self._load)

    async def synthesize(self, text: str) -> Speech:
        if not text.strip():
            return Speech(samples=array("h"), sample_rate=self.sample_rate)
        return await asyncio.to_thread(self._synthesize_sync, text)

    def _synthesize_sync(self, text: str) -> Speech:
        voice = self._load()
        chunks = bytearray()
        for chunk in voice.synthesize_stream_raw(
            text,
            length_scale=self.config.length_scale,
            noise_scale=self.config.noise_scale,
            noise_w=self.config.noise_w,
        ):
            chunks.extend(chunk)
        samples: Samples = bytes_to_samples(bytes(chunks))
        native = self._native_rate or 22050
        if native != self.sample_rate:
            samples = resample(samples, native, self.sample_rate)
        return Speech(samples=samples, sample_rate=self.sample_rate)
