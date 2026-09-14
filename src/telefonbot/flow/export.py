"""Flow als JSON exportieren.

Gebraucht fuer die Browser-Demo: Sie soll denselben Entscheidungsbaum zeigen
wie der Dienst, nicht eine abgetippte Kopie davon. Der Export ist die einzige
Quelle, aus der die Demo ihren Baum bezieht.
"""

from __future__ import annotations

from typing import Any

from telefonbot.flow.model import Flow, Node


def flow_to_dict(flow: Flow) -> dict[str, Any]:
    """Vollstaendige, JSON-taugliche Darstellung eines Baums."""
    return {
        "id": flow.id,
        "version": flow.version,
        "locale": flow.locale,
        "description": flow.description,
        "start": flow.start,
        "settings": {
            "max_attempts": flow.settings.max_attempts,
            "timeout_s": flow.settings.timeout_s,
            "barge_in": flow.settings.barge_in,
            "min_confidence": flow.settings.min_confidence,
            "escalation_node": flow.settings.escalation_node,
        },
        "slots": {
            name: {
                "type": spec.kind.value,
                "description": spec.description,
                "sensitive": spec.sensitive,
            }
            for name, spec in flow.slots.items()
        },
        "global_commands": [
            {
                "name": command.name,
                "phrases": list(command.phrases),
                "action": command.action,
                "target": command.target,
                "dtmf": command.dtmf,
            }
            for command in flow.global_commands
        ],
        "nodes": {node_id: _node_to_dict(node) for node_id, node in flow.nodes.items()},
    }


def _node_to_dict(node: Node) -> dict[str, Any]:
    body: dict[str, Any] = {"type": node.kind.value}
    for name in (
        "text", "reprompt", "no_input_text", "slot", "action", "assign",
        "target", "reason", "next", "on_yes", "on_no", "on_no_match",
        "on_no_input", "on_error", "max_attempts", "timeout_s", "barge_in",
    ):
        value = getattr(node, name)
        if value is not None:
            body[name] = value
    if node.transitions:
        body["transitions"] = dict(node.transitions)
    if node.args:
        body["args"] = dict(node.args)
    if node.tags:
        body["tags"] = list(node.tags)
    if node.expect is not None:
        expect: dict[str, Any] = {"type": node.expect.kind.value, "fuzzy": node.expect.fuzzy}
        if node.expect.options:
            expect["options"] = {k: list(v) for k, v in node.expect.options.items()}
        if node.expect.dtmf:
            expect["dtmf"] = dict(node.expect.dtmf)
        for key, value in (
            ("min", node.expect.min_value),
            ("max", node.expect.max_value),
            ("length", node.expect.length),
        ):
            if value is not None:
                expect[key] = value
        body["expect"] = expect
    if node.cases:
        body["cases"] = [
            {
                "when": [{"slot": c.slot, "op": c.op, "value": c.value} for c in case.when],
                "next": case.next,
            }
            for case in node.cases
        ]
    return body
