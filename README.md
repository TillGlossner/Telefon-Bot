# Telefonbot

Lokal gehosteter Telefon-Sprachassistent: nimmt Anrufe an, versteht gesprochene
Antworten, führt durch einen in YAML gepflegten **Entscheidungsbaum** und legt
einen Vorgang an oder verbindet mit einem Menschen.

Alles läuft auf eigener Hardware — Spracherkennung (faster-whisper),
Sprachsynthese (Piper) und Dialogsteuerung. Es verlässt kein Audio und kein
Text das System.

```
Anrufer ──SIP──> Asterisk ──AudioSocket──> Telefonbot ──> Vorgang / Weiterleitung
```

## Sofort ausprobieren

Ohne Installation, ohne Modelle, ohne Telefonanlage — nur Python 3.11 und PyYAML:

```bash
make pruefen     # Entscheidungsbäume statisch prüfen
make spielen     # Dialog im Terminal führen
make test        # 149 Tests, ca. 12 Sekunden
make graph       # Mermaid-Diagramme der Bäume
```

```
$ make spielen
Bot    : Guten Tag, hier ist der automatische Telefondienst des Lehrstuhls. …
Bot    : Möchten Sie einen Termin vereinbaren, einen Rückruf erbitten oder geht es um eine Prüfungsangelegenheit?
Anrufer: ich hätte gern einen Termin
Bot    : An welchem Tag möchten Sie kommen?
Anrufer: nächsten Dienstag
Bot    : Um welche Uhrzeit passt es Ihnen?
Anrufer: halb elf
Bot    : Und wie ist Ihr Name?
Anrufer: Till Glossner
Bot    : Ich habe notiert: Till Glossner, am 2026-09-15 um 10:30 Uhr. Stimmt das so?
```

## Vollbetrieb

```bash
pip install ".[asr,tts]"
python scripts/modelle_laden.py            # Whisper + Piper einmalig laden
cp config/config.example.yaml config/config.yaml
telefonbot start -c config/config.yaml
```

Details: [Betrieb an der LMU](docs/04-deployment-lmu.md).

## Dokumentation

| Dokument | Inhalt |
|---|---|
| [Architektur](docs/01-architektur.md) | Aufbau, Datenfluss, Latenzbudget, bewusste Einschränkungen |
| [Technologieentscheidungen](docs/02-stack-entscheidungen.md) | Warum Whisper, Piper, Asterisk — mit Alternativen und Hardwarebedarf |
| [Entscheidungsbäume](docs/03-entscheidungsbaeume.md) | YAML-Referenz und Erfahrungswerte für Telefondialoge |
| [Betrieb an der LMU](docs/04-deployment-lmu.md) | Installation, Asterisk-Dialplan, Monitoring, Fehlersuche |
| [Datenschutz](docs/05-datenschutz.md) | Was verarbeitet wird, was eingebaut ist, was noch zu klären ist |
| [Testkonzept](docs/06-testkonzept.md) | Was getestet ist — und was ehrlicherweise nicht |

## Aufbau des Projekts

```
src/telefonbot/
  flow/         Entscheidungsbaum: Modell, Loader, Prüfung, Engine, Diagramm
  nlu/          Deutsches Sprachverstehen (Ja/Nein, Zahlen, Datum, Uhrzeit)
  asr/ tts/     Spracherkennung und -ausgabe hinter schmalen Schnittstellen
  audio/        PCM, Resampling, Sprachaktivitätserkennung, Turn-Taking
  telephony/    AudioSocket (Asterisk), Fake-Transport, Textsimulator
  session/      Gesprächsschleife, Fachaktionen, Transkript
  control/      Status, Kennzahlen, Weiterleitungsziel für den Dialplan
config/flows/   Die Entscheidungsbäume
deploy/         Asterisk-Dialplan, systemd-Unit, Dockerfile
tests/          149 Tests, reine Standardbibliothek
```

Der Kern kommt ohne Fremdpakete aus (PyYAML nur zum Laden der Bäume). Die
schweren Pakete sind optionale Extras und werden erst beim Gebrauch importiert —
das hält Installation und Betrieb auf einer abgeschotteten VM einfach.

## Stand

**Fertig und getestet:** Entscheidungsbaum-Engine mit Nachfragen, Eskalation,
globalen Kommandos und statischer Prüfung; deutsches Sprachverstehen;
Gesprächsschleife mit Barge-in, Zeitgrenzen und Tasteneingabe; AudioSocket-
Protokoll und -Server; Konfiguration, CLI, Simulator, Control-API; zwei
Beispielbäume.

**Geschrieben, aber nie gegen echte Hardware gelaufen:** die Adapter für
faster-whisper und Piper (Pakete waren in der Entwicklungsumgebung nicht
installierbar) und die Asterisk-Anbindung (getestet gegen einen selbstgebauten
AudioSocket-Client, nicht gegen Asterisk).

**Noch offen:**

* Automatischer Löschlauf für Transkripte (`retention_days` wird noch nicht
  durchgesetzt)
* Optionaler LLM-Klassifikator für freie Formulierungen
  (`flow.engine.Interpreter` ist die vorgesehene Einhängestelle)
* Anbindung an ein konkretes Fachsystem — bisher legt der Bot Vorgänge als
  JSON-Dateien ab oder ruft einen konfigurierbaren Webhook auf
* Öffnungszeiten-Logik (außerhalb der Sprechzeit anders reagieren)

## Lizenz

MIT
