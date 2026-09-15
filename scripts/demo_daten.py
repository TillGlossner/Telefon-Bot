#!/usr/bin/env python3
"""Daten fuer die Browser-Demo erzeugen.

Die Demo im Browser bildet die Engine in JavaScript nach. Damit sie nicht
auseinanderlaeuft, bekommt sie zwei Dinge aus dieser Codebasis:

1. die Entscheidungsbaeume, exportiert aus derselben YAML wie im Betrieb
2. Pruefvektoren fuer das Sprachverstehen -- Eingabe und das Ergebnis, das die
   *Python*-Parser liefern

Der Selbsttest in der Demo laesst die JavaScript-Portierung ueber dieselben
Vektoren laufen. Weicht sie ab, faellt das sofort auf.

    python scripts/demo_daten.py          # demo/daten.js neu erzeugen
    python scripts/demo_daten.py --pruefen # nur pruefen, ob die Datei aktuell ist
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL / "src"))

from telefonbot.flow.export import flow_to_dict  # noqa: E402
from telefonbot.flow.loader import load_flow_file  # noqa: E402
from telefonbot.flow.model import ExpectKind, ExpectSpec  # noqa: E402
from telefonbot.nlu import german  # noqa: E402
from telefonbot.nlu.rules import RuleInterpreter  # noqa: E402
from telefonbot.flow.engine import UserInput  # noqa: E402

ZIEL = WURZEL / "demo" / "daten.js"
BEZUGSTAG = dt.date(2026, 3, 10)  # ein Dienstag -- feste Grundlage fuer Datumsvektoren

FLOWS = ["klinik_sekretariat", "lehrstuhl_sekretariat", "minimal_demo"]

JA_NEIN = ["ja", "ja genau", "korrekt", "passt so", "nein", "nee", "das stimmt nicht",
           "nicht richtig", "auf keinen Fall nein", "Moment mal"]
ZAHLEN = ["sieben", "einundzwanzig", "dreissig", "3 Stueck", "2,5", "keine Ahnung"]
ZIFFERN = ["eins zwei drei vier", "12345678", "eins zwei drei", "keine"]
DATUM = ["heute", "morgen bitte", "uebermorgen", "am 14.3.", "14.03.2027", "am 14. März",
         "am Freitag", "Dienstag", "am 5.1.", "am 31.2.", "weiss nicht"]
UHRZEIT = ["14:30", "14 Uhr 30", "neun Uhr", "halb drei", "viertel nach drei",
           "dreiviertel vier", "drei Uhr nachmittags", "halb drei nachmittags",
           "25 Uhr 99", "irgendwann"]
AUSWAHL = ["ich brauche einen Termin", "Sprechstunde", "ich moechte mich krank melden",
           "Terminn", "Krankmeldug", "Prüfungsamt", "ich wollte nur mal fragen"]

AUSWAHL_SPEC = ExpectSpec(
    kind=ExpectKind.CHOICE,
    options={
        "termin": ["termin", "sprechstunde", "beratungstermin"],
        "krankmeldung": ["krankmeldung", "krank melden"],
        "pruefungsamt": ["pruefungsamt", "pruefung"],
    },
)


def vektoren() -> list[dict]:
    """Eingabe -> erwartetes Ergebnis, erzeugt von den echten Python-Parsern."""
    nlu = RuleInterpreter(today=BEZUGSTAG)
    daten: list[dict] = []

    for text in JA_NEIN:
        daten.append({"art": "yes_no", "text": text, "erwartet": _werte(german.parse_yes_no(text))})
    for text in ZAHLEN:
        daten.append({"art": "number", "text": text, "erwartet": _werte(german.parse_number(text))})
    for text in ZIFFERN:
        daten.append({"art": "digits", "text": text, "erwartet": _werte(german.parse_digits(text))})
    for text in ZIFFERN:
        daten.append(
            {"art": "digits", "text": text, "laenge": 8,
             "erwartet": _werte(german.parse_digits(text, length=8))}
        )
    for text in DATUM:
        daten.append(
            {"art": "date", "text": text, "erwartet": _werte(german.parse_date(text, today=BEZUGSTAG))}
        )
    for text in UHRZEIT:
        daten.append({"art": "time", "text": text, "erwartet": _werte(german.parse_time(text))})
    for text in AUSWAHL:
        ergebnis = nlu.interpret(AUSWAHL_SPEC, UserInput(text=text))
        daten.append({"art": "choice", "text": text, "erwartet": _werte(ergebnis.value)})
    for text in ["normalisierung: Grüß Gott, Herr Müller!", "Sie haben 2,5 Stunden"]:
        daten.append({"art": "normalize", "text": text, "erwartet": german.normalize(text)})
    return daten


def _werte(wert):
    """Python-Werte in JSON-taugliche Form bringen (None bleibt None)."""
    if isinstance(wert, bool):
        return "yes" if wert else "no"
    if isinstance(wert, float) and wert.is_integer():
        return int(wert)
    return wert


def inhalt() -> str:
    daten = {
        "erzeugt_aus": "config/flows/*.yaml",
        "bezugstag": BEZUGSTAG.isoformat(),
        "auswahl_optionen": {k: list(v) for k, v in AUSWAHL_SPEC.options.items()},
        "flows": {
            name: flow_to_dict(load_flow_file(WURZEL / "config" / "flows" / f"{name}.yaml"))
            for name in FLOWS
        },
        "vektoren": vektoren(),
    }
    json_text = json.dumps(daten, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        "// Erzeugt von scripts/demo_daten.py -- nicht von Hand aendern.\n"
        "// Quelle: config/flows/*.yaml und die Python-Parser in src/telefonbot/nlu.\n"
        f"window.TELEFONBOT_DATEN = {json_text};\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pruefen", action="store_true", help="nur pruefen, nicht schreiben")
    args = parser.parse_args(argv)

    neu = inhalt()
    if args.pruefen:
        alt = ZIEL.read_text(encoding="utf-8") if ZIEL.exists() else ""
        if alt != neu:
            print(f"{ZIEL} ist nicht aktuell -- 'python scripts/demo_daten.py' ausfuehren")
            return 1
        print(f"{ZIEL} ist aktuell")
        return 0

    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    ZIEL.write_text(neu, encoding="utf-8")
    print(f"{ZIEL} geschrieben ({len(neu) // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
