/*
 * Sprachclient: Mikrofon rein, Ansagen raus.
 *
 * Aufnahme:  Mikrofon -> AudioWorklet -> auf 8 kHz herunterrechnen -> PCM16
 *            -> WebSocket (binaer, 20-ms-Bloecke, wie bei der Telefonanlage)
 * Wiedergabe: PCM16 vom Server -> AudioBuffer -> lueckenlos eingeplant.
 *
 * Alles laeuft gegen den lokalen Dienst; es geht kein Audio ins Netz.
 */
(function () {
  "use strict";

  var ABTASTRATE = 8000;
  var BLOCK_MS = 20;
  var BLOCK_SAMPLES = ABTASTRATE * BLOCK_MS / 1000;   // 160

  var el = function (id) { return document.getElementById(id); };
  var ws = null, aufnahmeKontext = null, wiedergabeKontext = null, mikro = null;
  var rest = new Float32Array(0), abspielzeit = 0, laufendeQuellen = [], verbunden = false;
  var pegelWert = 0;

  /* ------------------------------------------------------------- Verbindung */

  async function verbinden() {
    if (verbunden) return;
    setzeStatus("verbinde", "Mikrofon wird angefragt …");

    var strom;
    try {
      strom = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,   // sonst haelt die VAD die eigene Ansage fuer Sprache
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1
        }
      });
    } catch (fehler) {
      setzeStatus("fehler", "Kein Zugriff auf das Mikrofon: " + fehler.name);
      protokoll("system", "Der Browser hat das Mikrofon nicht freigegeben. Die Seite muss über " +
        "localhost oder HTTPS laufen, und die Berechtigung muss erteilt sein.", "warnung");
      return;
    }

    aufnahmeKontext = new (window.AudioContext || window.webkitAudioContext)();
    wiedergabeKontext = new (window.AudioContext || window.webkitAudioContext)();
    abspielzeit = wiedergabeKontext.currentTime;

    var adresse = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws";
    ws = new WebSocket(adresse);
    ws.binaryType = "arraybuffer";

    ws.onopen = async function () {
      verbunden = true;
      setzeStatus("laeuft", "Verbunden – sprechen Sie");
      el("verbinden").disabled = true;
      el("auflegen").disabled = false;
      await starteAufnahme(strom);
    };
    ws.onmessage = empfangen;
    ws.onclose = function () {
      verbunden = false;
      setzeStatus("beendet", "Verbindung beendet");
      beendeAufnahme();
      el("verbinden").disabled = false;
      el("auflegen").disabled = true;
    };
    ws.onerror = function () { setzeStatus("fehler", "Verbindungsfehler"); };
  }

  function auflegen() {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ typ: "auflegen" }));
    }
    beendeAufnahme();
  }

  /* --------------------------------------------------------------- Aufnahme */

  async function starteAufnahme(strom) {
    var quelle = aufnahmeKontext.createMediaStreamSource(strom);
    try {
      await aufnahmeKontext.audioWorklet.addModule("aufnahme.js");
      var knoten = new AudioWorkletNode(aufnahmeKontext, "aufnahme");
      knoten.port.onmessage = function (nachricht) { verarbeiteBlock(nachricht.data); };
      quelle.connect(knoten);
      knoten.connect(aufnahmeKontext.destination);   // Worklet braucht eine Senke
      mikro = { quelle: quelle, knoten: knoten, strom: strom };
    } catch (fehler) {
      // Aeltere Browser: ScriptProcessor als Rueckfallebene.
      var prozessor = aufnahmeKontext.createScriptProcessor(2048, 1, 1);
      prozessor.onaudioprocess = function (ereignis) {
        verarbeiteBlock(new Float32Array(ereignis.inputBuffer.getChannelData(0)));
      };
      quelle.connect(prozessor);
      prozessor.connect(aufnahmeKontext.destination);
      mikro = { quelle: quelle, knoten: prozessor, strom: strom };
    }
  }

  function beendeAufnahme() {
    if (mikro) {
      try { mikro.quelle.disconnect(); mikro.knoten.disconnect(); } catch (e) { /* egal */ }
      mikro.strom.getTracks().forEach(function (spur) { spur.stop(); });
      mikro = null;
    }
    if (aufnahmeKontext) { aufnahmeKontext.close(); aufnahmeKontext = null; }
    pegel(0);
  }

  /**
   * Mikrofonblock auf 8 kHz herunterrechnen und als PCM16 verschicken.
   *
   * Der Browser nimmt mit 44,1 oder 48 kHz auf, die Telefonie arbeitet mit 8 kHz.
   * Es wird immer genau ein 20-ms-Fenster auf einmal umgerechnet; was nicht fuer
   * ein volles Fenster reicht, bleibt fuer den naechsten Aufruf liegen. Der
   * Mittelwert ueber die zusammengefassten Werte wirkt als einfacher Tiefpass.
   */
  function verarbeiteBlock(block) {
    if (!ws || ws.readyState !== WebSocket.OPEN || !aufnahmeKontext) return;

    var gesamt = new Float32Array(rest.length + block.length);
    gesamt.set(rest, 0);
    gesamt.set(block, rest.length);

    var proFenster = Math.round(aufnahmeKontext.sampleRate * BLOCK_MS / 1000);
    var faktor = proFenster / BLOCK_SAMPLES;
    var verbraucht = 0, summe = 0, gezaehlt = 0;

    while (gesamt.length - verbraucht >= proFenster) {
      var pcm = new Int16Array(BLOCK_SAMPLES);
      for (var k = 0; k < BLOCK_SAMPLES; k++) {
        var von = verbraucht + Math.floor(k * faktor);
        var bis = verbraucht + Math.floor((k + 1) * faktor);
        var mittel = 0, anzahl = 0;
        for (var j = von; j < bis; j++) { mittel += gesamt[j]; anzahl++; }
        var wert = anzahl ? mittel / anzahl : 0;
        wert = Math.max(-1, Math.min(1, wert));
        pcm[k] = wert < 0 ? wert * 32768 : wert * 32767;
        summe += wert * wert;
        gezaehlt++;
      }
      ws.send(pcm.buffer);
      verbraucht += proFenster;
    }

    rest = gesamt.slice(verbraucht);
    if (gezaehlt) pegel(Math.sqrt(summe / gezaehlt));
  }

  /* -------------------------------------------------------------- Wiedergabe */

  function empfangen(ereignis) {
    if (typeof ereignis.data !== "string") return spieleAb(ereignis.data);
    var nachricht;
    try { nachricht = JSON.parse(ereignis.data); } catch (fehler) { return; }

    switch (nachricht.typ) {
      case "bereit": bereit(nachricht); break;
      case "bot": protokoll("bot", nachricht.text, "", nachricht.knoten); zustand(nachricht); break;
      case "user":
        protokoll("anrufer", nachricht.text || "(nichts verstanden)", "",
          nachricht.daten && nachricht.daten.konfidenz != null
            ? "Konfidenz " + Number(nachricht.daten.konfidenz).toFixed(2) : "");
        zustand(nachricht);
        break;
      case "dtmf": protokoll("anrufer", "Taste " + nachricht.text); break;
      case "action": protokoll("system", "Fachaktion: " + nachricht.text, "erfolg"); zustand(nachricht); break;
      case "system": protokoll("system", nachricht.text, "warnung"); zustand(nachricht); break;
      case "abbrechen": leereWiedergabe(); break;
      case "ansage_beginnt": el("sprecher").textContent = "Bot spricht …"; break;
      case "ansage_endet": el("sprecher").textContent = ""; break;
      case "ergebnis": ergebnis(nachricht); break;
      case "ende": setzeStatus("beendet", "Gespräch beendet (" + nachricht.grund + ")"); break;
    }
  }

  function spieleAb(puffer) {
    var pcm = new Int16Array(puffer);
    var daten = new Float32Array(pcm.length);
    for (var i = 0; i < pcm.length; i++) daten[i] = pcm[i] / 32768;

    var audio = wiedergabeKontext.createBuffer(1, daten.length, ABTASTRATE);
    audio.getChannelData(0).set(daten);
    var quelle = wiedergabeKontext.createBufferSource();
    quelle.buffer = audio;
    quelle.connect(wiedergabeKontext.destination);

    var jetzt = wiedergabeKontext.currentTime;
    if (abspielzeit < jetzt + 0.02) abspielzeit = jetzt + 0.02;
    quelle.start(abspielzeit);
    abspielzeit += audio.duration;
    laufendeQuellen.push(quelle);
    quelle.onended = function () {
      var stelle = laufendeQuellen.indexOf(quelle);
      if (stelle >= 0) laufendeQuellen.splice(stelle, 1);
    };
  }

  /** Barge-in: alles Eingeplante verwerfen, damit der Bot sofort schweigt. */
  function leereWiedergabe() {
    laufendeQuellen.forEach(function (quelle) {
      try { quelle.stop(); } catch (fehler) { /* schon beendet */ }
    });
    laufendeQuellen = [];
    abspielzeit = wiedergabeKontext ? wiedergabeKontext.currentTime : 0;
    el("sprecher").textContent = "";
  }

  /* ---------------------------------------------------------------- Anzeige */

  function bereit(nachricht) {
    el("technik").textContent = nachricht.erkenner + " · " + nachricht.ausgabe +
      " · " + nachricht.abtastrate + " Hz";
    el("flowname").textContent = nachricht.flow + " v" + nachricht.version;
    el("sprechzeit").textContent = nachricht.sprechzeit === "ja" ? "besetzt" : "nicht besetzt";
    protokoll("system", "Verbunden als " + nachricht.anruf + ". Das Gespräch beginnt.");
  }

  function zustand(nachricht) {
    var z = nachricht.zustand;
    if (!z) return;
    el("knoten").textContent = z.knoten || "—";
    el("knotentyp").textContent = z.knotentyp || "—";
    el("sprechzeit").textContent = z.sprechzeit === "ja" ? "besetzt" : "nicht besetzt";
    var ziel = el("slots");
    ziel.innerHTML = "";
    var namen = Object.keys(z.slots || {});
    if (!namen.length) {
      ziel.innerHTML = '<span class="leer">noch nichts erfasst</span>';
      return;
    }
    namen.forEach(function (name) {
      var zeile = document.createElement("div");
      zeile.className = "paar";
      var dt = document.createElement("dt");
      dt.textContent = name;
      var dd = document.createElement("dd");
      dd.textContent = String(z.slots[name]);
      zeile.appendChild(dt);
      zeile.appendChild(dd);
      ziel.appendChild(zeile);
    });
  }

  function ergebnis(nachricht) {
    var text = "Ergebnis: " + nachricht.grund + " nach " + nachricht.dauer_s + " s";
    if (nachricht.weiterleitung) text += " · Weiterleitung an " + nachricht.weiterleitung;
    protokoll("system", text, "erfolg");
  }

  function protokoll(art, text, klasse, quelle) {
    if (!text) return;
    var behaelter = document.createElement("div");
    behaelter.className = "zeile " + art + (klasse ? " " + klasse : "");
    if (quelle) {
      var q = document.createElement("span");
      q.className = "quelle";
      q.textContent = quelle;
      behaelter.appendChild(q);
    }
    var inhalt = document.createElement("div");
    inhalt.className = "inhalt";
    inhalt.textContent = text;
    behaelter.appendChild(inhalt);
    el("verlauf").appendChild(behaelter);
    el("verlauf").scrollTop = el("verlauf").scrollHeight;
  }

  function pegel(wert) {
    pegelWert = pegelWert * 0.7 + wert * 0.3;
    el("pegel").style.width = Math.min(100, Math.round(pegelWert * 400)) + "%";
  }

  function setzeStatus(zustandName, text) {
    el("status").dataset.zustand = zustandName;
    el("statustext").textContent = text;
  }

  /* --------------------------------------------------------------- Bedienung */

  el("verbinden").addEventListener("click", verbinden);
  // "?auto=1" startet den Anruf ohne Klick -- fuer Vorfuehrungen und fuer die
  // automatische Pruefung mit einem Browser samt simuliertem Mikrofon.
  if (new URLSearchParams(location.search).get("auto") === "1") {
    window.addEventListener("load", function () { verbinden(); });
  }
  el("auflegen").addEventListener("click", auflegen);
  "123456789*0#".split("").forEach(function (taste) {
    var knopf = document.createElement("button");
    knopf.type = "button";
    knopf.textContent = taste;
    knopf.addEventListener("click", function () {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ typ: "dtmf", taste: taste }));
        protokoll("anrufer", "Taste " + taste);
      }
    });
    el("tasten").appendChild(knopf);
  });
})();
