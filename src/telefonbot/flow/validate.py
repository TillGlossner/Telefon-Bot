"""Statische Pruefung eines Entscheidungsbaums.

Ein Dialogbaum ist Software, auch wenn er in YAML steht. Diese Pruefungen
fangen die Fehlerklassen ab, die im Betrieb am teuersten sind: Sackgassen,
tote Knoten, Uebergaenge auf nicht existierende Ziele, Platzhalter ohne Slot.
"""

from __future__ import annotations

from dataclasses import dataclass

from telefonbot.flow.model import ExpectKind, Flow, NodeKind
from telefonbot.flow.render import placeholders


@dataclass(frozen=True)
class Issue:
    """Ein Befund der Validierung."""

    severity: str  # "error" | "warning"
    code: str
    message: str
    node_id: str | None = None

    def __str__(self) -> str:
        where = f"[{self.node_id}] " if self.node_id else ""
        return f"{self.severity.upper()} {self.code}: {where}{self.message}"


def validate_flow(flow: Flow) -> list[Issue]:
    """Prueft Struktur und Erreichbarkeit; gibt Fehler und Warnungen zurueck."""
    issues: list[Issue] = []
    issues += _check_references(flow)
    issues += _check_node_shape(flow)
    issues += _check_placeholders(flow)
    issues += _check_reachability(flow)
    issues += _check_termination(flow)
    return issues


def _check_references(flow: Flow) -> list[Issue]:
    issues: list[Issue] = []
    if flow.start not in flow.nodes:
        issues.append(
            Issue("error", "missing_start", f"Startknoten '{flow.start}' existiert nicht")
        )
    for node in flow.nodes.values():
        for target in node.successors():
            if target not in flow.nodes:
                issues.append(
                    Issue("error", "dangling_edge", f"Uebergang auf unbekannten Knoten '{target}'", node.id)
                )
    for command in flow.global_commands:
        if command.action == "goto" and command.target not in flow.nodes:
            issues.append(
                Issue(
                    "error",
                    "dangling_global",
                    f"Globales Kommando '{command.name}' zeigt auf unbekannten Knoten "
                    f"'{command.target}'",
                )
            )
    escalation = flow.settings.escalation_node
    if escalation and escalation not in flow.nodes:
        issues.append(
            Issue("error", "dangling_escalation", f"escalation_node '{escalation}' existiert nicht")
        )
    return issues


def _check_node_shape(flow: Flow) -> list[Issue]:
    issues: list[Issue] = []
    for node in flow.nodes.values():
        if node.kind in (NodeKind.ASK, NodeKind.CONFIRM) and not node.text:
            issues.append(Issue("error", "missing_prompt", "Frage ohne Ansagetext", node.id))

        if node.kind is NodeKind.ASK:
            if node.expect is None:
                issues.append(Issue("error", "missing_expect", "ask-Knoten ohne 'expect'", node.id))
            elif node.expect.kind is ExpectKind.CHOICE:
                if not node.expect.options:
                    issues.append(
                        Issue("error", "empty_choice", "choice ohne 'options'", node.id)
                    )
                unknown = set(node.transitions) - set(node.expect.options) - {"*"}
                if unknown:
                    issues.append(
                        Issue(
                            "error",
                            "unknown_transition",
                            f"Uebergaenge {sorted(unknown)} entsprechen keiner Option "
                            f"{sorted(node.expect.options)}",
                            node.id,
                        )
                    )
                missing = set(node.expect.options) - set(node.transitions)
                if missing and "*" not in node.transitions and not node.next:
                    issues.append(
                        Issue(
                            "error",
                            "unhandled_option",
                            f"Optionen ohne Uebergang: {sorted(missing)}",
                            node.id,
                        )
                    )
                for value, target in node.expect.dtmf.items():
                    if target not in node.expect.options:
                        issues.append(
                            Issue(
                                "error",
                                "unknown_dtmf",
                                f"DTMF '{value}' zeigt auf unbekannte Option '{target}'",
                                node.id,
                            )
                        )
            elif node.expect.kind is ExpectKind.YES_NO:
                unknown = set(node.transitions) - {"yes", "no", "*"}
                if unknown:
                    issues.append(
                        Issue(
                            "error",
                            "unknown_transition",
                            f"Uebergaenge {sorted(unknown)} passen nicht zu einer Ja/Nein-Frage "
                            "(erlaubt: yes, no, *)",
                            node.id,
                        )
                    )
                missing = {"yes", "no"} - set(node.transitions)
                if missing and "*" not in node.transitions and not node.next:
                    issues.append(
                        Issue(
                            "error",
                            "unhandled_option",
                            f"Antworten ohne Uebergang: {sorted(missing)}",
                            node.id,
                        )
                    )
            elif not node.transitions and not node.next:
                issues.append(
                    Issue("error", "missing_next", "ask-Knoten ohne 'next'/'transitions'", node.id)
                )
            if not node.slot:
                issues.append(
                    Issue("warning", "no_slot", "Antwort wird nicht in einem Slot gespeichert", node.id)
                )

        if node.kind is NodeKind.CONFIRM and (not node.on_yes or not node.on_no):
            issues.append(
                Issue("error", "missing_branch", "confirm-Knoten braucht 'on_yes' und 'on_no'", node.id)
            )
        if node.kind is NodeKind.BRANCH:
            if not node.cases:
                issues.append(Issue("error", "empty_branch", "branch-Knoten ohne 'cases'", node.id))
            if not node.next:
                issues.append(
                    Issue(
                        "warning",
                        "branch_without_default",
                        "kein 'next' als Default -- trifft kein Fall zu, bricht das Gespraech ab",
                        node.id,
                    )
                )
            for case in node.cases:
                for cond in case.when:
                    if flow.slots and cond.slot not in flow.slots:
                        issues.append(
                            Issue(
                                "warning",
                                "undeclared_slot",
                                f"Bedingung nutzt undeklarierten Slot '{cond.slot}'",
                                node.id,
                            )
                        )
        if node.kind is NodeKind.ACTION and not node.action:
            issues.append(Issue("error", "missing_action", "action-Knoten ohne 'action'", node.id))
        if node.kind is NodeKind.TRANSFER and not node.target:
            issues.append(Issue("error", "missing_target", "transfer-Knoten ohne 'target'", node.id))
        if node.kind is NodeKind.SAY and not node.text:
            issues.append(Issue("warning", "empty_say", "say-Knoten ohne Text", node.id))
        if node.slot and flow.slots and node.slot not in flow.slots:
            issues.append(
                Issue("warning", "undeclared_slot", f"Slot '{node.slot}' ist nicht deklariert", node.id)
            )
    return issues


def _check_placeholders(flow: Flow) -> list[Issue]:
    known = set(flow.slots) | {"caller", "called", "last_error", "escalation_reason", "global_command"}
    issues: list[Issue] = []
    for node in flow.nodes.values():
        used: set[str] = set()
        for text in (node.text, node.reprompt, node.no_input_text, node.target):
            used |= placeholders(text)
        for value in node.args.values():
            if isinstance(value, str):
                used |= placeholders(value)
        if not flow.slots:
            continue
        for name in sorted(used - known):
            issues.append(
                Issue("warning", "unknown_placeholder", f"Platzhalter '{{{name}}}' ist kein Slot", node.id)
            )
    return issues


def _check_reachability(flow: Flow) -> list[Issue]:
    if flow.start not in flow.nodes:
        return []
    reachable: set[str] = set()
    stack = [flow.start] + [c.target for c in flow.global_commands if c.target]
    if flow.settings.escalation_node:
        stack.append(flow.settings.escalation_node)
    while stack:
        node_id = stack.pop()
        if node_id in reachable or node_id not in flow.nodes:
            continue
        reachable.add(node_id)
        stack.extend(flow.nodes[node_id].successors())
    return [
        Issue("warning", "unreachable", "Knoten ist von keinem Pfad aus erreichbar", node_id)
        for node_id in sorted(set(flow.nodes) - reachable)
    ]


def _check_termination(flow: Flow) -> list[Issue]:
    """Jeder Knoten muss ein Gespraechsende erreichen koennen."""
    terminal = {
        node.id
        for node in flow.nodes.values()
        if node.kind in (NodeKind.HANGUP, NodeKind.TRANSFER)
    }
    if not terminal:
        return [Issue("error", "no_terminal", "Flow hat keinen hangup-/transfer-Knoten")]

    can_end = set(terminal)
    changed = True
    while changed:
        changed = False
        for node in flow.nodes.values():
            if node.id in can_end:
                continue
            if any(target in can_end for target in node.successors()):
                can_end.add(node.id)
                changed = True
    return [
        Issue("error", "dead_end", "Von hier aus ist kein Gespraechsende erreichbar", node_id)
        for node_id in sorted(set(flow.nodes) - can_end)
    ]
