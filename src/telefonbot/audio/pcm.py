"""PCM-Hilfsfunktionen (16 bit signed, mono).

Telefonie liefert 8 kHz, Spracherkennung will 16 kHz. Das Umrechnen passiert
hier -- bewusst in reinem Python mit ``array``: ``audioop`` faellt mit Python
3.13 weg, und numpy soll fuer den Kern nicht Pflicht sein. Bei 8 kHz mono ist
der Rechenaufwand vernachlaessigbar.
"""

from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path
from typing import Iterator

Samples = array  # array("h"), 16-bit signed


def bytes_to_samples(data: bytes) -> Samples:
    """Little-Endian PCM16-Bytes -> Sample-Array."""
    if len(data) % 2:
        data = data[:-1]  # angebrochenes Sample verwerfen
    out = array("h")
    out.frombytes(data)
    if sys_is_big_endian():
        out.byteswap()
    return out


def samples_to_bytes(samples: Samples) -> bytes:
    """Sample-Array -> Little-Endian PCM16-Bytes."""
    if sys_is_big_endian():
        copy = array("h", samples)
        copy.byteswap()
        return copy.tobytes()
    return samples.tobytes()


def sys_is_big_endian() -> bool:
    import sys

    return sys.byteorder == "big"


def resample(samples: Samples, src_rate: int, dst_rate: int) -> Samples:
    """Abtastrate aendern (lineare Interpolation, beim Verkleinern mit Tiefpass)."""
    if src_rate == dst_rate or not samples:
        return array("h", samples)
    if dst_rate < src_rate:
        samples = _lowpass(samples, cutoff_ratio=dst_rate / src_rate)

    ratio = dst_rate / src_rate
    out_len = max(1, int(len(samples) * ratio))
    out = array("h", bytes(2 * out_len))
    last = len(samples) - 1
    for i in range(out_len):
        pos = i / ratio
        left = int(pos)
        if left >= last:
            out[i] = samples[last]
            continue
        frac = pos - left
        value = samples[left] + (samples[left + 1] - samples[left]) * frac
        out[i] = _clip(int(value))
    return out


def _lowpass(samples: Samples, *, cutoff_ratio: float) -> Samples:
    """Gleitender Mittelwert als einfacher Anti-Aliasing-Filter."""
    width = max(2, int(round(1 / max(cutoff_ratio, 1e-6))))
    if width < 2:
        return samples
    out = array("h", bytes(2 * len(samples)))
    running = 0
    for i, value in enumerate(samples):
        running += value
        if i >= width:
            running -= samples[i - width]
            out[i] = _clip(running // width)
        else:
            out[i] = _clip(running // (i + 1))
    return out


def _clip(value: int) -> int:
    return -32768 if value < -32768 else (32767 if value > 32767 else value)


def rms(samples: Samples) -> float:
    """Effektivwert (Lautstaerkemass) eines Blocks."""
    if not samples:
        return 0.0
    total = 0
    for value in samples:
        total += value * value
    return math.sqrt(total / len(samples))


def dbfs(samples: Samples) -> float:
    """Pegel in dB relativ zur Vollaussteuerung; Stille -> -100 dB."""
    level = rms(samples)
    if level <= 0:
        return -100.0
    return 20 * math.log10(level / 32768.0)


def frames(samples: Samples, frame_size: int) -> Iterator[Samples]:
    """Zerlegt in Bloecke fester Laenge; ein Rest am Ende wird verworfen."""
    for start in range(0, len(samples) - frame_size + 1, frame_size):
        yield samples[start : start + frame_size]


def silence(duration_ms: int, sample_rate: int) -> Samples:
    """Stille der gewuenschten Laenge."""
    return array("h", bytes(2 * int(sample_rate * duration_ms / 1000)))


def tone(duration_ms: int, sample_rate: int, freq: float = 440.0, amplitude: float = 0.3) -> Samples:
    """Sinuston -- fuer Tests und als Platzhalter-Audio ohne TTS-Modell."""
    count = int(sample_rate * duration_ms / 1000)
    peak = amplitude * 32767
    return array(
        "h",
        [_clip(int(peak * math.sin(2 * math.pi * freq * i / sample_rate))) for i in range(count)],
    )


def duration_s(samples: Samples, sample_rate: int) -> float:
    return len(samples) / float(sample_rate)


def read_wav(path: str | Path) -> tuple[Samples, int]:
    """Liest eine PCM16-Mono-WAV-Datei."""
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError(f"{path}: nur 16-bit PCM wird unterstuetzt")
        channels = handle.getnchannels()
        rate = handle.getframerate()
        data = handle.readframes(handle.getnframes())
    samples = bytes_to_samples(data)
    if channels > 1:
        samples = array("h", samples[::channels])  # ersten Kanal nehmen
    return samples, rate


def write_wav(path: str | Path, samples: Samples, sample_rate: int) -> None:
    """Schreibt eine PCM16-Mono-WAV-Datei."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples_to_bytes(samples))
