/*
 * Portierung der Telefonbot-Engine nach JavaScript -- fuer die Browser-Demo.
 *
 * Der Produktivcode ist Python (src/telefonbot/). Diese Datei bildet die
 * Dialogsteuerung und das deutsche Sprachverstehen so nach, dass man einen
 * Entscheidungsbaum ohne Installation durchspielen kann. Der Selbsttest der
 * Demo laesst dieselben Pruefvektoren laufen, die die Python-Parser erzeugt
 * haben (demo/daten.js) -- Abweichungen fallen damit sofort auf.
 */
(function (global) {
  "use strict";

  /* ------------------------------------------------------------ Normalisierung */

  var UMLAUTE = { "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss" };

  function normalize(text) {
    text = (text || "").normalize("NFC").toLowerCase();
    text = text.replace(/[äöüß]/g, function (z) { return UMLAUTE[z]; });
    text = text.replace(/[^\p{L}\p{N}_\s:.,-]/gu, " ");
    // Punkt/Komma/Doppelpunkt nur zwischen Ziffern behalten ("14.3.", "2,5", "9:30").
    text = text.replace(/(?<!\d)[.,:]|[.,:](?!\d)/g, " ");
    return text.replace(/\s+/g, " ").trim();
  }

  function tokens(text) {
    return normalize(text).split(/[\s,.:-]+/).filter(Boolean);
  }

  /* ------------------------------------------------------------------ Ja/Nein */

  var JA = new Set(["ja", "jo", "jep", "jup", "joa", "jawohl", "klar", "genau", "richtig",
    "korrekt", "stimmt", "passt", "gerne", "bitte", "okay", "ok", "sicher", "absolut",
    "exakt", "positiv", "einverstanden", "yes"]);
  var NEIN = new Set(["nein", "ne", "nee", "noe", "nicht", "falsch", "negativ", "quatsch",
    "keinesfalls", "niemals", "no"]);
  var VERNEINER = new Set(["nicht", "kein", "keine", "keinen", "nein", "ne", "nee", "noe"]);

  function parseYesNo(text) {
    var woerter = tokens(text);
    if (!woerter.length) return null;
    var hatVerneiner = woerter.some(function (w) { return VERNEINER.has(w); });
    var hatJa = woerter.some(function (w) { return JA.has(w); });
    var hatNein = woerter.some(function (w) { return NEIN.has(w); });
    if (hatVerneiner) return false;          // "stimmt nicht" ist Nein, nicht Ja
    if (hatJa && !hatNein) return true;
    if (hatNein && !hatJa) return false;
    return null;
  }

  /* -------------------------------------------------------------------- Zahlen */

  var EINER = { null: 0, "null": 0, eins: 1, ein: 1, eine: 1, einen: 1, zwei: 2, zwo: 2,
    drei: 3, vier: 4, fuenf: 5, sechs: 6, sieben: 7, acht: 8, neun: 9, zehn: 10, elf: 11,
    zwoelf: 12, dreizehn: 13, vierzehn: 14, fuenfzehn: 15, sechzehn: 16, siebzehn: 17,
    achtzehn: 18, neunzehn: 19 };
  var ZEHNER = { zwanzig: 20, dreissig: 30, vierzig: 40, fuenfzig: 50, sechzig: 60,
    siebzig: 70, achtzig: 80, neunzig: 90 };
  var ORDINAL = { erster: 1, erste: 1, ersten: 1, zweiter: 2, zweite: 2, zweiten: 2,
    dritter: 3, dritte: 3, dritten: 3, vierter: 4, vierte: 4, vierten: 4, fuenfter: 5,
    fuenfte: 5, fuenften: 5, sechster: 6, sechste: 6, sechsten: 6, siebter: 7, siebte: 7,
    siebten: 7, siebenter: 7, siebente: 7, achter: 8, achte: 8, achten: 8, neunter: 9,
    neunte: 9, neunten: 9, zehnter: 10, zehnte: 10, zehnten: 10, elfter: 11, elfte: 11,
    elften: 11, zwoelfter: 12, zwoelfte: 12, zwoelften: 12 };

  function hat(tabelle, wort) { return Object.prototype.hasOwnProperty.call(tabelle, wort); }

  function parseNumberWord(wort) {
    wort = normalize(wort).replace(/\s/g, "");
    if (!wort) return null;
    if (/^\d+$/.test(wort)) return parseInt(wort, 10);
    if (hat(EINER, wort)) return EINER[wort];
    if (hat(ZEHNER, wort)) return ZEHNER[wort];
    if (hat(ORDINAL, wort)) return ORDINAL[wort];
    var stelle = wort.indexOf("und");
    if (stelle >= 0) {
      var einer = wort.slice(0, stelle), zehner = wort.slice(stelle + 3);
      if (hat(EINER, einer) && hat(ZEHNER, zehner)) return ZEHNER[zehner] + EINER[einer];
    }
    if (wort.endsWith("hundert")) {
      var praefix = wort.slice(0, -"hundert".length);
      return (praefix ? (hat(EINER, praefix) ? EINER[praefix] : 1) : 1) * 100;
    }
    return null;
  }

  function parseNumber(text) {
    var norm = normalize(text);
    var treffer = norm.match(/-?\d+(?:[.,]\d+)?/);
    if (treffer) return parseFloat(treffer[0].replace(",", "."));
    var woerter = tokens(norm);
    for (var i = 0; i < woerter.length; i++) {
      var wert = parseNumberWord(woerter[i]);
      if (wert !== null) return wert;
    }
    return null;
  }

  function parseDigits(text, laenge) {
    var ziffern = [];
    tokens(text).forEach(function (wort) {
      if (/^\d+$/.test(wort)) { ziffern.push(wort); return; }
      var wert = parseNumberWord(wort);
      if (wert !== null) ziffern.push(String(Math.trunc(wert)));
    });
    var folge = ziffern.join("");
    if (!folge) return null;
    if (laenge != null && folge.length !== laenge) return null;
    return folge;
  }

  /* --------------------------------------------------------------------- Datum */

  var WOCHENTAGE = { montag: 0, dienstag: 1, mittwoch: 2, donnerstag: 3, freitag: 4,
    samstag: 5, sonnabend: 5, sonntag: 6 };
  var MONATE = { januar: 1, februar: 2, maerz: 3, april: 4, mai: 5, juni: 6, juli: 7,
    august: 8, september: 9, oktober: 10, november: 11, dezember: 12 };

  function wochentagIndex(datum) { return (datum.getDay() + 6) % 7; }   // 0 = Montag

  function iso(datum) {
    return datum.getFullYear() + "-" + String(datum.getMonth() + 1).padStart(2, "0") +
      "-" + String(datum.getDate()).padStart(2, "0");
  }

  function sicheresDatum(jahr, monat, tag) {
    var datum = new Date(jahr, monat - 1, tag);
    if (datum.getFullYear() !== jahr || datum.getMonth() !== monat - 1 || datum.getDate() !== tag) {
      return null;   // z.B. 31.2. -- rollt in JavaScript still weiter
    }
    return iso(datum);
  }

  function plusTage(datum, tage) {
    var neu = new Date(datum.getTime());
    neu.setDate(neu.getDate() + tage);
    return neu;
  }

  function jahrBestimmen(roh, tag, monat, heute) {
    if (roh) {
      var jahr = parseInt(roh, 10);
      return jahr < 100 ? jahr + 2000 : jahr;
    }
    var kandidat = sicheresDatum(heute.getFullYear(), monat, tag);
    if (kandidat && new Date(kandidat + "T00:00:00") < new Date(iso(heute) + "T00:00:00")) {
      return heute.getFullYear() + 1;
    }
    return heute.getFullYear();
  }

  function parseDate(text, heute) {
    heute = heute || new Date();
    var norm = normalize(text);
    if (!norm) return null;

    if (norm.indexOf("uebermorgen") >= 0) return iso(plusTage(heute, 2));
    if (norm.indexOf("morgen") >= 0) return iso(plusTage(heute, 1));
    if (norm.indexOf("heute") >= 0) return iso(heute);

    var isoTreffer = norm.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
    if (isoTreffer) {
      return sicheresDatum(+isoTreffer[1], +isoTreffer[2], +isoTreffer[3]);
    }

    var zahl = norm.match(/\b(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\s*(\d{2,4})?/);
    if (zahl) {
      var tag = +zahl[1], monat = +zahl[2];
      return sicheresDatum(jahrBestimmen(zahl[3], tag, monat, heute), monat, tag);
    }

    for (var name in MONATE) {
      if (norm.indexOf(name) < 0) continue;
      var tagTreffer = norm.match(new RegExp("\\b(\\d{1,2})\\s*\\.?\\s*(?=" + name + ")"));
      var tagWert = tagTreffer ? +tagTreffer[1] : ordinalDavor(norm, name);
      if (tagWert === null) continue;
      return sicheresDatum(jahrBestimmen(null, tagWert, MONATE[name], heute), MONATE[name], tagWert);
    }

    var ordinale = tokens(norm).filter(function (w) { return hat(ORDINAL, w); })
      .map(function (w) { return ORDINAL[w]; });
    if (ordinale.length >= 2 && ordinale[0] && ordinale[1]) {
      return sicheresDatum(jahrBestimmen(null, ordinale[0], ordinale[1], heute), ordinale[1], ordinale[0]);
    }

    for (var tagName in WOCHENTAGE) {
      if (norm.indexOf(tagName) < 0) continue;
      var versatz = (WOCHENTAGE[tagName] - wochentagIndex(heute) + 7) % 7;
      if (versatz === 0) versatz += 7;      // "Dienstag" an einem Dienstag meint den naechsten
      return iso(plusTage(heute, versatz));
    }
    return null;
  }

  function ordinalDavor(norm, monatsName) {
    var praefix = norm.split(monatsName)[0].trim();
    if (!praefix) return null;
    var teile = praefix.split(/\s+/);
    var wert = parseNumberWord(teile[teile.length - 1]);
    return wert === null ? null : wert;
  }

  /* ------------------------------------------------------------------- Uhrzeit */

  function sichereZeit(stunde, minute, nachmittags) {
    if (nachmittags && stunde < 12) stunde += 12;
    if (stunde === 24) stunde = 0;
    if (!(stunde >= 0 && stunde <= 23 && minute >= 0 && minute <= 59)) return null;
    return String(stunde).padStart(2, "0") + ":" + String(minute).padStart(2, "0");
  }

  function parseTime(text) {
    var norm = normalize(text);
    if (!norm) return null;
    var pm = ["nachmittag", "nachmittags", "abend", "abends"].some(function (w) {
      return norm.indexOf(w) >= 0;
    });

    var doppelpunkt = norm.match(/\b(\d{1,2})[:.](\d{2})\b/);
    if (doppelpunkt) return sichereZeit(+doppelpunkt[1], +doppelpunkt[2], pm);

    var uhr = norm.match(/\b(\d{1,2})\s*uhr\s*(\d{1,2})?\b/);
    if (uhr) return sichereZeit(+uhr[1], uhr[2] ? +uhr[2] : 0, pm);

    var wortUhr = norm.match(/\b([\p{L}\d]+)\s+uhr\b/u);
    if (wortUhr) {
      var stunde = parseNumberWord(wortUhr[1]);
      if (stunde !== null) return sichereZeit(stunde, 0, pm);
    }

    var viertel = norm.match(/(dreiviertel|viertel|halb)\s*(?:nach|vor)?\s*([\p{L}\d]+)/u);
    if (viertel) {
      var bezug = parseNumberWord(viertel[2]);
      if (bezug !== null) {
        if (viertel[1] === "halb") return sichereZeit(bezug - 1, 30, pm);
        if (viertel[1] === "dreiviertel") return sichereZeit(bezug - 1, 45, pm);
        if (norm.indexOf("vor") >= 0) return sichereZeit(bezug - 1, 45, pm);
        return norm.indexOf("nach") >= 0 ? sichereZeit(bezug, 15, pm) : sichereZeit(bezug - 1, 15, pm);
      }
    }
    return null;
  }

  /* ------------------------------------------------- Aehnlichkeit (wie difflib) */

  function laengsterBlock(a, b, a0, a1, b0, b1) {
    var besteI = a0, besteJ = b0, besteLaenge = 0;
    for (var i = a0; i < a1; i++) {
      for (var j = b0; j < b1; j++) {
        var laenge = 0;
        while (i + laenge < a1 && j + laenge < b1 && a[i + laenge] === b[j + laenge]) laenge++;
        if (laenge > besteLaenge) { besteI = i; besteJ = j; besteLaenge = laenge; }
      }
    }
    return [besteI, besteJ, besteLaenge];
  }

  function treffermenge(a, b, a0, a1, b0, b1) {
    var block = laengsterBlock(a, b, a0, a1, b0, b1);
    var i = block[0], j = block[1], k = block[2];
    if (!k) return 0;
    return k + treffermenge(a, b, a0, i, b0, j) + treffermenge(a, b, i + k, a1, j + k, b1);
  }

  /** Aehnlichkeit zweier Zeichenketten, 0..1 -- entspricht difflib.SequenceMatcher.ratio. */
  function aehnlichkeit(a, b) {
    var gesamt = a.length + b.length;
    if (!gesamt) return 1;
    return (2 * treffermenge(a, b, 0, a.length, 0, b.length)) / gesamt;
  }

  /* ------------------------------------------------------ Regel-Interpreter */

  var FUZZY_SCHWELLE = 0.82;
  var MEHRDEUTIG_ABSTAND = 0.08;

  function RuleInterpreter(heute) {
    this.heute = heute || new Date();
  }

  RuleInterpreter.prototype.interpret = function (expect, eingabe) {
    expect = expect || { type: "text" };
    if (eingabe.dtmf) {
      var ausTaste = this._ausTaste(expect, eingabe.dtmf);
      if (ausTaste) return ausTaste;
    }
    var text = eingabe.text || "";
    if (!text.trim()) return { value: null, confidence: 0, raw: text };

    switch (expect.type) {
      case "yes_no": {
        var jaNein = parseYesNo(text);
        if (jaNein === null) return { value: null, confidence: 0, raw: text };
        return { value: jaNein ? "yes" : "no", confidence: 1, raw: text };
      }
      case "choice":
        return this._auswahl(expect, text);
      case "number": {
        var zahl = parseNumber(text);
        if (zahl === null || !imBereich(expect, zahl)) return { value: null, confidence: 0, raw: text };
        return { value: Number.isInteger(zahl) ? zahl : zahl, confidence: 1, raw: text };
      }
      case "digits": {
        var ziffern = parseDigits(text, expect.length != null ? expect.length : null);
        return { value: ziffern, confidence: ziffern ? 1 : 0, raw: text };
      }
      case "date": {
        var datum = parseDate(text, this.heute);
        return { value: datum, confidence: datum ? 1 : 0, raw: text };
      }
      case "time": {
        var zeit = parseTime(text);
        return { value: zeit, confidence: zeit ? 1 : 0, raw: text };
      }
      default: {
        var sauber = text.trim();
        return { value: sauber || null, confidence: sauber ? 1 : 0, raw: text };
      }
    }
  };

  RuleInterpreter.prototype._ausTaste = function (expect, taste) {
    if (expect.dtmf && Object.prototype.hasOwnProperty.call(expect.dtmf, taste)) {
      return { value: expect.dtmf[taste], confidence: 1, raw: taste };
    }
    if (expect.type === "digits") {
      if (expect.length != null && taste.length !== expect.length) return null;
      return { value: taste, confidence: 1, raw: taste };
    }
    if (expect.type === "number" && /^\d+$/.test(taste)) {
      var wert = parseInt(taste, 10);
      return imBereich(expect, wert) ? { value: wert, confidence: 1, raw: taste } : null;
    }
    if (expect.type === "yes_no" && (taste === "1" || taste === "2")) {
      return { value: taste === "1" ? "yes" : "no", confidence: 1, raw: taste };
    }
    return null;
  };

  RuleInterpreter.prototype._auswahl = function (expect, text) {
    var norm = normalize(text), woerter = tokens(norm), bewertung = [];
    Object.keys(expect.options || {}).forEach(function (wert) {
      var beste = 0;
      (expect.options[wert] || []).forEach(function (synonym) {
        var syn = normalize(synonym);
        if (!syn) return;
        if (syn.indexOf(" ") >= 0) {
          if (norm.indexOf(syn) >= 0) { beste = Math.max(beste, 1); return; }
        } else if (woerter.indexOf(syn) >= 0) {
          beste = Math.max(beste, 1); return;
        }
        if (expect.fuzzy !== false) beste = Math.max(beste, fuzzyWert(syn, woerter, norm));
      });
      if (beste > 0) bewertung.push([wert, beste]);
    });
    if (!bewertung.length) return { value: null, confidence: 0, raw: text };
    bewertung.sort(function (a, b) { return b[1] - a[1]; });
    if (bewertung[0][1] < FUZZY_SCHWELLE) return { value: null, confidence: 0, raw: text };
    if (bewertung.length > 1 && bewertung[0][1] - bewertung[1][1] < MEHRDEUTIG_ABSTAND) {
      return { value: null, confidence: 0, raw: text, mehrdeutig: bewertung.slice(0, 2) };
    }
    return { value: bewertung[0][0], confidence: bewertung[0][1], raw: text };
  };

  function fuzzyWert(synonym, woerter, norm) {
    var beste = aehnlichkeit(synonym, norm);
    woerter.forEach(function (wort) {
      beste = Math.max(beste, aehnlichkeit(synonym, wort));
      if (synonym.indexOf(wort) === 0 && wort.length >= 5) beste = Math.max(beste, 0.9);
    });
    return beste;
  }

  function imBereich(expect, wert) {
    if (expect.min != null && wert < expect.min) return false;
    if (expect.max != null && wert > expect.max) return false;
    return true;
  }

  RuleInterpreter.prototype.matchGlobal = function (kommandos, eingabe) {
    var i, k;
    for (i = 0; i < (kommandos || []).length; i++) {
      k = kommandos[i];
      if (eingabe.dtmf && k.dtmf && eingabe.dtmf === k.dtmf) return k;
    }
    var norm = normalize(eingabe.text || "");
    if (!norm) return null;
    var woerter = tokens(norm);
    for (i = 0; i < kommandos.length; i++) {
      k = kommandos[i];
      for (var j = 0; j < (k.phrases || []).length; j++) {
        var phrase = normalize(k.phrases[j]);
        if (!phrase) continue;
        if (phrase.indexOf(" ") >= 0) {
          if (norm.indexOf(phrase) >= 0) return k;
        } else if (woerter.indexOf(phrase) >= 0) {
          return k;
        }
      }
    }
    return null;
  };

  /* ------------------------------------------------------------- Platzhalter */

  function render(text, kontext) {
    if (!text) return "";
    return text.replace(/\{([a-zA-Z_][a-zA-Z0-9_.]*)\}/g, function (_, name) {
      var wert = kontext[name];
      return wert === undefined || wert === null ? "" : String(wert);
    }).trim();
  }

  function renderArgs(args, kontext) {
    var out = {};
    Object.keys(args || {}).forEach(function (schluessel) {
      var wert = args[schluessel];
      out[schluessel] = typeof wert === "string" ? render(wert, kontext) : wert;
    });
    return out;
  }

  /* ------------------------------------------------------------------ Engine */

  function FlowEngine(flow, interpreter, kontext) {
    this.flow = flow;
    this.interpreter = interpreter;
    this.slots = {};
    this.meta = Object.assign({}, kontext || {});
    this.history = [];
    this.finished = false;
    this.finishReason = null;
    this.currentNode = null;
    this.pending = null;
    this.attempts = {};
  }

  FlowEngine.prototype.kontextWerte = function () {
    return Object.assign({}, this.meta, this.slots);
  };

  FlowEngine.prototype.knoten = function (id) {
    var knoten = this.flow.nodes[id];
    if (!knoten) throw new Error("Knoten '" + id + "' existiert nicht");
    return Object.assign({ id: id }, knoten);
  };

  FlowEngine.prototype.start = function () {
    return this._advance(this.flow.start);
  };

  FlowEngine.prototype.submit = function (eingabe) {
    var offen = this.pending;
    if (!offen || offen.art !== "collect") throw new Error("Es wird gerade keine Eingabe erwartet");
    var knoten = this.knoten(offen.node_id);
    var leer = eingabe.timedOut || (!(eingabe.text || "").trim() && !eingabe.dtmf);

    if (!leer) {
      var kommando = this.interpreter.matchGlobal(this.flow.global_commands, eingabe);
      if (kommando) return this._global(kommando, knoten, offen);
    }
    if (leer) return this._retry(knoten, offen, "no_input");

    var minKonfidenz = this.flow.settings.min_confidence;
    if (eingabe.confidence != null && eingabe.confidence < minKonfidenz && !eingabe.dtmf) {
      return this._retry(knoten, offen, "no_match");
    }

    var ergebnis = this.interpreter.interpret(offen.expect, eingabe);
    if (ergebnis.value === null || ergebnis.value === undefined) {
      return this._retry(knoten, offen, "no_match");
    }
    if (knoten.slot) this.slots[knoten.slot] = ergebnis.value;
    delete this.attempts[knoten.id];
    this.pending = null;
    return this._advance(this._naechsterNachAntwort(knoten, ergebnis.value));
  };

  FlowEngine.prototype.submitActionResult = function (wert, fehler) {
    var offen = this.pending;
    if (!offen || offen.art !== "invoke") throw new Error("Es wird gerade kein Aktionsergebnis erwartet");
    var knoten = this.knoten(offen.node_id);
    this.pending = null;
    if (fehler) {
      this.meta.last_error = fehler;
      var ziel = knoten.on_error || this.flow.settings.escalation_node;
      if (!ziel) return this._beenden(knoten, "action_failed", []);
      return this._advance(ziel);
    }
    if (knoten.assign) this.slots[knoten.assign] = wert;
    if (!knoten.next) return this._beenden(knoten, "completed", []);
    return this._advance(knoten.next);
  };

  FlowEngine.prototype._advance = function (startId) {
    var ansagen = [], naechste = startId, schritte = 0;
    while (naechste) {
      if (++schritte > 50) throw new Error("Zyklus im Flow ab '" + startId + "'");
      var knoten = this.knoten(naechste);
      this.currentNode = knoten;
      this.history.push(knoten.id);
      var kontext = this.kontextWerte();

      if (knoten.type === "say") {
        if (knoten.text) ansagen.push(this._ansage(knoten, knoten.text, kontext, false));
        naechste = knoten.next;
        if (!naechste) return this._beenden(knoten, "completed", ansagen);
        continue;
      }
      if (knoten.type === "ask" || knoten.type === "confirm") {
        ansagen.push(this._ansage(knoten, knoten.text || "", kontext, false));
        this.pending = this._collect(knoten, 1);
        return { ansagen: ansagen, pending: this.pending };
      }
      if (knoten.type === "branch") {
        naechste = this._branchZiel(knoten);
        continue;
      }
      if (knoten.type === "action") {
        if (knoten.text) ansagen.push(this._ansage(knoten, knoten.text, kontext, false));
        this.pending = { art: "invoke", node_id: knoten.id, action: knoten.action,
          args: renderArgs(knoten.args, kontext), assign: knoten.assign };
        return { ansagen: ansagen, pending: this.pending };
      }
      if (knoten.type === "transfer") {
        if (knoten.text) ansagen.push(this._ansage(knoten, knoten.text, kontext, false));
        this.finished = true;
        this.finishReason = "transferred";
        this.pending = null;
        return { ansagen: ansagen, pending: { art: "transfer", node_id: knoten.id,
          target: render(knoten.target, kontext) } };
      }
      if (knoten.type === "hangup") {
        if (knoten.text) ansagen.push(this._ansage(knoten, knoten.text, kontext, false));
        return this._beenden(knoten, knoten.reason || "completed", ansagen);
      }
      throw new Error("Unbekannter Knotentyp: " + knoten.type);
    }
    throw new Error("Flow endete ohne Abschlussknoten");
  };

  FlowEngine.prototype._ansage = function (knoten, text, kontext, istReprompt) {
    return { text: render(text, kontext), node_id: knoten.id, is_reprompt: !!istReprompt };
  };

  FlowEngine.prototype._collect = function (knoten, versuch) {
    var expect = knoten.expect;
    if (!expect && knoten.type === "confirm") expect = { type: "yes_no" };
    if (!expect) expect = { type: "text" };
    return { art: "collect", node_id: knoten.id, expect: expect, slot: knoten.slot,
      timeout_s: knoten.timeout_s != null ? knoten.timeout_s : this.flow.settings.timeout_s,
      attempt: versuch };
  };

  FlowEngine.prototype._naechsterNachAntwort = function (knoten, wert) {
    if (knoten.type === "confirm") {
      var ziel = (wert === true || wert === "yes") ? knoten.on_yes : knoten.on_no;
      if (!ziel) throw new Error("confirm-Knoten '" + knoten.id + "' ohne on_yes/on_no");
      return ziel;
    }
    var schluessel = typeof wert === "boolean" ? (wert ? "yes" : "no") : String(wert);
    var uebergaenge = knoten.transitions || {};
    var target = uebergaenge[schluessel] || uebergaenge["*"] || knoten.next;
    if (!target) {
      throw new Error("Knoten '" + knoten.id + "': kein Uebergang fuer '" + schluessel + "'");
    }
    return target;
  };

  FlowEngine.prototype._branchZiel = function (knoten) {
    var werte = this.kontextWerte();
    for (var i = 0; i < (knoten.cases || []).length; i++) {
      if ((knoten.cases[i].when || []).every(function (bedingung) {
        return pruefe(bedingung, werte);
      })) return knoten.cases[i].next;
    }
    if (!knoten.next) throw new Error("branch-Knoten '" + knoten.id + "' ohne Default");
    return knoten.next;
  };

  function pruefe(bedingung, werte) {
    var ist = werte[bedingung.slot];
    var op = bedingung.op || "eq", soll = bedingung.value;
    if (op === "set") return ist !== undefined && ist !== null;
    if (op === "unset") return ist === undefined || ist === null;
    if (ist === undefined || ist === null) return false;
    switch (op) {
      case "eq": return gleich(ist, soll);
      case "ne": return !gleich(ist, soll);
      case "lt": return parseFloat(ist) < parseFloat(soll);
      case "lte": return parseFloat(ist) <= parseFloat(soll);
      case "gt": return parseFloat(ist) > parseFloat(soll);
      case "gte": return parseFloat(ist) >= parseFloat(soll);
      case "in": return (soll || []).indexOf(ist) >= 0;
      case "contains": return String(ist).toLowerCase().indexOf(String(soll).toLowerCase()) >= 0;
      default: return false;
    }
  }

  function gleich(ist, soll) {
    if (ist === soll) return true;
    if (typeof ist === "boolean" || typeof soll === "boolean") return false;
    var a = parseFloat(ist), b = parseFloat(soll);
    if (!isNaN(a) && !isNaN(b)) return a === b;
    return String(ist).trim().toLowerCase() === String(soll).trim().toLowerCase();
  }

  FlowEngine.prototype._retry = function (knoten, offen, art) {
    var versuch = (this.attempts[knoten.id] || 0) + 1;
    this.attempts[knoten.id] = versuch;
    var grenze = knoten.max_attempts != null ? knoten.max_attempts : this.flow.settings.max_attempts;

    if (versuch <= grenze) {
      var kontext = this.kontextWerte();
      var text = (art === "no_input" ? knoten.no_input_text : null) || knoten.reprompt || knoten.text;
      this.pending = this._collect(knoten, offen.attempt + 1);
      return { ansagen: [this._ansage(knoten, text || "", kontext, true)], pending: this.pending,
        grund: art };
    }

    delete this.attempts[knoten.id];
    this.pending = null;
    this.meta.escalation_reason = art;
    var ziel = (art === "no_input" ? knoten.on_no_input : knoten.on_no_match) ||
      knoten.on_no_match || this.flow.settings.escalation_node;
    if (!ziel) return this._beenden(knoten, "max_attempts_" + art, []);
    return this._advance(ziel);
  };

  FlowEngine.prototype._global = function (kommando, knoten, offen) {
    if (kommando.action === "repeat") {
      this.pending = this._collect(knoten, offen.attempt + 1);
      return { ansagen: [this._ansage(knoten, knoten.text || "", this.kontextWerte(), true)],
        pending: this.pending, kommando: kommando.name };
    }
    if (kommando.action === "back") {
      var ziel = this._vorherigeFrage(knoten.id) || this.flow.start;
      this.pending = null;
      delete this.attempts[knoten.id];
      return this._advance(ziel);
    }
    if (kommando.action === "goto") {
      this.pending = null;
      this.meta.global_command = kommando.name;
      var ergebnis = this._advance(kommando.target);
      ergebnis.kommando = kommando.name;
      return ergebnis;
    }
    throw new Error("Unbekannte Kommando-Aktion: " + kommando.action);
  };

  FlowEngine.prototype._vorherigeFrage = function (aktuell) {
    for (var i = this.history.length - 2; i >= 0; i--) {
      var id = this.history[i];
      if (id === aktuell) continue;
      var knoten = this.flow.nodes[id];
      if (knoten && (knoten.type === "ask" || knoten.type === "confirm")) return id;
    }
    return null;
  };

  FlowEngine.prototype._beenden = function (knoten, grund, ansagen) {
    this.finished = true;
    this.finishReason = grund;
    this.pending = null;
    return { ansagen: ansagen || [], pending: { art: "hangup", node_id: knoten.id, reason: grund } };
  };

  /* -------------------------------------------------------------- Sprechzeiten */

  var WOCHENTAG_NAMEN = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"];

  function Sprechzeiten(tage, geschlossen) {
    this.tage = {};
    var selbst = this;
    Object.keys(tage || {}).forEach(function (tag) {
      selbst.tage[tag] = (tage[tag] || []).map(function (spanne) {
        var teile = spanne.split("-");
        return { von: teile[0].trim(), bis: teile[1].trim() };
      });
    });
    this.geschlossen = new Set(geschlossen || []);
  }

  Sprechzeiten.prototype.definiert = function () {
    var selbst = this;
    return Object.keys(this.tage).some(function (t) { return selbst.tage[t].length; });
  };

  Sprechzeiten.prototype.istOffen = function (zeitpunkt) {
    if (!this.definiert()) return true;
    if (this.geschlossen.has(iso(zeitpunkt))) return false;
    var uhrzeit = String(zeitpunkt.getHours()).padStart(2, "0") + ":" +
      String(zeitpunkt.getMinutes()).padStart(2, "0");
    return (this.tage[WOCHENTAG_NAMEN[wochentagIndex(zeitpunkt)]] || []).some(function (spanne) {
      return spanne.von <= uhrzeit && uhrzeit < spanne.bis;
    });
  };

  Sprechzeiten.prototype.naechsteOeffnung = function (zeitpunkt) {
    if (!this.definiert()) return null;
    for (var versatz = 0; versatz <= 14; versatz++) {
      var tag = plusTage(zeitpunkt, versatz);
      if (this.geschlossen.has(iso(tag))) continue;
      var spannen = (this.tage[WOCHENTAG_NAMEN[wochentagIndex(tag)]] || []).slice()
        .sort(function (a, b) { return a.von < b.von ? -1 : 1; });
      for (var i = 0; i < spannen.length; i++) {
        var teile = spannen[i].von.split(":");
        var kandidat = new Date(tag.getFullYear(), tag.getMonth(), tag.getDate(), +teile[0], +teile[1]);
        if (kandidat > zeitpunkt) return kandidat;
      }
    }
    return null;
  };

  Sprechzeiten.prototype.kontext = function (zeitpunkt) {
    var offen = this.istOffen(zeitpunkt);
    var naechste = this.naechsteOeffnung(zeitpunkt);
    return {
      jetzt_datum: iso(zeitpunkt),
      jetzt_uhrzeit: String(zeitpunkt.getHours()).padStart(2, "0") + ":" +
        String(zeitpunkt.getMinutes()).padStart(2, "0"),
      wochentag: WOCHENTAG_NAMEN[wochentagIndex(zeitpunkt)],
      innerhalb_sprechzeit: offen ? "ja" : "nein",
      naechste_sprechzeit: naechste ? inWorten(naechste, zeitpunkt) : ""
    };
  };

  function inWorten(zeitpunkt, jetzt) {
    var stunde = zeitpunkt.getHours() + " Uhr" + (zeitpunkt.getMinutes() ? " " + zeitpunkt.getMinutes() : "");
    var tage = Math.round((new Date(iso(zeitpunkt)) - new Date(iso(jetzt))) / 86400000);
    if (tage === 0) return "heute um " + stunde;
    if (tage === 1) return "morgen um " + stunde;
    var name = WOCHENTAG_NAMEN[wochentagIndex(zeitpunkt)];
    return "am " + name.charAt(0).toUpperCase() + name.slice(1) + " um " + stunde;
  }

  global.Telefonbot = {
    normalize: normalize, tokens: tokens, parseYesNo: parseYesNo, parseNumber: parseNumber,
    parseNumberWord: parseNumberWord, parseDigits: parseDigits, parseDate: parseDate,
    parseTime: parseTime, aehnlichkeit: aehnlichkeit, render: render,
    RuleInterpreter: RuleInterpreter, FlowEngine: FlowEngine, Sprechzeiten: Sprechzeiten,
    WOCHENTAG_NAMEN: WOCHENTAG_NAMEN, iso: iso
  };
})(window);
