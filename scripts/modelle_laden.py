#!/usr/bin/env python3
"""Modelle einmalig herunterladen, damit der Betrieb offline laufen kann.

Auf der Zielmaschine an der LMU ist ausgehender Verkehr oft eingeschraenkt.
Dieses Skript laedt Whisper- und Piper-Modelle in ``models/``; danach braucht
der Dienst keinen Internetzugang mehr. Laesst sich auch auf einem anderen
Rechner ausfuehren und das Verzeichnis kopieren.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE"
PIPER_VOICES = {
    "thorsten-high": f"{PIPER_BASE}/thorsten/high/de_DE-thorsten-high.onnx",
    "thorsten-medium": f"{PIPER_BASE}/thorsten/medium/de_DE-thorsten-medium.onnx",
    "eva_k-x_low": f"{PIPER_BASE}/eva_k/x_low/de_DE-eva_k-x_low.onnx",
}


def lade_piper(voice: str, ziel: Path) -> None:
    url = PIPER_VOICES.get(voice)
    if url is None:
        raise SystemExit(f"Unbekannte Stimme '{voice}'. Bekannt: {', '.join(PIPER_VOICES)}")
    ziel.mkdir(parents=True, exist_ok=True)
    for quelle in (url, url + ".json"):
        datei = ziel / quelle.rsplit("/", 1)[1]
        if datei.exists():
            print(f"vorhanden: {datei}")
            continue
        print(f"lade {quelle}")
        urllib.request.urlretrieve(quelle, datei)
        print(f"  -> {datei} ({datei.stat().st_size // 1024} KiB)")


def lade_whisper(model: str, ziel: Path) -> None:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit(
            "faster-whisper ist nicht installiert: pip install 'telefonbot[asr]'"
        ) from None
    ziel.mkdir(parents=True, exist_ok=True)
    print(f"lade Whisper-Modell {model} nach {ziel}")
    WhisperModel(model, device="cpu", compute_type="int8", download_root=str(ziel))
    print("fertig")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--whisper", default="large-v3", help="Whisper-Modell oder 'keins'")
    parser.add_argument("--piper", default="thorsten-high", help="Piper-Stimme oder 'keins'")
    parser.add_argument("--ziel", type=Path, default=Path("models"))
    args = parser.parse_args(argv)

    if args.piper != "keins":
        lade_piper(args.piper, args.ziel / "piper")
    if args.whisper != "keins":
        lade_whisper(args.whisper, args.ziel / "whisper")
    return 0


if __name__ == "__main__":
    sys.exit(main())
