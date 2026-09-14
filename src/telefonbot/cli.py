"""Kommandozeile des Telefonbots.

::

    telefonbot pruefen config/flows/*.yaml     # Baum statisch pruefen
    telefonbot spielen config/flows/x.yaml     # Dialog im Terminal durchspielen
    telefonbot graph config/flows/x.yaml       # Mermaid-Diagramm erzeugen
    telefonbot ansage "Guten Tag" -o test.wav  # Sprachausgabe pruefen
    telefonbot erkennen aufnahme.wav           # Spracherkennung pruefen
    telefonbot sprechen -c config/config.yaml  # mit dem Bot sprechen (Browser)
    telefonbot start -c config/config.yaml     # Dienst starten
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from telefonbot import __version__
from telefonbot.config import load_config
from telefonbot.flow.graph import to_mermaid
from telefonbot.flow.loader import FlowLoadError, load_flow_file
from telefonbot.flow.validate import validate_flow


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    return int(args.func(args) or 0)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telefonbot", description="Telefonbot der LMU")
    parser.add_argument("--version", action="version", version=f"telefonbot {__version__}")
    parser.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR")
    sub = parser.add_subparsers(dest="befehl", required=True)

    p = sub.add_parser("pruefen", help="Entscheidungsbaeume statisch pruefen")
    p.add_argument("flows", nargs="+", type=Path)
    p.add_argument("--warnungen-als-fehler", action="store_true")
    p.set_defaults(func=cmd_pruefen)

    p = sub.add_parser("spielen", help="Dialog im Terminal durchspielen")
    p.add_argument("flow", type=Path)
    p.add_argument("--eingaben", nargs="*", help="Antworten vorgeben statt zu tippen")
    p.set_defaults(func=cmd_spielen)

    p = sub.add_parser("graph", help="Mermaid-Diagramm des Baums erzeugen")
    p.add_argument("flow", type=Path)
    p.add_argument("-o", "--ausgabe", type=Path)
    p.set_defaults(func=cmd_graph)

    p = sub.add_parser("ansage", help="Text synthetisieren und als WAV speichern")
    p.add_argument("text")
    p.add_argument("-o", "--ausgabe", type=Path, default=Path("var/ansage.wav"))
    p.add_argument("-c", "--config", type=Path, default=Path("config/config.yaml"))
    p.set_defaults(func=cmd_ansage)

    p = sub.add_parser("erkennen", help="WAV-Datei erkennen lassen")
    p.add_argument("wav", type=Path)
    p.add_argument("-c", "--config", type=Path, default=Path("config/config.yaml"))
    p.set_defaults(func=cmd_erkennen)

    p = sub.add_parser("sprechen", help="Mit dem Bot sprechen (Browser-Mikrofon, alles lokal)")
    p.add_argument("-c", "--config", type=Path, default=Path("config/config.yaml"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8099)
    p.set_defaults(func=cmd_sprechen)

    p = sub.add_parser("start", help="Dienst starten (AudioSocket + Control-API)")
    p.add_argument("-c", "--config", type=Path, default=Path("config/config.yaml"))
    p.set_defaults(func=cmd_start)

    return parser


# ----------------------------------------------------------------- Befehle


def cmd_pruefen(args) -> int:
    fehler = 0
    for path in args.flows:
        try:
            flow = load_flow_file(path, strict=False)
        except FlowLoadError as exc:
            print(f"✗ {path}\n  {exc}")
            fehler += 1
            continue
        issues = validate_flow(flow)
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        zeichen = "✓" if not errors else "✗"
        print(f"{zeichen} {path}  ({len(flow.nodes)} Knoten, {len(errors)} Fehler, {len(warnings)} Warnungen)")
        for issue in errors + warnings:
            print(f"    {issue}")
        fehler += len(errors) + (len(warnings) if args.warnungen_als_fehler else 0)
    return 1 if fehler else 0


def cmd_spielen(args) -> int:
    from telefonbot.telephony.simulator import simulate

    flow = load_flow_file(args.flow)
    print(f"Flow '{flow.id}' v{flow.version} -- Eingabe: Text, '#1' fuer Taste 1, leer fuer Schweigen")
    print("Abbruch mit Strg-D.\n")

    if args.eingaben:
        result = simulate(flow, list(args.eingaben))
        print("\n".join(result.transcript()))
    else:
        def frage(ansagen: list[str]) -> str:
            for text in ansagen:
                print(f"Bot    : {text}")
            try:
                return input("Anrufer: ")
            except EOFError:
                print()
                raise SystemExit(0) from None

        result = simulate(flow, frage)
        for text in result.steps[-1].bot:
            print(f"Bot    : {text}")

    print(f"\nEnde: {result.reason}")
    if result.transfer_target:
        print(f"Weiterleitung an: {result.transfer_target}")
    if result.slots:
        print("Erfasste Daten:")
        for name, value in result.slots.items():
            print(f"  {name} = {value}")
    return 0


def cmd_graph(args) -> int:
    flow = load_flow_file(args.flow, strict=False)
    diagram = to_mermaid(flow)
    if args.ausgabe:
        args.ausgabe.parent.mkdir(parents=True, exist_ok=True)
        args.ausgabe.write_text(diagram + "\n", encoding="utf-8")
        print(f"Diagramm geschrieben: {args.ausgabe}")
    else:
        print(diagram)
    return 0


def cmd_ansage(args) -> int:
    from telefonbot.app import build_tts
    from telefonbot.audio.pcm import write_wav

    config = load_config(args.config)
    tts = build_tts(config)

    async def run():
        await tts.warmup()
        return await tts.synthesize(args.text)

    speech = asyncio.run(run())
    write_wav(args.ausgabe, speech.samples, speech.sample_rate)
    print(f"{args.ausgabe} ({speech.duration_s:.1f}s, {speech.sample_rate} Hz)")
    return 0


def cmd_erkennen(args) -> int:
    from telefonbot.app import build_asr
    from telefonbot.audio.pcm import read_wav

    config = load_config(args.config)
    asr = build_asr(config)
    samples, rate = read_wav(args.wav)

    async def run():
        await asr.warmup()
        return await asr.transcribe(samples, rate)

    transcript = asyncio.run(run())
    print(f"Text      : {transcript.text}")
    print(f"Konfidenz : {transcript.confidence:.2f}")
    print(f"Dauer     : {transcript.duration_s:.1f}s")
    return 0


def cmd_sprechen(args) -> int:
    from telefonbot.voice import VoiceWebService

    config = load_config(args.config)
    dienst = VoiceWebService(config, host=args.host, port=args.port)
    try:
        asyncio.run(dienst.run())
    except KeyboardInterrupt:
        print("\nSprachdienst beendet")
    return 0


def cmd_start(args) -> int:
    from telefonbot.app import BotService

    config = load_config(args.config)
    service = BotService(config)
    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        print("\nDienst beendet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
