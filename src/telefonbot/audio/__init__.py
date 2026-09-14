"""Audio-Grundlagen: PCM-Verarbeitung und Sprachaktivitaetserkennung."""

from telefonbot.audio.pcm import (
    bytes_to_samples,
    frames,
    read_wav,
    resample,
    rms,
    samples_to_bytes,
    silence,
    write_wav,
)
from telefonbot.audio.vad import EnergyVAD, SegmentEvent, SpeechSegmenter

__all__ = [
    "EnergyVAD",
    "SegmentEvent",
    "SpeechSegmenter",
    "bytes_to_samples",
    "frames",
    "read_wav",
    "resample",
    "rms",
    "samples_to_bytes",
    "silence",
    "write_wav",
]
