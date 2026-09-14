# Mit dem Bot sprechen

Der Bot lässt sich vollständig ausprobieren, bevor eine Telefonanlage
angebunden ist: Mikrofon im Browser, Audio über eine WebSocket-Verbindung an
den lokalen Dienst, dort dieselbe Spracherkennung, derselbe Entscheidungsbaum
und dieselbe Sprachausgabe wie am Telefon.

```
Mikrofon ──> Browser ──WebSocket, PCM 8 kHz──> Telefonbot ──> Whisper ──> Baum ──> Piper ──> Lautsprecher
```

Es geht dabei **kein Audio ins Netz**. Der Dienst hört auf `127.0.0.1`, die
Modelle liegen auf der Platte.

## Starten

```bash
pip install ".[asr,tts]"
python scripts/modelle_laden.py            # einmalig: Whisper + Piper
cp config/config.example.yaml config/config.yaml

telefonbot sprechen -c config/config.yaml  # oder: make sprechen
```

Dann `http://127.0.0.1:8099` im Browser öffnen und auf **Anrufen** drücken.

Der erste Start dauert, bis das Whisper-Modell geladen ist; die Ansagen werden
dabei gleich mit vorsynthetisiert und landen im Cache.

## Zwei Dinge, die sonst Zeit kosten

**Kopfhörer aufsetzen.** Über Lautsprecher hört der Bot seine eigene Ansage und
hält sie für eine Antwort — das ist kein Fehler, sondern genau das Problem, das
eine Telefonanlage mit Echokompensation löst. Der Client bittet den Browser um
Echounterdrückung, verlässlich ist das aber nicht.

**Das Mikrofon gibt der Browser nur auf `localhost` oder über HTTPS frei.** Wer
den Dienst auf einer anderen Maschine laufen lässt, braucht einen SSH-Tunnel:

```bash
ssh -L 8099:127.0.0.1:8099 benutzer@gpu-vm.lmu.de
```

Danach ist `http://127.0.0.1:8099` lokal, und das Mikrofon funktioniert.

## Was dabei ausprobiert werden kann

* **Erkennungsqualität** — versteht Whisper Namen, Matrikelnummern, Dialekt?
  Die Konfidenz jeder Äußerung steht neben der Zeile im Verlauf.
* **Timing** — kommt die Antwort schnell genug? Wird zu früh abgeschnitten?
  Stellschrauben: `vad.end_silence_s` und die Modellgröße.
* **Barge-in** — dem Bot ins Wort fallen; die Ansage muss sofort verstummen.
* **Ansagen** — wie klingt der Text tatsächlich gesprochen? Abkürzungen,
  Zahlen und Eigennamen klingen vorgelesen oft anders als gedacht.
* **Tasten** — die Tastatur rechts schickt DTMF wie am Telefon.

Erkannte Äußerungen zu Slots, die als `sensitive` deklariert sind, erscheinen
als `***` — im Protokoll wie in der Anzeige. Der Entscheidungsbaum bekommt
weiterhin den echten Text.

## Wie es technisch funktioniert

| Richtung | Inhalt |
|---|---|
| Browser → Dienst | Binär: PCM 16 bit, 8 kHz, 20-ms-Blöcke. Text: `{"typ":"dtmf","taste":"1"}`, `{"typ":"auflegen"}` |
| Dienst → Browser | Binär: PCM 16 bit, 8 kHz, im Echtzeittakt. Text: Verlauf, Zustand, `{"typ":"abbrechen"}` bei Barge-in |

Der Browser nimmt mit 44,1 oder 48 kHz auf; der Client rechnet blockweise auf
8 kHz herunter, damit der Dienst exakt dasselbe Signalformat sieht wie von der
Telefonanlage. Die Ausgabe wird im 20-ms-Takt gesendet — ohne diese Taktung
läge die ganze Ansage sofort im Puffer und Barge-in ginge ins Leere.

Serverseitig ist das derselbe `CallSession`-Ablauf wie bei AudioSocket, nur mit
einem anderen Transport (`telefonbot.telephony.browser.BrowserTransport`).
WebSocket ist in `telefonbot.net.websocket` selbst umgesetzt — damit bleibt der
Dienst ohne Fremdpakete installierbar.

## Wenn etwas nicht funktioniert

| Symptom | Ursache |
|---|---|
| „Kein Zugriff auf das Mikrofon“ | Seite läuft nicht über `localhost`/HTTPS, oder die Berechtigung fehlt |
| Bot reagiert nicht auf Sprache | Pegelbalken beobachten: bleibt er leer, nimmt der Browser das falsche Gerät auf |
| Bot unterbricht sich selbst | Lautsprecher statt Kopfhörer; sonst `vad.margin_db` erhöhen |
| Lange Pause vor der Antwort | Modell zu groß für die Maschine — `scripts/benchmark_asr.py` misst es |
| Ansage klingt abgehackt | Auslastung: parallele Gespräche oder CPU-Betrieb mit großem Modell |

## Was das *nicht* ersetzt

Die Sprechprobe läuft über ein Breitbandmikrofon in einem ruhigen Raum. Echte
Telefonie ist 8 kHz aus einem Mobilfunknetz, mit Störungen, Freisprechanlagen
und Hintergrundgeräuschen. Die Erkennungsqualität dort ist messbar schlechter —
verlässliche Zahlen liefern nur echte Anrufe (siehe `docs/06-testkonzept.md`).
