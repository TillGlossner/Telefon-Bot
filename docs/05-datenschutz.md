# Datenschutz und rechtliche Rahmenbedingungen

**Kein Rechtsrat.** Diese Seite fasst zusammen, was technisch vorgesehen ist und
was vor dem Produktivbetrieb mit dem Datenschutzbeauftragten der LMU und ggf.
dem Personalrat geklärt werden muss.

## Was das System verarbeitet

| Daten | Wo | Aufbewahrung |
|---|---|---|
| Gesprochene Sprache (Audio) | nur im Arbeitsspeicher, blockweise | wird nicht gespeichert (Standard) |
| Transkripte der Äußerungen | `var/transkripte/*.jsonl` | konfigurierbar, Standard 30 Tage |
| Erfasste Slots (Name, Rufnummer, Matrikelnummer) | Transkript und Vorgang | wie Transkript bzw. Fachsystem |
| Rufnummer des Anrufers | Transkript, gekürzt | wie Transkript |
| Modelle, Ansagen-Cache | lokal | dauerhaft, keine Personenbezüge |

**Es verlässt kein Audio und kein Text das System.** Spracherkennung und
Sprachsynthese laufen lokal; es gibt keinen Cloud-Aufruf im Gesprächspfad. Das
ist der wesentliche Grund für diese Architektur.

## Eingebaute Schutzmaßnahmen

* **Kein Audiomitschnitt im Standardbetrieb** (`transcripts.store_audio: false`).
* **Maskierung sensibler Slots:** Als `sensitive: true` deklarierte Slots
  erscheinen im Transkript als `***`. Im Beispielbaum betrifft das Name,
  Rufnummer und Matrikelnummer.
* **Gekürzte Rufnummern** im Protokoll (Datensparsamkeit).
* **Hinweis auf den Automaten im ersten Satz** des Beispielbaums.
* **Lokale Control-API ohne Außenanbindung**, systemd-Unit mit eingeschränkten
  Rechten und gesperrtem ausgehendem Netz.

## Was noch zu klären ist

1. **Rechtsgrundlage.** Für eine staatliche Hochschule kommt in der Regel
   Art. 6 Abs. 1 lit. e DSGVO in Verbindung mit dem BayHIG/BayDSG in Betracht
   (Aufgabenerfüllung). Zu prüfen und im Verfahrensverzeichnis zu dokumentieren.
2. **Informationspflichten (Art. 13 DSGVO).** Der Anrufer muss erfahren, wer
   verarbeitet, wozu, wie lange und welche Rechte er hat. Am Telefon praktisch:
   kurzer Hinweis in der Ansage plus Verweis auf die Datenschutzerklärung der
   Einrichtung. Die Begrüßung im Beispielbaum enthält den Automatenhinweis, ist
   aber **noch keine vollständige Information** — Formulierung mit dem
   Datenschutzbeauftragten abstimmen.
3. **Aufzeichnung.** Das Mitschneiden von Gesprächen ohne Einwilligung aller
   Beteiligten ist in Deutschland nicht nur datenschutzrechtlich problematisch,
   sondern nach § 201 StGB strafbewehrt. `store_audio` deshalb nur mit
   ausdrücklicher, dokumentierter Einwilligung am Gesprächsanfang und mit
   Löschfrist einschalten — auch für Testaufnahmen zur Qualitätsmessung.
4. **Verfahrensverzeichnis (Art. 30 DSGVO)** anlegen; je nach Umfang der
   verarbeiteten Daten ist eine Datenschutz-Folgenabschätzung zu prüfen.
5. **Beschäftigtendaten.** Wenn Gespräche von Beschäftigten betroffen sind oder
   Auswertungen Rückschlüsse auf deren Arbeit zulassen, ist der Personalrat zu
   beteiligen.
6. **Löschung umsetzen.** `transcripts.retention_days` ist aktuell nur ein
   dokumentierter Wert; ein Löschlauf (Cron oder systemd-Timer) fehlt noch —
   siehe offene Punkte im README.
7. **Barrierefreiheit.** Ein Sprachdialog ist nicht für alle Anrufer nutzbar.
   Die Tastenbedienung und der jederzeit erreichbare Mensch sind dafür die
   Mindestausstattung (BITV 2.0 / BayBGG beachten).

## Löschung von Hand

```bash
find /var/lib/telefonbot/transkripte -name '*.jsonl' -mtime +30 -delete
find /var/lib/telefonbot/vorgaenge  -name '*.json'  -mtime +90 -delete
```

Als systemd-Timer einrichten, sobald die Fristen festgelegt sind.
