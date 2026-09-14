"""Ausfuehrung eines Entscheidungsbaums.

Die Engine ist ein *synchroner* Zustandsautomat ohne I/O. Sie bekommt
Nutzereingaben herein und gibt Effekte heraus. Alles, was ein Telefonat
ausmacht -- Audio, Timeouts, Barge-in -- liegt in
:mod:`telefonbot.session.call`. Diese Trennung ist der Grund, warum sich der
komplette Gespraechsverlauf in Millisekunden testen laesst.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from telefonbot.flow.effects import Collect, Hangup, Invoke, Speak, Transfer, Turn
from telefonbot.flow.model import (
    ExpectKind,
    ExpectSpec,
    Flow,
    GlobalCommand,
    Node,
    NodeKind,
)
from telefonbot.flow.render import render, render_args

log = logging.getLogger(__name__)

MAX_STEPS_PER_TURN = 50
"""Schutz gegen Zyklen ohne Ansage im Baum (z.B. branch -> branch -> branch)."""


class EngineError(RuntimeError):
    """Der Baum verlangt etwas Unmoegliches (fehlender Knoten, falscher Zustand)."""


@dataclass(frozen=True)
class UserInput:
    """Was der Anrufer in einem Zug geliefert hat."""

    text: str = ""
    dtmf: str = ""
    confidence: float = 1.0
    timed_out: bool = False

    @property
    def empty(self) -> bool:
        return self.timed_out or (not self.text.strip() and not self.dtmf)


@dataclass(frozen=True)
class Interpretation:
    """Ergebnis des Sprachverstehens fuer eine erwartete Antwort."""

    value: Any = None
    confidence: float = 0.0
    raw: str = ""

    @property
    def understood(self) -> bool:
        return self.value is not None


class Interpreter(Protocol):
    """Schnittstelle zum Sprachverstehen (Regeln oder LLM)."""

    def interpret(self, expect: ExpectSpec, user_input: UserInput) -> Interpretation: ...

    def match_global(
        self, commands: list[GlobalCommand], user_input: UserInput
    ) -> GlobalCommand | None: ...


@dataclass
class CallContext:
    """Gespraechszustand: gefuellte Slots plus Metadaten des Anrufs."""

    call_id: str = "local"
    caller: str = ""
    called: str = ""
    slots: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def as_template_context(self) -> dict[str, Any]:
        return {**self.meta, **self.slots, "caller": self.caller, "called": self.called}


class FlowEngine:
    """Fuehrt einen :class:`Flow` schrittweise aus."""

    def __init__(
        self,
        flow: Flow,
        interpreter: Interpreter,
        *,
        context: CallContext | None = None,
    ) -> None:
        self.flow = flow
        self.interpreter = interpreter
        self.context = context or CallContext()
        self.history: list[str] = []
        self.finished = False
        self.finish_reason: str | None = None
        self._current: Node | None = None
        self._pending: Collect | Invoke | None = None
        self._attempts: dict[str, int] = {}

    # ---------------------------------------------------------------- Zustand

    @property
    def slots(self) -> dict[str, Any]:
        return self.context.slots

    @property
    def current_node(self) -> Node | None:
        return self._current

    @property
    def awaiting_input(self) -> bool:
        return isinstance(self._pending, Collect)

    @property
    def awaiting_action(self) -> bool:
        return isinstance(self._pending, Invoke)

    # ------------------------------------------------------------- Ausfuehrung

    def start(self) -> Turn:
        """Startet das Gespraech am Wurzelknoten."""
        if self.history:
            raise EngineError("start() wurde bereits aufgerufen")
        return self._advance(self.flow.start)

    def submit(self, user_input: UserInput) -> Turn:
        """Verarbeitet eine Antwort des Anrufers auf den offenen ``Collect``."""
        pending = self._pending
        if not isinstance(pending, Collect):
            raise EngineError("Es wird gerade keine Eingabe erwartet")
        node = self.flow.node(pending.node_id)

        if not user_input.empty:
            command = self.interpreter.match_global(self.flow.global_commands, user_input)
            if command is not None:
                return self._handle_global(command, node, pending)

        if user_input.empty:
            return self._retry(node, pending, kind="no_input")

        if user_input.confidence < self.flow.settings.min_confidence and not user_input.dtmf:
            log.info(
                "ASR-Konfidenz %.2f unter Schwelle %.2f -- gilt als nicht verstanden",
                user_input.confidence,
                self.flow.settings.min_confidence,
            )
            return self._retry(node, pending, kind="no_match")

        result = self.interpreter.interpret(pending.expect, user_input)
        if not result.understood:
            return self._retry(node, pending, kind="no_match")

        if node.slot:
            self.context.slots[node.slot] = result.value
        self._attempts.pop(node.id, None)
        self._pending = None
        return self._advance(self._next_after_answer(node, result.value))

    def submit_action_result(self, value: Any = None, *, error: str | None = None) -> Turn:
        """Meldet das Ergebnis einer Fachaktion zurueck."""
        pending = self._pending
        if not isinstance(pending, Invoke):
            raise EngineError("Es wird gerade kein Aktionsergebnis erwartet")
        node = self.flow.node(pending.node_id)
        self._pending = None

        if error is not None:
            log.warning("Aktion '%s' fehlgeschlagen: %s", node.action, error)
            self.context.meta["last_error"] = error
            target = node.on_error or self.flow.settings.escalation_node
            if target is None:
                return self._terminate(node, reason="action_failed")
            return self._advance(target)

        if node.assign:
            self.context.slots[node.assign] = value
        if node.next is None:
            return self._terminate(node, reason="completed")
        return self._advance(node.next)

    # ----------------------------------------------------------- interne Logik

    def _advance(self, node_id: str) -> Turn:
        """Laeuft durch den Baum, bis Eingabe noetig ist oder das Gespraech endet."""
        effects: list[Speak] = []
        steps = 0
        next_id: str | None = node_id

        while next_id is not None:
            steps += 1
            if steps > MAX_STEPS_PER_TURN:
                raise EngineError(
                    f"Mehr als {MAX_STEPS_PER_TURN} Knoten ohne Interaktion "
                    f"(Zyklus im Flow '{self.flow.id}' ab '{node_id}'?)"
                )
            node = self.flow.node(next_id)
            self._current = node
            self.history.append(node.id)
            ctx = self.context.as_template_context()

            if node.kind is NodeKind.SAY:
                if node.text:
                    effects.append(self._speak(node, node.text, ctx))
                next_id = node.next
                if next_id is None:
                    return self._terminate(node, reason="completed", effects=effects)
                continue

            if node.kind in (NodeKind.ASK, NodeKind.CONFIRM):
                prompt = node.text or ""
                effects.append(self._speak(node, prompt, ctx))
                collect = self._collect_for(node, attempt=1)
                self._pending = collect
                return Turn(effects=list(effects), pending=collect)

            if node.kind is NodeKind.BRANCH:
                next_id = self._branch_target(node)
                continue

            if node.kind is NodeKind.ACTION:
                if node.text:
                    effects.append(self._speak(node, node.text, ctx))
                invoke = Invoke(
                    action=node.action or "",
                    args=render_args(node.args, ctx),
                    node_id=node.id,
                    assign=node.assign,
                )
                self._pending = invoke
                return Turn(effects=list(effects), pending=invoke)

            if node.kind is NodeKind.TRANSFER:
                if node.text:
                    effects.append(self._speak(node, node.text, ctx))
                self.finished = True
                self.finish_reason = "transferred"
                transfer = Transfer(target=render(node.target, ctx), node_id=node.id)
                self._pending = None
                return Turn(effects=list(effects), pending=transfer)

            if node.kind is NodeKind.HANGUP:
                if node.text:
                    effects.append(self._speak(node, node.text, ctx))
                return self._terminate(node, reason=node.reason or "completed", effects=effects)

            raise EngineError(f"Unbekannter Knotentyp: {node.kind}")

        raise EngineError("Flow endete ohne Abschlussknoten")

    def _speak(self, node: Node, text: str, ctx: dict[str, Any], *, reprompt: bool = False) -> Speak:
        barge_in = node.barge_in if node.barge_in is not None else self.flow.settings.barge_in
        return Speak(
            text=render(text, ctx),
            node_id=node.id,
            barge_in=barge_in,
            is_reprompt=reprompt,
        )

    def _collect_for(self, node: Node, *, attempt: int) -> Collect:
        expect = node.expect or ExpectSpec(kind=ExpectKind.TEXT)
        if node.kind is NodeKind.CONFIRM and node.expect is None:
            expect = ExpectSpec(kind=ExpectKind.YES_NO)
        timeout = node.timeout_s if node.timeout_s is not None else self.flow.settings.timeout_s
        return Collect(
            expect=expect,
            node_id=node.id,
            timeout_s=timeout,
            slot=node.slot,
            attempt=attempt,
        )

    def _next_after_answer(self, node: Node, value: Any) -> str:
        if node.kind is NodeKind.CONFIRM:
            target = node.on_yes if value in (True, "yes") else node.on_no
            if target is None:
                raise EngineError(f"confirm-Knoten '{node.id}' ohne on_yes/on_no")
            return target
        key = _transition_key(value)
        target = node.transitions.get(key) or node.transitions.get("*") or node.next
        if target is None:
            raise EngineError(
                f"Knoten '{node.id}': kein Uebergang fuer Antwort '{key}' und kein 'next'"
            )
        return target

    def _branch_target(self, node: Node) -> str:
        # Bedingungen duerfen auch Kontextvariablen pruefen (z.B. innerhalb_sprechzeit);
        # gleichnamige Slots haben Vorrang.
        werte = self.context.as_template_context()
        for case in node.cases:
            if case.matches(werte):
                return case.next
        if node.next is None:
            raise EngineError(f"branch-Knoten '{node.id}': kein Fall trifft zu und kein 'next'")
        return node.next

    def _retry(self, node: Node, pending: Collect, *, kind: str) -> Turn:
        """Nachfragen -- und nach zu vielen Versuchen eskalieren."""
        attempt = self._attempts.get(node.id, 0) + 1
        self._attempts[node.id] = attempt
        limit = node.max_attempts if node.max_attempts is not None else self.flow.settings.max_attempts

        if attempt <= limit:
            ctx = self.context.as_template_context()
            text = (node.no_input_text if kind == "no_input" else None) or node.reprompt or node.text
            effects = [self._speak(node, text or "", ctx, reprompt=True)]
            collect = self._collect_for(node, attempt=pending.attempt + 1)
            self._pending = collect
            return Turn(effects=effects, pending=collect)

        self._attempts.pop(node.id, None)
        self._pending = None
        self.context.meta["escalation_reason"] = kind
        target = (
            (node.on_no_input if kind == "no_input" else node.on_no_match)
            or node.on_no_match
            or self.flow.settings.escalation_node
        )
        if target is None:
            return self._terminate(node, reason=f"max_attempts_{kind}")
        return self._advance(target)

    def _handle_global(self, command: GlobalCommand, node: Node, pending: Collect) -> Turn:
        """Globale Kommandos: wiederholen, zurueck, direkt springen."""
        log.info("Globales Kommando '%s' erkannt", command.name)
        if command.action == "repeat":
            ctx = self.context.as_template_context()
            effects = [self._speak(node, node.text or "", ctx, reprompt=True)]
            collect = self._collect_for(node, attempt=pending.attempt + 1)
            self._pending = collect
            return Turn(effects=effects, pending=collect)
        if command.action == "back":
            target = self._previous_interactive_node(node.id) or self.flow.start
            self._pending = None
            self._attempts.pop(node.id, None)
            return self._advance(target)
        if command.action == "goto":
            if not command.target:
                raise EngineError(f"Globales Kommando '{command.name}' ohne Ziel")
            self._pending = None
            self.context.meta["global_command"] = command.name
            return self._advance(command.target)
        raise EngineError(f"Unbekannte Kommando-Aktion: {command.action}")

    def _previous_interactive_node(self, current_id: str) -> str | None:
        for node_id in reversed(self.history[:-1]):
            if node_id == current_id:
                continue
            node = self.flow.nodes.get(node_id)
            if node and node.kind in (NodeKind.ASK, NodeKind.CONFIRM):
                return node_id
        return None

    def _terminate(self, node: Node, *, reason: str, effects: list[Speak] | None = None) -> Turn:
        self.finished = True
        self.finish_reason = reason
        self._pending = None
        return Turn(effects=list(effects or []), pending=Hangup(node_id=node.id, reason=reason))


def _transition_key(value: Any) -> str:
    """Normalisiert einen Antwortwert zum Schluessel in ``transitions``."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)
