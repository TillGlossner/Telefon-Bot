// Erzeugt von scripts/demo_daten.py -- nicht von Hand aendern.
// Quelle: config/flows/*.yaml und die Python-Parser in src/telefonbot/nlu.
window.TELEFONBOT_DATEN = {
  "auswahl_optionen": {
    "krankmeldung": [
      "krankmeldung",
      "krank melden"
    ],
    "pruefungsamt": [
      "pruefungsamt",
      "pruefung"
    ],
    "termin": [
      "termin",
      "sprechstunde",
      "beratungstermin"
    ]
  },
  "bezugstag": "2026-03-10",
  "erzeugt_aus": "config/flows/*.yaml",
  "flows": {
    "klinik_sekretariat": {
      "description": "Anliegen aufnehmen, ärztliche Anrufer durchstellen, Absagen erledigen",
      "global_commands": [
        {
          "action": "goto",
          "dtmf": null,
          "name": "notfall",
          "phrases": [
            "notfall",
            "notaufnahme",
            "notarzt",
            "herzinfarkt",
            "schlaganfall",
            "bekomme keine luft",
            "keine luft",
            "bewusstlos",
            "reanimation",
            "112"
          ],
          "target": "notfall_hinweis"
        },
        {
          "action": "goto",
          "dtmf": "0",
          "name": "mensch",
          "phrases": [
            "mitarbeiter",
            "mitarbeiterin",
            "sekretariat",
            "mensch",
            "jemanden sprechen",
            "echten menschen",
            "persönlich sprechen"
          ],
          "target": "weiterleitung_pruefen"
        },
        {
          "action": "repeat",
          "dtmf": null,
          "name": "wiederholen",
          "phrases": [
            "wiederholen",
            "nochmal",
            "noch mal",
            "wie bitte",
            "nicht verstanden"
          ],
          "target": null
        },
        {
          "action": "goto",
          "dtmf": null,
          "name": "abbrechen",
          "phrases": [
            "abbrechen",
            "auflegen",
            "hat sich erledigt",
            "danke das wars"
          ],
          "target": "verabschiedung"
        }
      ],
      "id": "klinik_sekretariat",
      "locale": "de-DE",
      "nodes": {
        "absage_anlegen": {
          "action": "create_ticket",
          "args": {
            "art": "terminabsage",
            "name": "{name}",
            "termin": "{termindatum}"
          },
          "assign": "vorgangsnummer",
          "next": "absage_ende",
          "on_error": "weiterleitung_pruefen",
          "type": "action"
        },
        "absage_bestaetigen": {
          "on_no": "absage_name",
          "on_yes": "absage_anlegen",
          "reprompt": "Bitte antworten Sie mit ja oder nein.",
          "text": "Ich sage den Termin am {termindatum} ab, auf den Namen {name}. Ist das richtig?",
          "type": "confirm"
        },
        "absage_datum": {
          "expect": {
            "fuzzy": true,
            "type": "date"
          },
          "next": "absage_bestaetigen",
          "reprompt": "Bitte nennen Sie den Tag, zum Beispiel morgen oder Dienstag, den vierzehnten.",
          "slot": "termindatum",
          "text": "An welchem Tag war Ihr Termin?",
          "type": "ask"
        },
        "absage_ende": {
          "reason": "completed",
          "text": "Die Absage ist vermerkt, Vorgangsnummer {vorgangsnummer}. Wenn Sie einen neuen Termin möchten, melden Sie sich gerne wieder. Auf Wiederhören.",
          "type": "hangup"
        },
        "absage_name": {
          "expect": {
            "fuzzy": true,
            "type": "text"
          },
          "next": "absage_datum",
          "reprompt": "Bitte nennen Sie Ihren Vor- und Nachnamen.",
          "slot": "name",
          "text": "Gerne nehme ich die Absage auf. Wie ist Ihr Name?",
          "type": "ask"
        },
        "aerztlich_ausserhalb": {
          "next": "rueckruf_name",
          "text": "Das Sekretariat ist derzeit nicht besetzt. In dringenden fachlichen Fällen erreichen Sie den diensthabenden Arzt rund um die Uhr über die Pforte der Klinik. Für alles andere notiere ich Ihnen einen Rückruf.",
          "type": "say"
        },
        "aerztlich_durchstellen": {
          "cases": [
            {
              "next": "aerztlich_ausserhalb",
              "when": [
                {
                  "op": "eq",
                  "slot": "innerhalb_sprechzeit",
                  "value": "nein"
                }
              ]
            }
          ],
          "next": "weiterleitung",
          "type": "branch"
        },
        "anderes_hinweis": {
          "next": "rueckruf_name",
          "text": "Zu Befunden, Arztbriefen und Behandlungen darf ich telefonisch keine Auskunft geben. Ich notiere Ihr Anliegen und das Sekretariat meldet sich.",
          "type": "say"
        },
        "begruessung": {
          "next": "hinweis_assistent",
          "text": "Guten Tag, hier ist der automatische Telefondienst des Klinik-Sekretariats. Bei einem medizinischen Notfall legen Sie bitte auf und wählen Sie die 1 1 2.",
          "type": "say"
        },
        "hauptmenue": {
          "expect": {
            "dtmf": {
              "1": "aerztlich",
              "2": "termin",
              "3": "anderes"
            },
            "fuzzy": true,
            "options": {
              "aerztlich": [
                "ärztlich",
                "arzt",
                "ärztin",
                "doktor",
                "kollege",
                "kollegin",
                "zuweiser",
                "zuweisung",
                "einweisung",
                "hausarzt",
                "facharzt",
                "praxis",
                "ich bin arzt",
                "ich bin ärztin"
              ],
              "anderes": [
                "etwas anderes",
                "anderes",
                "sonstiges",
                "befund",
                "arztbrief",
                "unterlagen",
                "bescheinigung",
                "auskunft"
              ],
              "termin": [
                "termin",
                "sprechstunde",
                "vorstellung",
                "untersuchung",
                "terminvergabe",
                "absagen",
                "verschieben"
              ]
            },
            "type": "choice"
          },
          "no_input_text": "Ich habe Sie nicht gehört. Sagen Sie ärztlich, Termin, oder etwas anderes.",
          "reprompt": "Bitte sagen Sie: ärztlich, Termin, oder etwas anderes. Sie können auch die Eins, Zwei oder Drei drücken.",
          "slot": "anliegen",
          "text": "Rufen Sie als Ärztin oder Arzt an, geht es um einen Termin, oder um etwas anderes?",
          "transitions": {
            "aerztlich": "aerztlich_durchstellen",
            "anderes": "anderes_hinweis",
            "termin": "termin_art"
          },
          "type": "ask"
        },
        "hinweis_assistent": {
          "next": "sprechzeit_pruefen",
          "text": "Ich bin ein Sprachassistent und nehme Ihr Anliegen auf. Sagen Sie jederzeit Mitarbeiter oder drücken Sie die Null, um mit einer Person verbunden zu werden.",
          "type": "say"
        },
        "hinweis_geschlossen": {
          "next": "hauptmenue",
          "text": "Das Sekretariat ist im Moment nicht besetzt, wieder erreichbar {naechste_sprechzeit}. Ich nehme Ihr Anliegen trotzdem auf.",
          "type": "say"
        },
        "notfall_hinweis": {
          "reason": "notfall",
          "text": "Wenn es sich um einen medizinischen Notfall handelt, legen Sie bitte sofort auf und wählen Sie die 1 1 2. Bei dringenden Beschwerden wenden Sie sich an die Notaufnahme oder an den ärztlichen Bereitschaftsdienst unter der 1 1 6 1 1 7.",
          "type": "hangup"
        },
        "rueckruf_anlegen": {
          "action": "create_ticket",
          "args": {
            "anliegen": "{anliegen}",
            "art": "rueckruf",
            "name": "{name}",
            "nummer": "{rueckrufnummer}"
          },
          "assign": "vorgangsnummer",
          "next": "rueckruf_ende",
          "on_error": "weiterleitung_pruefen",
          "type": "action"
        },
        "rueckruf_bestaetigen": {
          "on_no": "rueckruf_nummer",
          "on_yes": "rueckruf_anlegen",
          "reprompt": "Bitte antworten Sie mit ja oder nein.",
          "text": "Ich habe die Nummer {rueckrufnummer} notiert. Stimmt das?",
          "type": "confirm"
        },
        "rueckruf_ende": {
          "reason": "completed",
          "text": "Danke, der Rückruf ist unter der Nummer {vorgangsnummer} notiert. Das Sekretariat meldet sich bei Ihnen. Auf Wiederhören.",
          "type": "hangup"
        },
        "rueckruf_name": {
          "expect": {
            "fuzzy": true,
            "type": "text"
          },
          "next": "rueckruf_nummer",
          "reprompt": "Bitte nennen Sie Ihren Vor- und Nachnamen.",
          "slot": "name",
          "text": "Wie ist Ihr Name?",
          "type": "ask"
        },
        "rueckruf_nummer": {
          "expect": {
            "fuzzy": true,
            "type": "digits"
          },
          "next": "rueckruf_bestaetigen",
          "reprompt": "Bitte nennen Sie Ihre Rufnummer Ziffer für Ziffer.",
          "slot": "rueckrufnummer",
          "text": "Unter welcher Rufnummer sind Sie erreichbar? Sie können die Nummer auch über die Tastatur eingeben und mit der Raute abschließen.",
          "type": "ask"
        },
        "sprechzeit_pruefen": {
          "cases": [
            {
              "next": "hinweis_geschlossen",
              "when": [
                {
                  "op": "eq",
                  "slot": "innerhalb_sprechzeit",
                  "value": "nein"
                }
              ]
            }
          ],
          "next": "hauptmenue",
          "type": "branch"
        },
        "termin_art": {
          "expect": {
            "dtmf": {
              "1": "neu",
              "2": "absage"
            },
            "fuzzy": true,
            "options": {
              "absage": [
                "absage",
                "absagen",
                "abmelden",
                "verschieben",
                "verschiebung",
                "kann nicht kommen",
                "verhindert",
                "nicht kommen"
              ],
              "neu": [
                "neuer termin",
                "neu",
                "termin vereinbaren",
                "erstvorstellung",
                "vorstellung",
                "anmelden",
                "sprechstunde"
              ]
            },
            "type": "choice"
          },
          "reprompt": "Bitte sagen Sie: neuer Termin, oder Absage.",
          "slot": "terminart",
          "text": "Geht es um einen neuen Termin oder um eine Absage?",
          "transitions": {
            "absage": "absage_name",
            "neu": "termin_neu_hinweis"
          },
          "type": "ask"
        },
        "termin_neu_hinweis": {
          "next": "rueckruf_name",
          "text": "Termine vergibt das Sekretariat persönlich, damit die nötigen Unterlagen vorliegen. Ich notiere Ihnen einen Rückruf.",
          "type": "say"
        },
        "verabschiedung": {
          "reason": "caller_cancelled",
          "text": "Vielen Dank für Ihren Anruf. Auf Wiederhören.",
          "type": "hangup"
        },
        "weiterleitung": {
          "target": "PJSIP/sekretariat@uni-pbx",
          "text": "Einen Moment bitte, ich verbinde Sie mit dem Sekretariat.",
          "type": "transfer"
        },
        "weiterleitung_nicht_moeglich": {
          "next": "rueckruf_name",
          "text": "Das Sekretariat ist gerade nicht besetzt, wieder erreichbar {naechste_sprechzeit}. Ich notiere Ihnen einen Rückruf.",
          "type": "say"
        },
        "weiterleitung_pruefen": {
          "cases": [
            {
              "next": "weiterleitung_nicht_moeglich",
              "when": [
                {
                  "op": "eq",
                  "slot": "innerhalb_sprechzeit",
                  "value": "nein"
                }
              ]
            }
          ],
          "next": "weiterleitung",
          "type": "branch"
        }
      },
      "settings": {
        "barge_in": true,
        "escalation_node": "weiterleitung_pruefen",
        "max_attempts": 2,
        "min_confidence": 0.5,
        "timeout_s": 7.0
      },
      "slots": {
        "anliegen": {
          "description": "Grobe Anliegensart",
          "sensitive": false,
          "type": "choice"
        },
        "name": {
          "description": "Name des Anrufers",
          "sensitive": true,
          "type": "text"
        },
        "rueckrufnummer": {
          "description": "Rufnummer für den Rückruf",
          "sensitive": true,
          "type": "digits"
        },
        "terminart": {
          "description": "Neuer Termin oder Absage",
          "sensitive": false,
          "type": "choice"
        },
        "termindatum": {
          "description": "Betroffener Termin bei einer Absage",
          "sensitive": true,
          "type": "date"
        },
        "vorgangsnummer": {
          "description": "Nummer des angelegten Vorgangs",
          "sensitive": false,
          "type": "text"
        }
      },
      "start": "begruessung",
      "version": 1
    },
    "lehrstuhl_sekretariat": {
      "description": "Anliegen aufnehmen, Termine notieren, sonst an das Sekretariat weiterleiten",
      "global_commands": [
        {
          "action": "goto",
          "dtmf": "0",
          "name": "mensch",
          "phrases": [
            "mitarbeiter",
            "mitarbeiterin",
            "mensch",
            "echten menschen",
            "sekretariat",
            "jemanden sprechen"
          ],
          "target": "weiterleitung_pruefen"
        },
        {
          "action": "repeat",
          "dtmf": null,
          "name": "wiederholen",
          "phrases": [
            "wiederholen",
            "nochmal",
            "noch mal",
            "wie bitte",
            "nicht verstanden"
          ],
          "target": null
        },
        {
          "action": "goto",
          "dtmf": null,
          "name": "oeffnungszeiten",
          "phrases": [
            "öffnungszeiten",
            "sprechzeiten",
            "wann habt ihr auf",
            "wann ist geoeffnet"
          ],
          "target": "oeffnungszeiten"
        },
        {
          "action": "goto",
          "dtmf": null,
          "name": "abbrechen",
          "phrases": [
            "abbrechen",
            "auflegen",
            "hat sich erledigt",
            "danke das wars"
          ],
          "target": "verabschiedung"
        }
      ],
      "id": "lehrstuhl_sekretariat",
      "locale": "de-DE",
      "nodes": {
        "begruessung": {
          "next": "sprechzeit_pruefen",
          "text": "Guten Tag, hier ist der automatische Telefondienst des Lehrstuhls. Ich bin ein Sprachassistent und nehme Ihr Anliegen auf. Sagen Sie jederzeit Mitarbeiter oder drücken Sie die Null, um mit einer Person verbunden zu werden.",
          "type": "say"
        },
        "hauptmenue": {
          "expect": {
            "dtmf": {
              "1": "termin",
              "2": "rueckruf",
              "3": "pruefung"
            },
            "fuzzy": true,
            "options": {
              "pruefung": [
                "prüfung",
                "prüfungsamt",
                "klausur",
                "note",
                "noten",
                "prüfungsangelegenheit"
              ],
              "rueckruf": [
                "rückruf",
                "zurückrufen",
                "anrufen",
                "rueckmeldung"
              ],
              "termin": [
                "termin",
                "termine",
                "sprechstunde",
                "beratung",
                "besprechung",
                "treffen"
              ]
            },
            "type": "choice"
          },
          "no_input_text": "Ich habe Sie nicht gehört. Sagen Sie Termin, Rückruf oder Prüfung.",
          "reprompt": "Bitte sagen Sie Termin, Rückruf oder Prüfung. Sie können auch die Eins, Zwei oder Drei drücken.",
          "slot": "anliegen",
          "text": "Möchten Sie einen Termin vereinbaren, einen Rückruf erbitten oder geht es um eine Prüfungsangelegenheit?",
          "transitions": {
            "pruefung": "pruefung_art",
            "rueckruf": "rueckruf_name",
            "termin": "termin_datum"
          },
          "type": "ask"
        },
        "hinweis_geschlossen": {
          "next": "hauptmenue",
          "text": "Das Sekretariat ist im Moment nicht besetzt, wieder erreichbar {naechste_sprechzeit}. Ich nehme Ihr Anliegen trotzdem auf.",
          "type": "say"
        },
        "oeffnungszeiten": {
          "next": "hauptmenue",
          "text": "Das Sekretariat ist montags bis donnerstags von neun bis zwölf Uhr und von vierzehn bis sechzehn Uhr besetzt, freitags von neun bis zwölf Uhr.",
          "type": "say"
        },
        "pruefung_anlegen": {
          "action": "create_ticket",
          "args": {
            "art": "pruefung",
            "matrikelnummer": "{matrikelnummer}",
            "name": "{name}",
            "unterart": "{pruefungsanliegen}"
          },
          "assign": "vorgangsnummer",
          "next": "pruefung_ende",
          "on_error": "weiterleitung_pruefen",
          "type": "action"
        },
        "pruefung_art": {
          "expect": {
            "dtmf": {
              "1": "anmeldung",
              "2": "attest",
              "3": "bescheinigung"
            },
            "fuzzy": true,
            "options": {
              "anmeldung": [
                "anmeldung",
                "anmelden",
                "prüfungsanmeldung",
                "eintragen"
              ],
              "attest": [
                "attest",
                "krank",
                "krankmeldung",
                "krankschreibung",
                "rücktritt"
              ],
              "bescheinigung": [
                "bescheinigung",
                "notenbescheinigung",
                "zeugnis",
                "noten",
                "schein"
              ]
            },
            "type": "choice"
          },
          "reprompt": "Bitte sagen Sie Anmeldung, Attest oder Bescheinigung.",
          "slot": "pruefungsanliegen",
          "text": "Geht es um eine Prüfungsanmeldung, um ein Attest oder um eine Notenbescheinigung?",
          "transitions": {
            "anmeldung": "pruefung_matrikel",
            "attest": "pruefung_attest_hinweis",
            "bescheinigung": "pruefung_matrikel"
          },
          "type": "ask"
        },
        "pruefung_attest_hinweis": {
          "next": "pruefung_matrikel",
          "text": "Ein Attest muss im Original im Prüfungsamt eingehen. Ich nehme Ihre Daten auf und leite den Vorgang weiter.",
          "type": "say"
        },
        "pruefung_ende": {
          "reason": "completed",
          "text": "Ihr Anliegen ist unter der Nummer {vorgangsnummer} aufgenommen. Das Prüfungssekretariat bearbeitet es und meldet sich bei Rückfragen. Auf Wiederhören.",
          "type": "hangup"
        },
        "pruefung_matrikel": {
          "expect": {
            "fuzzy": true,
            "length": 8,
            "type": "digits"
          },
          "next": "pruefung_name",
          "reprompt": "Bitte nennen Sie die acht Ziffern Ihrer Matrikelnummer oder geben Sie sie über die Tastatur ein.",
          "slot": "matrikelnummer",
          "text": "Bitte nennen Sie Ihre achtstellige Matrikelnummer.",
          "type": "ask"
        },
        "pruefung_name": {
          "expect": {
            "fuzzy": true,
            "type": "text"
          },
          "next": "pruefung_anlegen",
          "slot": "name",
          "text": "Und wie ist Ihr Name?",
          "type": "ask"
        },
        "rueckruf_anlegen": {
          "action": "create_ticket",
          "args": {
            "art": "rueckruf",
            "name": "{name}",
            "nummer": "{rueckrufnummer}"
          },
          "assign": "vorgangsnummer",
          "next": "rueckruf_ende",
          "on_error": "weiterleitung_pruefen",
          "type": "action"
        },
        "rueckruf_dringend": {
          "on_no": "rueckruf_anlegen",
          "on_yes": "weiterleitung_pruefen",
          "slot": "dringend",
          "text": "Ist Ihr Anliegen dringend, also noch heute?",
          "type": "confirm"
        },
        "rueckruf_ende": {
          "reason": "completed",
          "text": "Danke. Der Rückruf ist unter der Nummer {vorgangsnummer} notiert, das Sekretariat meldet sich bei Ihnen. Auf Wiederhören.",
          "type": "hangup"
        },
        "rueckruf_name": {
          "expect": {
            "fuzzy": true,
            "type": "text"
          },
          "next": "rueckruf_nummer",
          "reprompt": "Bitte nennen Sie Ihren Vor- und Nachnamen.",
          "slot": "name",
          "text": "Gerne notiere ich einen Rückruf. Wie ist Ihr Name?",
          "type": "ask"
        },
        "rueckruf_nummer": {
          "expect": {
            "fuzzy": true,
            "type": "digits"
          },
          "next": "rueckruf_dringend",
          "reprompt": "Bitte nennen Sie Ihre Rufnummer Ziffer für Ziffer.",
          "slot": "rueckrufnummer",
          "text": "Unter welcher Rufnummer sind Sie erreichbar? Sie können die Nummer auch über die Tastatur eingeben und mit der Raute abschliessen.",
          "type": "ask"
        },
        "sprechzeit_pruefen": {
          "cases": [
            {
              "next": "hinweis_geschlossen",
              "when": [
                {
                  "op": "eq",
                  "slot": "innerhalb_sprechzeit",
                  "value": "nein"
                }
              ]
            }
          ],
          "next": "hauptmenue",
          "type": "branch"
        },
        "termin_anlegen": {
          "action": "create_appointment",
          "args": {
            "art": "termin",
            "datum": "{datum}",
            "name": "{name}",
            "uhrzeit": "{uhrzeit}"
          },
          "assign": "vorgangsnummer",
          "next": "termin_ende",
          "on_error": "weiterleitung_pruefen",
          "type": "action"
        },
        "termin_bestaetigen": {
          "on_no": "termin_datum",
          "on_yes": "termin_anlegen",
          "reprompt": "Bitte antworten Sie mit ja oder nein.",
          "text": "Ich habe notiert: {name}, am {datum} um {uhrzeit} Uhr. Stimmt das so?",
          "type": "confirm"
        },
        "termin_datum": {
          "expect": {
            "fuzzy": true,
            "type": "date"
          },
          "next": "termin_uhrzeit",
          "reprompt": "Bitte nennen Sie einen Tag, zum Beispiel morgen oder Dienstag, den vierzehnten.",
          "slot": "datum",
          "text": "An welchem Tag möchten Sie kommen?",
          "type": "ask"
        },
        "termin_ende": {
          "reason": "completed",
          "text": "Ihr Terminwunsch ist unter der Nummer {vorgangsnummer} vermerkt. Das Sekretariat bestätigt Ihnen den Termin. Vielen Dank für Ihren Anruf und auf Wiederhören.",
          "type": "hangup"
        },
        "termin_name": {
          "expect": {
            "fuzzy": true,
            "type": "text"
          },
          "next": "termin_bestaetigen",
          "reprompt": "Bitte nennen Sie Ihren Vor- und Nachnamen.",
          "slot": "name",
          "text": "Und wie ist Ihr Name?",
          "type": "ask"
        },
        "termin_uhrzeit": {
          "expect": {
            "fuzzy": true,
            "type": "time"
          },
          "next": "termin_name",
          "reprompt": "Bitte nennen Sie eine Uhrzeit, zum Beispiel vierzehn Uhr dreißig.",
          "slot": "uhrzeit",
          "text": "Um welche Uhrzeit passt es Ihnen?",
          "type": "ask"
        },
        "verabschiedung": {
          "reason": "caller_cancelled",
          "text": "Vielen Dank für Ihren Anruf. Auf Wiederhören.",
          "type": "hangup"
        },
        "weiterleitung": {
          "target": "PJSIP/sekretariat@uni-pbx",
          "text": "Einen Moment bitte, ich verbinde Sie mit dem Sekretariat.",
          "type": "transfer"
        },
        "weiterleitung_nicht_moeglich": {
          "next": "rueckruf_name",
          "text": "Das Sekretariat ist gerade nicht besetzt, wieder erreichbar {naechste_sprechzeit}. Ich notiere Ihnen einen Rückruf.",
          "type": "say"
        },
        "weiterleitung_pruefen": {
          "cases": [
            {
              "next": "weiterleitung_nicht_moeglich",
              "when": [
                {
                  "op": "eq",
                  "slot": "innerhalb_sprechzeit",
                  "value": "nein"
                }
              ]
            }
          ],
          "next": "weiterleitung",
          "type": "branch"
        }
      },
      "settings": {
        "barge_in": true,
        "escalation_node": "weiterleitung_pruefen",
        "max_attempts": 2,
        "min_confidence": 0.45,
        "timeout_s": 6.0
      },
      "slots": {
        "anliegen": {
          "description": "Hauptanliegen des Anrufs",
          "sensitive": false,
          "type": "choice"
        },
        "datum": {
          "description": "Wunschtag fuer den Termin",
          "sensitive": false,
          "type": "date"
        },
        "dringend": {
          "description": "Rueckruf noch heute noetig",
          "sensitive": false,
          "type": "yes_no"
        },
        "matrikelnummer": {
          "description": "Matrikelnummer",
          "sensitive": true,
          "type": "digits"
        },
        "name": {
          "description": "Name des Anrufers",
          "sensitive": true,
          "type": "text"
        },
        "pruefungsanliegen": {
          "description": "Art des Pruefungsanliegens",
          "sensitive": false,
          "type": "choice"
        },
        "rueckrufnummer": {
          "description": "Rufnummer fuer den Rueckruf",
          "sensitive": true,
          "type": "digits"
        },
        "uhrzeit": {
          "description": "Wunschzeit fuer den Termin",
          "sensitive": false,
          "type": "time"
        },
        "vorgangsnummer": {
          "description": "Nummer des angelegten Vorgangs",
          "sensitive": false,
          "type": "text"
        }
      },
      "start": "begruessung",
      "version": 1
    },
    "minimal_demo": {
      "description": "",
      "global_commands": [],
      "id": "minimal_demo",
      "locale": "de-DE",
      "nodes": {
        "begruessung": {
          "next": "frage",
          "text": "Guten Tag, hier ist der automatische Telefondienst.",
          "type": "say"
        },
        "frage": {
          "expect": {
            "fuzzy": true,
            "type": "yes_no"
          },
          "reprompt": "Bitte antworten Sie mit ja oder nein.",
          "slot": "anliegen",
          "text": "Möchten Sie einen Termin vereinbaren? Sagen Sie ja oder nein.",
          "transitions": {
            "no": "verabschiedung",
            "yes": "termin"
          },
          "type": "ask"
        },
        "termin": {
          "text": "Das Sekretariat meldet sich bei Ihnen. Auf Wiederhören.",
          "type": "hangup"
        },
        "verabschiedung": {
          "text": "Alles klar, danke für Ihren Anruf.",
          "type": "hangup"
        },
        "weiterleitung": {
          "target": "PJSIP/sekretariat",
          "text": "Ich verbinde Sie.",
          "type": "transfer"
        }
      },
      "settings": {
        "barge_in": true,
        "escalation_node": "weiterleitung",
        "max_attempts": 2,
        "min_confidence": 0.45,
        "timeout_s": 6.0
      },
      "slots": {
        "anliegen": {
          "description": "",
          "sensitive": false,
          "type": "choice"
        }
      },
      "start": "begruessung",
      "version": 1
    }
  },
  "vektoren": [
    {
      "art": "yes_no",
      "erwartet": "yes",
      "text": "ja"
    },
    {
      "art": "yes_no",
      "erwartet": "yes",
      "text": "ja genau"
    },
    {
      "art": "yes_no",
      "erwartet": "yes",
      "text": "korrekt"
    },
    {
      "art": "yes_no",
      "erwartet": "yes",
      "text": "passt so"
    },
    {
      "art": "yes_no",
      "erwartet": "no",
      "text": "nein"
    },
    {
      "art": "yes_no",
      "erwartet": "no",
      "text": "nee"
    },
    {
      "art": "yes_no",
      "erwartet": "no",
      "text": "das stimmt nicht"
    },
    {
      "art": "yes_no",
      "erwartet": "no",
      "text": "nicht richtig"
    },
    {
      "art": "yes_no",
      "erwartet": "no",
      "text": "auf keinen Fall nein"
    },
    {
      "art": "yes_no",
      "erwartet": null,
      "text": "Moment mal"
    },
    {
      "art": "number",
      "erwartet": 7,
      "text": "sieben"
    },
    {
      "art": "number",
      "erwartet": 21,
      "text": "einundzwanzig"
    },
    {
      "art": "number",
      "erwartet": 30,
      "text": "dreissig"
    },
    {
      "art": "number",
      "erwartet": 3,
      "text": "3 Stueck"
    },
    {
      "art": "number",
      "erwartet": 2.5,
      "text": "2,5"
    },
    {
      "art": "number",
      "erwartet": null,
      "text": "keine Ahnung"
    },
    {
      "art": "digits",
      "erwartet": "1234",
      "text": "eins zwei drei vier"
    },
    {
      "art": "digits",
      "erwartet": "12345678",
      "text": "12345678"
    },
    {
      "art": "digits",
      "erwartet": "123",
      "text": "eins zwei drei"
    },
    {
      "art": "digits",
      "erwartet": null,
      "text": "keine"
    },
    {
      "art": "digits",
      "erwartet": null,
      "laenge": 8,
      "text": "eins zwei drei vier"
    },
    {
      "art": "digits",
      "erwartet": "12345678",
      "laenge": 8,
      "text": "12345678"
    },
    {
      "art": "digits",
      "erwartet": null,
      "laenge": 8,
      "text": "eins zwei drei"
    },
    {
      "art": "digits",
      "erwartet": null,
      "laenge": 8,
      "text": "keine"
    },
    {
      "art": "date",
      "erwartet": "2026-03-10",
      "text": "heute"
    },
    {
      "art": "date",
      "erwartet": "2026-03-11",
      "text": "morgen bitte"
    },
    {
      "art": "date",
      "erwartet": "2026-03-12",
      "text": "uebermorgen"
    },
    {
      "art": "date",
      "erwartet": "2026-03-14",
      "text": "am 14.3."
    },
    {
      "art": "date",
      "erwartet": "2027-03-14",
      "text": "14.03.2027"
    },
    {
      "art": "date",
      "erwartet": "2026-03-14",
      "text": "am 14. März"
    },
    {
      "art": "date",
      "erwartet": "2026-03-13",
      "text": "am Freitag"
    },
    {
      "art": "date",
      "erwartet": "2026-03-17",
      "text": "Dienstag"
    },
    {
      "art": "date",
      "erwartet": "2027-01-05",
      "text": "am 5.1."
    },
    {
      "art": "date",
      "erwartet": null,
      "text": "am 31.2."
    },
    {
      "art": "date",
      "erwartet": null,
      "text": "weiss nicht"
    },
    {
      "art": "time",
      "erwartet": "14:30",
      "text": "14:30"
    },
    {
      "art": "time",
      "erwartet": "14:30",
      "text": "14 Uhr 30"
    },
    {
      "art": "time",
      "erwartet": "09:00",
      "text": "neun Uhr"
    },
    {
      "art": "time",
      "erwartet": "02:30",
      "text": "halb drei"
    },
    {
      "art": "time",
      "erwartet": "03:15",
      "text": "viertel nach drei"
    },
    {
      "art": "time",
      "erwartet": "03:45",
      "text": "dreiviertel vier"
    },
    {
      "art": "time",
      "erwartet": "15:00",
      "text": "drei Uhr nachmittags"
    },
    {
      "art": "time",
      "erwartet": "14:30",
      "text": "halb drei nachmittags"
    },
    {
      "art": "time",
      "erwartet": null,
      "text": "25 Uhr 99"
    },
    {
      "art": "time",
      "erwartet": null,
      "text": "irgendwann"
    },
    {
      "art": "choice",
      "erwartet": "termin",
      "text": "ich brauche einen Termin"
    },
    {
      "art": "choice",
      "erwartet": "termin",
      "text": "Sprechstunde"
    },
    {
      "art": "choice",
      "erwartet": "krankmeldung",
      "text": "ich moechte mich krank melden"
    },
    {
      "art": "choice",
      "erwartet": "termin",
      "text": "Terminn"
    },
    {
      "art": "choice",
      "erwartet": "krankmeldung",
      "text": "Krankmeldug"
    },
    {
      "art": "choice",
      "erwartet": "pruefungsamt",
      "text": "Prüfungsamt"
    },
    {
      "art": "choice",
      "erwartet": null,
      "text": "ich wollte nur mal fragen"
    },
    {
      "art": "normalize",
      "erwartet": "normalisierung gruess gott herr mueller",
      "text": "normalisierung: Grüß Gott, Herr Müller!"
    },
    {
      "art": "normalize",
      "erwartet": "sie haben 2,5 stunden",
      "text": "Sie haben 2,5 Stunden"
    }
  ]
};
