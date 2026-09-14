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

## Mit dem Bot sprechen

```bash
pip install ".[asr,tts]"
python scripts/modelle_laden.py            # einmalig: Whisper + Piper
telefonbot sprechen -c config/config.yaml  # dann http://127.0.0.1:8099 öffnen
```

Mikrofon im Browser, Audio über WebSocket an den lokalen Dienst, dort echtes
Whisper, echter Entscheidungsbaum, echtes Piper — dieselbe Gesprächsschleife
wie am Telefon, nur ohne Telefonanlage. Es geht kein Audio ins Netz.
Details und Fehlersuche: [Mit dem Bot sprechen](docs/07-sprachinterface.md).

## Den Baum durchklicken

Ohne Installation, ohne Mikrofon: der Entscheidungsbaum als Artefakt mit
Telefontastatur, Sprechzeiten-Umschalter und Blick auf den Zustand der Engine.
Die Seite liegt in [`demo/`](demo/); ihre Daten erzeugt `make demo` aus derselben
YAML, die auch der Dienst lädt.

## Sofort ausprobieren

Ohne Installation, ohne Modelle, ohne Telefonanlage — nur Python 3.11 und PyYAML:

```bash
make pruefen     # Entscheidungsbäume statisch prüfen
make spielen     # Dialog im Terminal führen
make test        # 189 Tests, ca. 40 Sekunden
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
| [Mit dem Bot sprechen](docs/07-sprachinterface.md) | Sprechprobe im Browser: starten, bedienen, Fehler suchen |

## Aufbau des Projekts

```
src/telefonbot/
  flow/         Entscheidungsbaum: Modell, Loader, Prüfung, Engine, Diagramm
  nlu/          Deutsches Sprachverstehen (Ja/Nein, Zahlen, Datum, Uhrzeit)
  asr/ tts/     Spracherkennung und -ausgabe hinter schmalen Schnittstellen
  audio/        PCM, Resampling, Sprachaktivitätserkennung, Turn-Taking
  telephony/    AudioSocket (Asterisk), Browser-Transport, Fake, Textsimulator
  net/          WebSocket und Dateiserver (Standardbibliothek)
  webclient/    Sprachclient: Mikrofonaufnahme und Wiedergabe im Browser
  session/      Gesprächsschleife, Fachaktionen, Transkript
  control/      Status, Kennzahlen, Weiterleitungsziel für den Dialplan
config/flows/   Die Entscheidungsbäume
demo/           Browser-Demo (JavaScript-Portierung der Engine, Daten aus der YAML)
deploy/         Asterisk-Dialplan, systemd-Unit, Dockerfile
tests/          189 Tests, reine Standardbibliothek
```

Der Kern kommt ohne Fremdpakete aus (PyYAML nur zum Laden der Bäume). Die
schweren Pakete sind optionale Extras und werden erst beim Gebrauch importiert —
das hält Installation und Betrieb auf einer abgeschotteten VM einfach.

## Stand

**Fertig und getestet:** Entscheidungsbaum-Engine mit Nachfragen, Eskalation,
globalen Kommandos und statischer Prüfung; deutsches Sprachverstehen;
Gesprächsschleife mit Barge-in, Zeitgrenzen und Tasteneingabe; Sprechzeiten-
Logik (außerhalb der Sprechzeit wird ein Rückruf aufgenommen statt ins Leere
verbunden); AudioSocket-Protokoll und -Server; Konfiguration, CLI, Simulator,
Control-API; zwei Beispielbäume.

**Ausgelegt auf:** Lehrstuhl-/Sekretariatsbetrieb, Asterisk als schlanker
Vermittler an einer SIP-Nebenstelle der zentralen LMU-Anlage, Spracherkennung
auf einer GPU-VM.

**Geschrieben, aber nie gegen echte Modelle gelaufen:** die Adapter für
faster-whisper und Piper (die Pakete waren in der Entwicklungsumgebung nicht
installierbar) und die Asterisk-Anbindung (getestet gegen einen selbstgebauten
AudioSocket-Client, nicht gegen Asterisk). Die Sprachkette davor und dahinter
ist dagegen mit einem echten Browser samt simuliertem Mikrofon geprüft.

**Noch offen:**

* Automatischer Löschlauf für Transkripte (`retention_days` wird noch nicht
  durchgesetzt)
* Optionaler LLM-Klassifikator für freie Formulierungen
  (`flow.engine.Interpreter` ist die vorgesehene Einhängestelle)
* Anbindung an ein konkretes Fachsystem — bisher legt der Bot Vorgänge als
  JSON-Dateien ab oder ruft einen konfigurierbaren Webhook auf

## Lizenz

MIT
