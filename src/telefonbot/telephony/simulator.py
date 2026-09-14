"""Textsimulator: einen Dialogbaum am Schreibtisch durchspielen.

Der schnellste Weg, einen Entscheidungsbaum zu entwerfen, ist ihn zu
durchlaufen -- ohne Telefonanlage, ohne Modelle. Der Simulator nutzt exakt
dieselbe Engine und dasselbe Sprachverstehen wie der Telefonbetrieb; nur Audio
und Spracherkennung fallen weg.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Callable

from telefonbot.flow.effects import Collect, Hangup, Invoke, Speak, Transfer
from telefonbot.flow.engine import CallContext, FlowEngine, UserInput
from telefonbot.flow.model import Flow
from telefonbot.nlu.rules import RuleInterpreter


@dataclass
class SimulationStep:
    """Ein Schritt im simulierten Gespraech."""

    bot: list[str] = field(default_factory=list)
    eingabe: str | None = None
    knoten: str = ""


@dataclass
class SimulationResult:
    """Ergebnis eines simulierten Gespraechs."""

    steps: list[SimulationStep] = field(default_factory=list)
    slots: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    transfer_target: str | None = None
    history: list[str] = field(default_factory=list)

    def transcript(self) -> list[str]:
        lines: list[str] = []
        for step in self.steps:
            lines.extend(f"Bot   : {text}" for text in step.bot)
            if step.eingabe is not None:
                lines.append(f"Anrufer: {step.eingabe}")
        return lines


def simulate(
    flow: Flow,
    inputs: list[str] | Callable[[list[str]], str],
    *,
    today: dt.date | None = None,
    action_results: dict[str, Any] | None = None,
    max_steps: int = 50,
) -> SimulationResult:
    """Spielt einen Baum mit vorgegebenen oder interaktiven Eingaben durch.

    ``inputs`` ist entweder eine Liste von Antworten oder eine Funktion, die zu
    den zuletzt gesagten Ansagen die naechste Antwort liefert (interaktiv).
    Eine Tasteneingabe wird als ``"#1"`` geschrieben.
    """
    engine = FlowEngine(flow, RuleInterpreter(today=today), context=CallContext(call_id="sim"))
    results = action_results or {}
    queue = list(inputs) if isinstance(inputs, list) else None
    result = SimulationResult()

    turn = engine.start()
    for _ in range(max_steps):
        step = SimulationStep(
            bot=[e.text for e in turn.all_effects if isinstance(e, Speak) and e.text],
            knoten=engine.current_node.id if engine.current_node else "",
        )
        pending = turn.pending

        if isinstance(pending, Hangup):
            result.steps.append(step)
            result.reason = pending.reason
            break
        if isinstance(pending, Transfer):
            result.steps.append(step)
            result.reason = "transferred"
            result.transfer_target = pending.target
            break
        if isinstance(pending, Invoke):
            result.steps.append(step)
            turn = engine.submit_action_result(results.get(pending.action, f"{pending.action}-ok"))
            continue
        if isinstance(pending, Collect):
            if queue is not None:
                if not queue:
                    result.reason = "keine weiteren Eingaben"
                    result.steps.append(step)
                    break
                answer = queue.pop(0)
            else:
                answer = inputs(step.bot)  # type: ignore[operator]
            step.eingabe = answer
            result.steps.append(step)
            turn = engine.submit(_to_input(answer))
            continue
    else:
        result.reason = "max_steps"

    result.slots = dict(engine.slots)
    result.history = list(engine.history)
    return result


def _to_input(answer: str) -> UserInput:
    """``"#12"`` sind Tasten, ``""`` ist Schweigen, alles andere ist Sprache."""
    answer = answer.strip()
    if not answer:
        return UserInput(timed_out=True)
    if answer.startswith("#"):
        return UserInput(dtmf=answer[1:])
    return UserInput(text=answer, confidence=1.0)
