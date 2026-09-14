# Entscheidungsbäume schreiben

Ein Baum ist eine YAML-Datei in `config/flows/`. Nach jeder Änderung:

```bash
make pruefen                      # findet Sackgassen, tote Knoten, offene Antworten
make spielen                      # Dialog im Terminal durchspielen
make graph                        # Mermaid-Diagramm für die Abstimmung mit der Fachabteilung
```

## Grundgerüst

```yaml
id: mein_baum
version: 1
start: begruessung

settings:
  max_attempts: 2          # Nachfragen je Frage, dann Eskalation
  timeout_s: 6             # Wartezeit auf eine Antwort
  min_confidence: 0.45     # unsichere Erkennung gilt als "nicht verstanden"
  escalation_node: weiterleitung

slots:                     # Gesprächsvariablen (Deklaration hilft der Prüfung)
  anliegen: { type: choice }
  matrikelnummer: { type: digits, sensitive: true }   # sensitive -> im Protokoll maskiert

global_commands:           # überall gültig, vor jeder Knotenlogik geprüft
  - { name: mensch, phrases: ["mitarbeiter", "mensch"], action: goto, target: weiterleitung, dtmf: "0" }
  - { name: wiederholen, phrases: ["nochmal", "wie bitte"], action: repeat }

nodes:
  ...
```

## Knotentypen

| Typ | Zweck | Pflichtfelder |
|---|---|---|
| `say` | Ansage, dann weiter | `text`, `next` |
| `ask` | Frage mit erwarteter Antwort | `text`, `expect`, `transitions` oder `next` |
| `confirm` | Ja/Nein-Rückfrage | `text`, `on_yes`, `on_no` |
| `branch` | Verzweigung nach Slot-Werten | `cases` (plus `next` als Default) |
| `action` | Fachaktion aufrufen | `action` |
| `transfer` | an Menschen übergeben | `target` |
| `hangup` | Gespräch beenden | — |

Ergänzend an jedem `ask`: `reprompt` (nach Missverstehen), `no_input_text` (nach
Schweigen), `on_no_match`, `on_no_input`, `max_attempts`, `timeout_s`,
`barge_in`.

## Erwartete Antworten (`expect`)

| Typ | Versteht unter anderem | Ergebniswert |
|---|---|---|
| `yes_no` | ja, genau, korrekt, passt / nein, nee, stimmt nicht | `"yes"` / `"no"` |
| `choice` | eigene Synonyme, unscharf gegen Verhörer | Optionsname |
| `number` | „sieben“, „einundzwanzig“, „2,5“ | Zahl |
| `digits` | „eins zwei drei“, „12345678“, Tastatureingabe | Ziffernfolge |
| `date` | heute, morgen, übermorgen, Dienstag, 14.3., 14. März | `"2026-03-14"` |
| `time` | 14:30, 14 Uhr 30, halb drei, viertel nach drei | `"14:30"` |
| `text` | beliebige Eingabe | Rohtext |

```yaml
  hauptmenue:
    type: ask
    text: Geht es um einen Termin oder eine Prüfung?
    reprompt: Bitte sagen Sie Termin oder Prüfung.
    slot: anliegen
    expect:
      type: choice
      options:
        termin: ["termin", "sprechstunde", "beratung"]
        pruefung: ["prüfung", "klausur", "note"]
      dtmf: { "1": termin, "2": pruefung }
    transitions:
      termin: termin_datum
      pruefung: pruefung_art
```

`digits` akzeptiert `length: 8`: Eine Matrikelnummer mit sieben Ziffern wird
dann *nicht* übernommen, sondern nachgefragt. Am Telefon ist das der wichtigste
Schutz gegen halb verstandene Nummern.

## Platzhalter

`{slot}` in Ansagen wird durch den erfassten Wert ersetzt:
`text: "Ich habe notiert: {name}, am {datum} um {uhrzeit} Uhr."`
Nicht gefüllte Platzhalter werden zu leerem Text — die Prüfung warnt vorher,
wenn ein Platzhalter zu keinem Slot gehört.

## Kontextvariablen

Neben den Slots setzt der Dienst selbst einige Variablen. Sie lassen sich in
Ansagen (`{naechste_sprechzeit}`) und in `branch`-Bedingungen verwenden:

| Variable | Wert |
|---|---|
| `innerhalb_sprechzeit` | `"ja"` / `"nein"` nach den Sprechzeiten in `config.yaml` |
| `naechste_sprechzeit` | „morgen um 9 Uhr“, „am Dienstag um 9 Uhr“ |
| `jetzt_datum`, `jetzt_uhrzeit`, `wochentag` | Zeitpunkt des Anrufs |
| `caller`, `called` | Rufnummern, soweit die Anlage sie liefert |
| `last_error` | Fehlermeldung der zuletzt gescheiterten Fachaktion |
| `escalation_reason` | `no_match` oder `no_input` nach zu vielen Versuchen |

So nutzt der Beispielbaum die Sprechzeit, statt ins Leere zu verbinden:

```yaml
  weiterleitung_pruefen:
    type: branch
    cases:
      - when: [{ slot: innerhalb_sprechzeit, op: eq, value: "nein" }]
        next: weiterleitung_nicht_moeglich
    next: weiterleitung

  weiterleitung_nicht_moeglich:
    type: say
    text: >
      Das Sekretariat ist gerade nicht besetzt, wieder erreichbar
      {naechste_sprechzeit}. Ich notiere Ihnen einen Rueckruf.
    next: rueckruf_name
```

Sprechzeiten stehen in `config.yaml` unter `sprechzeiten`; ohne Konfiguration
gilt der Betrieb als durchgehend erreichbar.

## Was die Prüfung findet

| Code | Bedeutung |
|---|---|
| `dangling_edge` | Übergang auf einen Knoten, den es nicht gibt |
| `dead_end` | von hier aus ist kein Gesprächsende erreichbar |
| `unhandled_option` | eine Antwortmöglichkeit hat keinen Übergang |
| `unknown_transition` | ein Übergang passt zu keiner Antwortmöglichkeit |
| `missing_branch` | `confirm` ohne `on_yes`/`on_no` |
| `unreachable` (Warnung) | Knoten, den kein Pfad erreicht |
| `unknown_placeholder` (Warnung) | `{name}` ohne passenden Slot |

Beim Start des Dienstes wird streng geladen: Ein Baum mit Fehlern geht gar nicht
erst in Betrieb.

## Erfahrungswerte für Telefondialoge

1. **Höchstens drei Auswahlmöglichkeiten pro Frage.** Wer mehr anbietet, bekommt
   „ähm“ als Antwort.
2. **Frage ans Ende der Ansage.** Anrufer antworten auf das, was sie zuletzt
   gehört haben.
3. **Immer einen Weg zum Menschen** — als globales Kommando *und* auf der Null.
   Eine Schleife ohne Ausweg ist der häufigste Grund für Beschwerden.
4. **Zweimal nachfragen, dann weiterleiten.** Ab dem dritten Versuch ist die
   Wahrscheinlichkeit auf Erfolg gering und der Ärger groß.
5. **Erfasste Daten zurücklesen** (`confirm`), bevor etwas angelegt wird.
6. **Reprompt anders formulieren als die Frage.** Wörtliche Wiederholung wirkt
   wie ein Defekt; der Reprompt sollte die Antwortmöglichkeiten explizit nennen.
7. **Zahlen ziffernweise erfragen** und die Länge prüfen.
8. **Im ersten Satz sagen, dass es ein Automat ist.** Rechtlich geboten und
   praktisch hilfreich: Anrufer sprechen dann deutlicher und kürzer.

## YAML-Fallstrick

`yes`, `no`, `on`, `off` liest YAML als Wahrheitswerte. Der Loader fängt das ab
und macht daraus wieder `"yes"`/`"no"`, sodass

```yaml
    transitions:
      yes: termin      # wird korrekt als "yes" verstanden
      no: verabschiedung
```

funktioniert. Deutlicher ist trotzdem, die Schlüssel zu quoten.
