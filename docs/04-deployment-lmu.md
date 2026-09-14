# Betrieb an der LMU

## Aufbau

Ausgangslage hier: Die Einrichtung bekommt **keine eigene Amtsleitung, sondern
eine Nebenstelle (Durchwahl) der zentralen Anlage**. Asterisk meldet sich mit
dieser Durchwahl an und dient nur als schlanker Vermittler vor dem Bot.

```
Zentrale Anlage der LMU ──SIP (Nebenstelle 12345)──> Asterisk (VM)
                                                          │ AudioSocket (localhost:8090)
                                                          ▼
                                                     Telefonbot
                                                          │
             Weiterleitung als neuer Anruf über die Anlage ┘ ──> Sekretariat (67890)
```

Asterisk und Bot laufen auf derselben Maschine; der AudioSocket-Port ist auf
`127.0.0.1` gebunden und braucht keine Firewallregel.

Konsequenzen dieser Variante:

* Die Weiterleitung geht **als neuer Anruf** über die zentrale Anlage
  (`Dial(PJSIP/67890@uni-pbx)`) und belegt dabei einen zweiten Kanal. Wo die
  Anlage SIP-REFER zulässt, ist `Transfer()` sparsamer — vorher testen.
* Gleichzeitige Gespräche sind durch die Nebenstelle begrenzt. Für mehr als
  ein paralleles Gespräch muss die Anlage mehrere Kanäle auf der Durchwahl
  erlauben; das ist beim Telefonie-Team zu erfragen.
* Die Rufnummer des Anrufers kommt nur, wenn die Anlage sie durchreicht.

## Voraussetzungen klären (vor der Technik)

Diese Punkte sind **keine Programmieraufgaben** und brauchen erfahrungsgemäß am
längsten:

1. **Nebenstelle und Zugangsdaten** — über den IT-Servicedesk bzw. das
   Telefonie-Team. Konkret zu erfragen:
   * Durchwahl und SIP-Zugangsdaten (Benutzer, Passwort, Registrar-Adresse)
   * erlaubte Codecs (meist G.711 a-law) und DTMF-Verfahren (RFC 4733?)
   * wie viele gleichzeitige Gespräche die Durchwahl erlaubt
   * ob SIP-REFER (Weiterverbinden) zugelassen ist
   * ob die Rufnummer des Anrufers durchgereicht wird
2. **VM oder Hardware** — siehe Hardware-Tabelle in `docs/02`. GPU-Kapazität
   gibt es an der LMU unter anderem über das LRZ.
3. **Datenschutz** — Verfahrensverzeichnis, Abstimmung mit dem Datenschutz-
   beauftragten, ggf. Personalrat. Siehe `docs/05`.
4. **Wer ist das Rückfallziel?** Ein Bot ohne erreichbaren Menschen dahinter ist
   keine Verbesserung.

## Installation (systemd, ohne Container)

```bash
sudo useradd --system --home /opt/telefonbot telefonbot
sudo mkdir -p /opt/telefonbot /etc/telefonbot /var/lib/telefonbot
sudo chown -R telefonbot:telefonbot /opt/telefonbot /var/lib/telefonbot

sudo -u telefonbot git clone <repo> /opt/telefonbot
cd /opt/telefonbot
sudo -u telefonbot python3.11 -m venv .venv
sudo -u telefonbot .venv/bin/pip install ".[asr,tts]"

# Modelle einmalig laden (danach ist kein Internetzugang mehr nötig)
sudo -u telefonbot .venv/bin/python scripts/modelle_laden.py --whisper large-v3 --piper thorsten-high

sudo cp config/config.example.yaml /etc/telefonbot/config.yaml
sudo cp deploy/systemd/telefonbot.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now telefonbot
```

Prüfen:

```bash
curl -s http://127.0.0.1:8091/health | python3 -m json.tool
journalctl -u telefonbot -f
```

Die mitgelieferte systemd-Unit sperrt ausgehende Netzverbindungen
(`IPAddressDeny=any`). Wenn Fachaktionen ein internes System aufrufen sollen,
muss dessen Adresse dort freigegeben werden.

## Installation (Container)

```bash
docker compose build
docker compose up -d telefonbot                   # nur der Bot
docker compose --profile telefonie up -d          # mit Asterisk
```

Modelle liegen als Volume unter `./models`, damit das Abbild klein bleibt und
der Container ohne Internetzugang startet.

## Asterisk anbinden

`deploy/asterisk/extensions.conf` enthält einen vollständigen Beispiel-Dialplan.
Kern:

```asterisk
exten => _X.,1,Answer()
 same => n,Set(BOTUUID=${UUID()})
 same => n,AudioSocket(${BOTUUID},127.0.0.1:8090)
 same => n,Set(ZIEL=${CURL(http://127.0.0.1:8091/calls/${BOTUUID}/transfer)})
 same => n,GotoIf($["${ZIEL}" = ""]?ende)
 same => n,Dial(${ZIEL},30,m)
 same => n(ende),Hangup()
```

Wichtig:

* `direct_media=no` — sonst läuft das Audio an Asterisk vorbei und der Bot
  bekommt nichts zu hören.
* `res_audiosocket.so` und `app_audiosocket.so` müssen geladen sein
  (`module show like audiosocket`).
* `func_curl.so` wird für die Weiterleitungsabfrage gebraucht.
* Das Weiterleitungsziel aus dem Baum (`PJSIP/sekretariat@uni-pbx`) wird im
  Dialplan auf die echte Durchwahl umgesetzt — Variable `SEKRETARIAT` in
  `extensions.conf`. So steht keine Durchwahl im Dialogbaum.

**Offener Punkt DTMF:** Ob Tastendrücke als AudioSocket-Rahmen ankommen, hängt
von der Asterisk-Version ab. Testen mit:

```bash
asterisk -rx "core set verbose 3"   # während des Anrufs Tasten drücken
```

Kommen keine DTMF-Rahmen an, gibt es zwei Wege: Tasteneingaben im Dialplan vor
dem AudioSocket-Aufruf einsammeln (`Read()`), oder auf ARI + `externalMedia`
umstellen. Der Bot funktioniert in beiden Fällen weiter — nur eben ohne Tasten
mitten im Gespräch.

## Netz und Firewall

| Port | Dienst | Sichtbarkeit |
|---|---|---|
| 5060/UDP, RTP-Bereich | Asterisk ↔ Telefonanlage | nur zur Anlage |
| 8090/TCP | AudioSocket | nur Asterisk, idealerweise localhost |
| 8091/TCP | Control-API | **nur localhost** — keine Authentisierung |

Die Control-API bewusst nie nach außen binden. Wer sie aus der Ferne braucht,
stellt einen authentisierenden Reverse-Proxy davor.

## Betrieb

```bash
curl -s localhost:8091/metrics     # Prometheus-Format
```

| Kennzahl | Bedeutung |
|---|---|
| `telefonbot_calls_total` | angenommene Anrufe |
| `telefonbot_calls_active` | laufende Gespräche |
| `telefonbot_transfers_total` | Weiterleitungen an Menschen |
| `telefonbot_call_end_total{reason=...}` | Gesprächsenden nach Grund |

Ein dauerhaft hoher Anteil `transferred` bedeutet: Der Baum trifft die Anliegen
nicht. Ein steigender Anteil `max_attempts_no_match` bedeutet: Ansagen oder
Synonyme nachbessern.

**Baum ändern im laufenden Betrieb:**

```bash
make pruefen                     # erst prüfen
sudo systemctl reload-or-restart telefonbot
```

Der Dienst lädt Bäume beim Start streng — ein fehlerhafter Baum verhindert den
Start, statt im Gespräch aufzufallen. Ein Neustart trennt laufende Gespräche;
außerhalb der Sprechzeiten neu starten.

## Wenn etwas nicht funktioniert

| Symptom | Wahrscheinliche Ursache |
|---|---|
| Anruf wird angenommen, aber es ist still | `direct_media=yes`, oder der Bot hört auf 127.0.0.1 und Asterisk läuft anderswo |
| Bot antwortet nie, Log zeigt keine Äußerung | VAD zu unempfindlich: `vad.margin_db` senken |
| Bot unterbricht sich selbst | Echo auf der Leitung: Echokompensation in Asterisk, `margin_db` erhöhen |
| Lange Pausen vor der Antwort | Modell zu groß für die Hardware, oder TTS-Cache kalt |
| Erste Ansage ist abgeschnitten | `session.greeting_delay_s` erhöhen |
| Erkennung versteht Eigennamen falsch | `asr.initial_prompt` mit Fachbegriffen füllen |
| Weiterleitung passiert nicht | `func_curl.so` fehlt, oder Control-API nicht erreichbar |
