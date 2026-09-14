# Testkonzept

## Was automatisch getestet ist

`make test` — 189 Tests, Laufzeit rund 40 Sekunden (davon 22 s der Browsertest), ohne Installation von
Fremdpaketen, ohne Modelle, ohne Telefonanlage.

| Bereich | Umfang |
|---|---|
| Deutsche Parser | Ja/Nein inkl. Negation, Zahlwörter, Ziffernfolgen, Datum (relativ, numerisch, Monatsname, Wochentag), Uhrzeit (auch „halb drei“, „dreiviertel vier“) |
| Regel-Verstehen | Synonyme, unscharfe Treffer, Mehrdeutigkeit, DTMF-Vorrang, Wertebereiche, Längenprüfung |
| Baum-Loader | Kurzformen, Tippfehler in Feldnamen, unbekannte Typen, YAML-Wahrheitswert-Falle |
| Baum-Prüfung | Sackgassen, tote Knoten, offene Antworten, fehlende Zweige, Platzhalter |
| Engine | vollständige Pfade, Nachfragen, Eskalation, Bestätigung, globale Kommandos, Aktionsfehler, Zyklusschutz |
| Audio | Resampling, Pegel, WAV, Übersteuerung, VAD-Einpegelung, Segmentierung |
| Telefonie | AudioSocket-Rahmen (auch byteweise zerstückelt), echter TCP-Durchlauf gegen den Server, Überlastabweisung |
| Gespräch | ganze Telefonate gegen Fake-Telefonie: Sprache, Tasten, Barge-in, Schweigen, Auflegen, Aktionsfehler |
| Sprechzeiten | offen/geschlossen inkl. Mittagspause und Feiertagen, nächste Öffnung, fehlerhafte Angaben; beide Pfade des Beispielbaums (verbinden vs. Rückruf aufnehmen) |
| Sprachinterface | WebSocket-Rahmen (Maskierung, Fragmentierung, Längenformate, Steuerrahmen), Dateiauslieferung samt Pfadausbruch-Schutz, vollständige Gespräche über eine echte WebSocket-Verbindung: Sprache, Tasten, Barge-in, Auflegen, Maskierung sensibler Äußerungen |
| Browser | Ein echter Chromium mit simuliertem Mikrofon führt ein vollständiges Gespräch: Aufnahme, AudioWorklet, Herunterrechnen auf 8 kHz, Segmentierung, Baum, Rückweg als Audio (wird ohne Chromium übersprungen) |
| Werkzeuge | Konfiguration (YAML + Umgebung), Simulator, Diagramm, Control-API, CLI |

Die Gesprächstests laufen ohne Echtzeit: Der Fake-Transport taktet die
Wiedergabe über Kontrollabgaben statt über die Uhr, und der Segmentierer zählt
Blöcke statt Sekunden. Deshalb sind sie schnell und reproduzierbar.

## Browser-Demo

`demo/` bildet die Engine in JavaScript nach, damit der Baum ohne Installation
durchspielbar ist. Damit beides nicht auseinanderläuft:

* Der Baum wird von `scripts/demo_daten.py` aus derselben YAML exportiert, die
  der Dienst lädt — er ist nicht abgetippt.
* Aus den echten Python-Parsern werden 54 Eingabe-/Ergebnis-Paare erzeugt. Der
  Reiter „Selbsttest“ der Demo lässt die Portierung über dieselben Fälle laufen
  und zeigt jede Abweichung an.
* Nach Änderungen an Bäumen oder Parsern: `make demo` ausführen, sonst zeigt die
  Demo einen veralteten Stand.

Nicht abgebildet ist alles Akustische: Erkennung, Synthese, Sprechpausen und
Barge-in. Die Demo prüft den Dialog, nicht das Hören.

## Was **nicht** automatisch getestet ist

Das ist der ehrliche Teil der Liste — hier braucht es Hardware:

* **faster-whisper und Piper.** Die Adapter sind geschrieben, aber in dieser
  Umgebung nie gegen echte Modelle gelaufen (Pakete nicht installierbar). Der
  erste Lauf auf der Zielmaschine ist ein echter Test, kein Formalakt.
  Alles um die Modelle herum — Aufnahme, Segmentierung, Aufruf, Rückweg — ist
  dagegen im Browsertest durchlaufen; ausgetauscht sind nur Erkenner und
  Sprachausgabe.
* **Asterisk.** Der AudioSocket-Server ist gegen einen selbstgebauten Client
  getestet, nicht gegen Asterisk. Offen: ob DTMF-Rahmen kommen, ob die
  Weiterleitung über die Control-API im Dialplan sauber greift.
* **Echtes Telefonaudio.** Erkennungsqualität bei 8 kHz, Mobilfunk,
  Freisprecheinrichtung, Dialekt — nur messbar mit Aufnahmen.
* **Echo und Barge-in auf echter Leitung.** Wenn die Anlage das eigene Ansage-
  signal zurückspiegelt, kann die VAD es für Sprache halten. Gegenmittel:
  Echokompensation in Asterisk, `vad.margin_db` erhöhen.
* **Last.** Wie viele Gespräche die Maschine parallel schafft, entscheidet die
  GPU-Auslastung der Spracherkennung.

## Abnahme mit echter Anlage

1. **Durchstich:** ein Anruf, Baum `minimal_demo`, Ansagen hörbar, Auflegen wird
   erkannt.
2. **Tasten:** DTMF im Dialplan und über AudioSocket prüfen, Verhalten
   dokumentieren.
3. **Weiterleitung:** „Mitarbeiter“ sagen und die Null drücken; landet der
   Anruf im Sekretariat?
4. **Aufnahmen sammeln:** 20–30 echte Anrufe mitschneiden (mit Einwilligung!)
   und mit `scripts/benchmark_asr.py` auswerten. Ergebnis entscheidet über
   Modellgröße und `min_confidence`.
5. **Zeiten justieren:** `end_silence_s` und `timeout_s` anhand echter Anrufer
   nachziehen — Denkpausen sind länger, als man am Schreibtisch annimmt.
6. **Lasttest:** mehrere Gespräche parallel, `telefonbot_calls_active` und
   GPU-Auslastung beobachten.

## Qualität im Betrieb messen

Die Transkripte in `var/transkripte/` sind die wichtigste Quelle. Sinnvolle
wöchentliche Auswertung:

* Anteil der Gespräche, die im Entscheidungsbaum zu Ende gehen, gegen Anteil
  Weiterleitungen (`telefonbot_call_end_total`).
* Knoten mit den meisten Nachfragen — dort stimmt die Ansage nicht.
* Häufige Äußerungen, die auf keine Option passen — Kandidaten für neue
  Synonyme oder einen neuen Menüpunkt.
