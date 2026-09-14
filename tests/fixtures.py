"""Ein kleiner, realistischer Flow fuer Engine-Tests."""

import textwrap

DEMO_FLOW_YAML = textwrap.dedent(
    """
    id: demo
    version: 1
    start: begruessung
    description: Testbaum mit allen Knotentypen
    settings:
      max_attempts: 2
      timeout_s: 5
      min_confidence: 0.5
      escalation_node: weiterleitung
    slots:
      anliegen: { type: choice }
      datum: { type: date }
      matrikelnummer: { type: digits, sensitive: true }
      ticket_id: { type: text }
    global_commands:
      - name: mensch
        phrases: ["mitarbeiter", "mensch", "echten menschen", "sprechstunde persoenlich"]
        action: goto
        target: weiterleitung
        dtmf: "0"
      - name: wiederholen
        phrases: ["wiederholen", "noch mal", "nochmal"]
        action: repeat
    nodes:
      begruessung:
        type: say
        text: "Guten Tag, hier ist der Sprachassistent des Lehrstuhls."
        next: hauptmenue
      hauptmenue:
        type: ask
        text: "Geht es um einen Termin oder um eine Krankmeldung?"
        reprompt: "Bitte sagen Sie Termin oder Krankmeldung."
        slot: anliegen
        expect:
          type: choice
          options:
            termin: ["termin", "sprechstunde", "beratung"]
            krankmeldung: ["krankmeldung", "krank", "krank melden"]
          dtmf: { "1": termin, "2": krankmeldung }
        transitions:
          termin: termin_datum
          krankmeldung: krank_matrikel
      termin_datum:
        type: ask
        text: "An welchem Tag?"
        slot: datum
        expect: date
        next: termin_bestaetigen
      termin_bestaetigen:
        type: confirm
        text: "Termin am {datum}. Ist das richtig?"
        on_yes: termin_buchen
        on_no: termin_datum
      termin_buchen:
        type: action
        action: create_appointment
        args: { datum: "{datum}", anliegen: "{anliegen}" }
        assign: ticket_id
        next: termin_fertig
        on_error: weiterleitung
      termin_fertig:
        type: hangup
        text: "Ihr Termin am {datum} ist notiert, Vorgangsnummer {ticket_id}. Auf Wiederhoeren."
        reason: completed
      krank_matrikel:
        type: ask
        text: "Bitte nennen Sie Ihre achtstellige Matrikelnummer."
        slot: matrikelnummer
        expect: { type: digits, length: 8 }
        next: krank_pruefen
      krank_pruefen:
        type: branch
        cases:
          - when: [{ slot: matrikelnummer, op: set }]
            next: krank_fertig
        next: weiterleitung
      krank_fertig:
        type: hangup
        text: "Die Krankmeldung fuer {matrikelnummer} ist vermerkt."
      weiterleitung:
        type: transfer
        text: "Ich verbinde Sie mit dem Sekretariat."
        target: "PJSIP/sekretariat"
    """
)
