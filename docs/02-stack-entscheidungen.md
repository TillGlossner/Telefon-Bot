# Technologieentscheidungen

Stand: September 2026. Jede Entscheidung mit Alternative und Begründung, damit
sie später überprüfbar bleibt.

## Spracherkennung: faster-whisper (Whisper large-v3)

**Gewählt**, weil Whisper für deutsches Telefonaudio (8 kHz, schmalbandig,
Nebengeräusche) der robusteste frei verfügbare Erkenner ist und mit
CTranslate2/int8 auch ohne dicke GPU brauchbar läuft. Modelle liegen lokal, es
verlässt kein Audio das Haus.

| Modell | Hardware | Erwartete Latenz auf 5 s Audio | Einsatz |
|---|---|---|---|
| `large-v3` | GPU ≥ 8 GB | 0,3–0,6 s | Standard, beste Qualität |
| `distil-large-v3` | GPU ≥ 6 GB | 0,2–0,4 s | wenn Latenz wichtiger als letzte Prozente |
| `medium` | CPU, 8 Kerne | 1,5–3 s | kleine VM ohne GPU |
| `small` | CPU, 4 Kerne | 0,8–1,5 s | Notlösung, spürbar mehr Fehler |

Diese Werte sind Richtwerte aus der Praxis, **nicht auf LMU-Hardware gemessen**.
Vor der Modellwahl `scripts/benchmark_asr.py` mit echten Telefonaufnahmen laufen
lassen.

Da für dieses Projekt eine **GPU-VM** vorgesehen ist, steht die
Beispielkonfiguration auf `large-v3` mit `device: cuda` und
`compute_type: float16`. Reicht der GPU-Speicher nicht, ist
`int8_float16` der nächste Schritt, danach `distil-large-v3`.

*Alternativen:* NVIDIA Parakeet/Canary (schnell, deutsches Telefonaudio schwächer
abgedeckt), WhisperX (Wortzeitstempel, für uns nicht nötig), Cloud-Dienste
(scheiden aus Datenschutzgründen aus).

*Stellschraube:* `asr.initial_prompt` mit Fachbegriffen („Matrikelnummer“,
„Prüfungsamt“, Lehrstuhlname) hebt die Trefferquote bei Eigennamen deutlich —
die billigste Qualitätsverbesserung im ganzen System.

## Sprachausgabe: Piper

**Gewählt**, weil Piper in Echtzeit auf der CPU synthetisiert, brauchbare
deutsche Stimmen mitbringt (`de_DE-thorsten-high`) und pro Stimme nur zwei
Dateien braucht. Feste Ansagen landen im WAV-Cache und kosten danach null
Latenz.

*Alternativen:* XTTS-v2/Kokoro (natürlicher, brauchen GPU und deutlich mehr
Zeit), MaryTTS (veraltet), eingesprochene Ansagen (beste Qualität — für feste
Texte ernsthaft erwägenswert, scheitert an Platzhaltern wie Datum und
Vorgangsnummer).

Am Telefon zählt Verständlichkeit mehr als Natürlichkeit: `length_scale: 1.05`
spricht bewusst etwas langsamer.

## Sprachaktivitätserkennung: Energie-VAD, optional Silero

Die mitgelieferte Energie-VAD führt den Grundrauschpegel nach und braucht kein
Modell. Für Telefonie reicht das meistens. Bei schwierigen Leitungen lässt sich
Silero-VAD (ONNX) über dieselbe Schnittstelle einhängen.

Die VAD bestimmt zwei Dinge, die den Eindruck des Bots stärker prägen als die
Erkennungsqualität: wann er merkt, dass man fertig ist (`end_silence_s`), und ob
man ihm ins Wort fallen darf (Barge-in).

## Telefonie: Asterisk + AudioSocket

**Gewählt**, weil AudioSocket rohes PCM über eine simple TCP-Verbindung liefert,
keinen zusätzlichen Mediaserver braucht und vollständig on-premise läuft. Das
Protokoll ist so klein, dass es hier vollständig implementiert und getestet ist.

*Alternativen:* ARI + `externalMedia` (mächtiger, mehr bewegliche Teile, erlaubt
dafür Weiterverbinden aus der Anwendung heraus), FreeSWITCH mod_audio_stream
(gleichwertig, wenn ohnehin FreeSWITCH steht), SIP direkt im Python-Prozess
(spart Asterisk, handelt sich RTP, Jitter, Codecs und NAT ein — nicht empfohlen).

**Offener Punkt:** Ob die vorhandene Asterisk-Version DTMF über AudioSocket
weiterreicht, ist versionsabhängig. Der Bot verarbeitet DTMF-Rahmen, wenn sie
kommen; andernfalls müssen Tasteneingaben im Dialplan eingesammelt werden. Das
ist beim ersten Test mit echter Anlage zu prüfen (siehe `docs/04`).

## Dialogsteuerung: Entscheidungsbaum in YAML, kein LLM

Der Baum ist deterministisch, versionierbar, im Diff lesbar und statisch
prüfbar (Sackgassen, tote Knoten, unbehandelte Antworten). Fachabteilungen
können Ansagen ändern, ohne Python anzufassen.

Ein LLM würde freiere Gespräche erlauben, aber Nachvollziehbarkeit,
Prüfbarkeit, Latenz und Datenschutzargumentation verschlechtern. Wenn freie
Formulierungen zum Problem werden, ist der richtige Schritt ein **lokales LLM
als Klassifikator vor dem Baum** („welcher Menüpunkt passt zu dieser
Äußerung?“) — die Entscheidung bleibt beim Baum. Die Schnittstelle dafür ist
`flow.engine.Interpreter`; ein Regel-Interpreter ist vorhanden.

## Sprache der Codebasis: Deutsch

Bezeichner im Fachbereich (Flows, Slots, Ansagen, Transkriptfelder) sind
deutsch, weil die Fachabteilung damit arbeitet. Technische Schnittstellen
bleiben englisch. Kommentare und Dokumentation sind deutsch.

## Hardware-Empfehlung

| Betriebsart | CPU | RAM | GPU | Parallele Gespräche |
|---|---|---|---|---|
| Erprobung | 4 Kerne | 8 GB | — | 1–2 (Modell `small`/`medium`) |
| Regelbetrieb | 8 Kerne | 16 GB | RTX 4000 / A2000, 8–16 GB | 4–8 |
| Ausbau | 16 Kerne | 32 GB | L4 / A10 | 10–20 |

Die GPU wird fast ausschließlich von der Spracherkennung belegt. Der übrige
Bot ist rechnerisch anspruchslos.
