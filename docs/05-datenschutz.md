# Datenschutz und rechtliche Rahmenbedingungen

**Kein Rechtsrat.** Diese Seite fasst zusammen, was technisch vorgesehen ist und
was vor dem Produktivbetrieb mit dem Datenschutzbeauftragten der LMU und ggf.
dem Personalrat geklärt werden muss.

## Was das System verarbeitet

| Daten | Wo | Aufbewahrung |
|---|---|---|
| Gesprochene Sprache (Audio) | nur im Arbeitsspeicher, blockweise | wird nicht gespeichert (Standard) |
| Transkripte der Äußerungen | `var/transkripte/*.jsonl` | konfigurierbar, Standard 30 Tage |
| Erfasste Slots (Name, Rufnummer, Terminbezug) | Transkript und Vorgang | wie Transkript bzw. Fachsystem |
| Rufnummer des Anrufers | Transkript, gekürzt | wie Transkript |
| Modelle, Ansagen-Cache | lokal | dauerhaft, keine Personenbezüge |

**Es verlässt kein Audio und kein Text das System.** Spracherkennung und
Sprachsynthese laufen lokal; es gibt keinen Cloud-Aufruf im Gesprächspfad. Das
ist der wesentliche Grund für diese Architektur.

## Eingebaute Schutzmaßnahmen

* **Kein Audiomitschnitt im Standardbetrieb** (`transcripts.store_audio: false`).
* **Maskierung sensibler Slots:** Als `sensitive: true` deklarierte Slots
  erscheinen im Transkript als `***` — und ebenso die Äußerung, mit der sie
  erfasst wurden. Die vorgelesene Rufnummer steht also nicht im Klartext
  daneben.
* **Gekürzte Rufnummern** im Protokoll (Datensparsamkeit).
* **Hinweis auf den Automaten im ersten Satz** des Beispielbaums.
* **Lokale Control-API ohne Außenanbindung**, systemd-Unit mit eingeschränkten
  Rechten und gesperrtem ausgehendem Netz.

## Zusätzlich im Klinikbetrieb

Ein Klinik-Sekretariat verarbeitet **Gesundheitsdaten nach Art. 9 DSGVO** — und
zwar schon dann, wenn jemand anruft: Die Tatsache, dass eine Person sich bei
einer bestimmten Klinik meldet, ist selbst ein Gesundheitsdatum. Dazu kommt die
**ärztliche Schweigepflicht (§ 203 StGB)**, die Strafrecht ist und nicht nur
Datenschutzrecht, und die sich auf Dienstleister und deren Unterauftragnehmer
erstreckt.

Genau deshalb ist dieses System lokal gebaut: Es gibt keinen Auftragsverarbeiter
und keinen Cloud-Dienst im Gesprächspfad. Die Diskussion über
Auftragsverarbeitungsverträge, Serverstandorte und Support-Zugriffe aus
Drittstaaten — bei den marktüblichen SaaS-Telefonassistenten der Kern der
Prüfung — entfällt.

Der Baum `config/flows/klinik_sekretariat.yaml` setzt fünf Regeln technisch um,
die im Klinikkontext nicht verhandelbar sind. Tests in
`tests/test_klinik_flow.py` halten sie fest:

1. **Der Notfallweg steht im ersten Satz**, und Notfallbegriffe führen an jeder
   Stelle des Dialogs sofort zum Hinweis auf 112 — ohne Menü, ohne Rückfrage,
   ohne Weiterleitung in eine mögliche Warteschleife.
2. **Keine Frage nach Beschwerden, Symptomen oder Dringlichkeit.** Das ist nicht
   nur fachlich geboten: Software, die Symptome erfasst und nach Dringlichkeit
   einstuft, kann ein Medizinprodukt nach MDR sein — mit Konformitätsbewertung,
   Risikomanagement und Marktüberwachung. Ein administrativer Telefondienst ist
   das nicht und darf es nicht werden.
3. **Keine Auskunft zu Befunden, Arztbriefen oder Behandlungsverhältnissen** —
   auch nicht indirekt durch Bestätigen, dass jemand Patient ist.
4. **Ärztliche Anrufer werden ohne Datenaufnahme durchgestellt.**
5. **Kein Freitext-Slot außer dem Namen.** Freitext ist die Stelle, an der
   ungewollt Diagnosen und Beschwerden ins Protokoll geraten. Erfasst werden
   nur Name, Rufnummer, Terminbezug und die grobe Anliegensart — Name,
   Rufnummer und Termindatum als `sensitive` und damit im Protokoll maskiert.

Zusätzlich zu klären, über die Punkte unten hinaus: Beteiligung des
Datenschutzbeauftragten des Klinikums, des Personalrats und gegebenenfalls der
Patientenfürsprache; Aufnahme ins Verfahrensverzeichnis des Klinikums, nicht
der Fakultät.

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
