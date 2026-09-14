"""Regelbasiertes Sprachverstehen.

Deterministisch, erklaerbar und ohne Modell -- fuer einen Behoerden-/Uni-Kontext
der richtige Default: Was der Bot versteht, steht nachvollziehbar im Flow.
Fuer freie Formulierungen kann ein LLM nachgeschaltet werden
(:mod:`telefonbot.nlu.llm`), das aber nur *klassifiziert*, nie entscheidet.
"""

from __future__ import annotations

import datetime as dt
import logging
from difflib import SequenceMatcher

from telefonbot.flow.engine import Interpretation, UserInput
from telefonbot.flow.model import ExpectKind, ExpectSpec, GlobalCommand
from telefonbot.nlu import german

log = logging.getLogger(__name__)

FUZZY_THRESHOLD = 0.82
"""Ab dieser Aehnlichkeit gilt ein Synonym als getroffen (Tippfehler der ASR)."""

AMBIGUITY_MARGIN = 0.08
"""Liegen die zwei besten Optionen so dicht beieinander, wird nachgefragt."""


class RuleInterpreter:
    """Setzt :class:`telefonbot.flow.engine.Interpreter` regelbasiert um."""

    def __init__(self, *, today: dt.date | None = None, fuzzy_threshold: float = FUZZY_THRESHOLD):
        self._today = today
        self.fuzzy_threshold = fuzzy_threshold

    @property
    def today(self) -> dt.date:
        return self._today or dt.date.today()

    # ------------------------------------------------------------------- API

    def interpret(self, expect: ExpectSpec, user_input: UserInput) -> Interpretation:
        """Bildet eine Aeusserung auf den erwarteten Wert ab."""
        if user_input.dtmf:
            hit = self._from_dtmf(expect, user_input.dtmf)
            if hit is not None:
                return hit

        text = user_input.text or ""
        if not text.strip():
            return Interpretation(raw=text)

        if expect.kind is ExpectKind.YES_NO:
            value = german.parse_yes_no(text)
            if value is None:
                return Interpretation(raw=text)
            return Interpretation(value="yes" if value else "no", confidence=1.0, raw=text)

        if expect.kind is ExpectKind.CHOICE:
            return self._match_choice(expect, text)

        if expect.kind is ExpectKind.NUMBER:
            value = german.parse_number(text)
            if value is None or not self._in_range(expect, value):
                return Interpretation(raw=text)
            as_int = int(value)
            return Interpretation(
                value=as_int if float(as_int) == value else value, confidence=1.0, raw=text
            )

        if expect.kind is ExpectKind.DIGITS:
            value = german.parse_digits(text, length=expect.length)
            return Interpretation(value=value, confidence=1.0 if value else 0.0, raw=text)

        if expect.kind is ExpectKind.DATE:
            value = german.parse_date(text, today=self.today)
            return Interpretation(value=value, confidence=1.0 if value else 0.0, raw=text)

        if expect.kind is ExpectKind.TIME:
            value = german.parse_time(text)
            return Interpretation(value=value, confidence=1.0 if value else 0.0, raw=text)

        # ExpectKind.TEXT: freie Eingabe, wird unveraendert uebernommen.
        cleaned = text.strip()
        return Interpretation(value=cleaned or None, confidence=1.0 if cleaned else 0.0, raw=text)

    def match_global(
        self, commands: list[GlobalCommand], user_input: UserInput
    ) -> GlobalCommand | None:
        """Erkennt globale Kommandos ("Mitarbeiter", "wiederholen", "Notfall")."""
        for command in commands:
            if user_input.dtmf and command.dtmf and user_input.dtmf == command.dtmf:
                return command
        norm = german.normalize(user_input.text)
        if not norm:
            return None
        words = set(german.tokens(norm))
        for command in commands:
            for phrase in command.phrases:
                phrase_norm = german.normalize(phrase)
                if not phrase_norm:
                    continue
                if " " in phrase_norm:
                    if phrase_norm in norm:
                        return command
                elif phrase_norm in words:
                    return command
        return None

    # -------------------------------------------------------------- intern

    def _from_dtmf(self, expect: ExpectSpec, dtmf: str) -> Interpretation | None:
        if expect.dtmf:
            mapped = expect.dtmf.get(dtmf)
            if mapped is not None:
                return Interpretation(value=mapped, confidence=1.0, raw=dtmf)
        if expect.kind is ExpectKind.DIGITS:
            if expect.length is not None and len(dtmf) != expect.length:
                return None
            return Interpretation(value=dtmf, confidence=1.0, raw=dtmf)
        if expect.kind is ExpectKind.NUMBER and dtmf.isdigit():
            value = int(dtmf)
            return Interpretation(value=value, confidence=1.0, raw=dtmf) if self._in_range(
                expect, value
            ) else None
        if expect.kind is ExpectKind.YES_NO and dtmf in ("1", "2"):
            return Interpretation(value="yes" if dtmf == "1" else "no", confidence=1.0, raw=dtmf)
        return None

    def _match_choice(self, expect: ExpectSpec, text: str) -> Interpretation:
        """Bestes Synonym gewinnt; bei Gleichstand wird lieber nachgefragt."""
        norm = german.normalize(text)
        words = german.tokens(norm)
        scores: dict[str, float] = {}

        for value, synonyms in expect.options.items():
            best = 0.0
            for synonym in synonyms:
                syn = german.normalize(synonym)
                if not syn:
                    continue
                if " " in syn:
                    if syn in norm:
                        best = max(best, 1.0)
                        continue
                elif syn in words:
                    best = max(best, 1.0)
                    continue
                if expect.fuzzy:
                    best = max(best, self._fuzzy_score(syn, words, norm))
            if best > 0:
                scores[value] = best

        if not scores:
            return Interpretation(raw=text)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best_value, best_score = ranked[0]
        if best_score < self.fuzzy_threshold:
            return Interpretation(raw=text)
        if len(ranked) > 1 and best_score - ranked[1][1] < AMBIGUITY_MARGIN:
            log.info("Mehrdeutige Antwort %r: %s", text, ranked[:2])
            return Interpretation(raw=text)
        return Interpretation(value=best_value, confidence=best_score, raw=text)

    def _fuzzy_score(self, synonym: str, words: list[str], norm: str) -> float:
        """Aehnlichkeit gegen einzelne Woerter und gegen die ganze Aeusserung."""
        best = SequenceMatcher(None, synonym, norm).ratio()
        for word in words:
            best = max(best, SequenceMatcher(None, synonym, word).ratio())
            if synonym.startswith(word) and len(word) >= 5:
                best = max(best, 0.9)  # abgeschnittene Woerter der ASR
        return best

    @staticmethod
    def _in_range(expect: ExpectSpec, value: float) -> bool:
        if expect.min_value is not None and value < expect.min_value:
            return False
        if expect.max_value is not None and value > expect.max_value:
            return False
        return True
