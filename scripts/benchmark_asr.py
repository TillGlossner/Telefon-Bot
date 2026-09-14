#!/usr/bin/env python3
"""Erkennungsqualitaet und Latenz auf der eigenen Hardware messen.

Ohne Messung auf der Zielmaschine ist jede Modellempfehlung geraten. Das
Skript laesst ein Modell ueber WAV-Dateien laufen und meldet Dauer, Echtzeit-
faktor und -- wenn Referenztexte vorliegen -- die Wortfehlerrate.

    python scripts/benchmark_asr.py aufnahmen/*.wav --modell large-v3

Referenztexte werden als gleichnamige ``.txt``-Datei neben der WAV erwartet.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from telefonbot.asr.whisper import FasterWhisperASR, WhisperConfig  # noqa: E402
from telefonbot.audio.pcm import duration_s, read_wav  # noqa: E402
from telefonbot.nlu.german import normalize  # noqa: E402


def wortfehlerrate(referenz: str, hypothese: str) -> float:
    """Levenshtein-Abstand auf Wortebene, geteilt durch die Referenzlaenge."""
    r, h = normalize(referenz).split(), normalize(hypothese).split()
    if not r:
        return 0.0
    vorher = list(range(len(h) + 1))
    for i, wort_r in enumerate(r, start=1):
        aktuell = [i]
        for j, wort_h in enumerate(h, start=1):
            aktuell.append(
                min(vorher[j] + 1, aktuell[j - 1] + 1, vorher[j - 1] + (wort_r != wort_h))
            )
        vorher = aktuell
    return vorher[-1] / len(r)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dateien", nargs="+", type=Path)
    parser.add_argument("--modell", default="large-v3")
    parser.add_argument("--geraet", default="auto")
    parser.add_argument("--compute-type", default="int8_float16")
    args = parser.parse_args(argv)

    asr = FasterWhisperASR(
        WhisperConfig(model=args.modell, device=args.geraet, compute_type=args.compute_type)
    )
    print(f"lade Modell {args.modell} ...")
    start = time.monotonic()
    await asr.warmup()
    print(f"Modell geladen in {time.monotonic() - start:.1f}s\n")

    gesamt_audio = gesamt_zeit = 0.0
    fehlerraten: list[float] = []

    for datei in args.dateien:
        samples, rate = read_wav(datei)
        laenge = duration_s(samples, rate)
        begin = time.monotonic()
        transcript = await asr.transcribe(samples, rate)
        dauer = time.monotonic() - begin
        gesamt_audio += laenge
        gesamt_zeit += dauer

        zeile = f"{datei.name:30s} {laenge:5.1f}s Audio  {dauer:5.2f}s  RTF {dauer / max(laenge, 0.01):4.2f}"
        referenz = datei.with_suffix(".txt")
        if referenz.exists():
            wer = wortfehlerrate(referenz.read_text(encoding="utf-8"), transcript.text)
            fehlerraten.append(wer)
            zeile += f"  WER {wer:5.1%}"
        print(zeile)
        print(f"{'':30s} -> {transcript.text}  (Konfidenz {transcript.confidence:.2f})")

    print(f"\nGesamt: {gesamt_audio:.1f}s Audio in {gesamt_zeit:.1f}s "
          f"(Echtzeitfaktor {gesamt_zeit / max(gesamt_audio, 0.01):.2f})")
    if fehlerraten:
        print(f"Mittlere Wortfehlerrate: {sum(fehlerraten) / len(fehlerraten):.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
