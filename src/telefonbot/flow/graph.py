"""Entscheidungsbaum als Diagramm.

Fachabteilungen pruefen einen Dialog nicht im YAML, sondern am Bild. Der Export
nach Mermaid laesst sich in GitLab/GitHub, Confluence und VS Code direkt
anzeigen -- ohne Zusatzwerkzeug.
"""

from __future__ import annotations

from telefonbot.flow.model import Flow, NodeKind

_SHAPES = {
    NodeKind.SAY: ("[", "]"),
    NodeKind.ASK: ("{{", "}}"),
    NodeKind.CONFIRM: ("{{", "}}"),
    NodeKind.BRANCH: ("{", "}"),
    NodeKind.ACTION: ("[[", "]]"),
    NodeKind.TRANSFER: ("([", "])"),
    NodeKind.HANGUP: ("([", "])"),
}


def to_mermaid(flow: Flow, *, with_text: bool = True, max_text: int = 40) -> str:
    """Erzeugt ein Mermaid-Flussdiagramm des Baums."""
    lines = [f"%% Flow {flow.id} v{flow.version}", "flowchart TD"]

    for node in flow.nodes.values():
        open_shape, close_shape = _SHAPES[node.kind]
        label = node.id
        if with_text and node.text:
            label = f"{node.id}<br/>{_escape(_shorten(node.text, max_text))}"
        lines.append(f"  {node.id}{open_shape}\"{label}\"{close_shape}")

    for node in flow.nodes.values():
        for value, target in node.transitions.items():
            lines.append(f"  {node.id} -->|{_escape(value)}| {target}")
        if node.on_yes:
            lines.append(f"  {node.id} -->|ja| {node.on_yes}")
        if node.on_no:
            lines.append(f"  {node.id} -->|nein| {node.on_no}")
        for index, case in enumerate(node.cases, start=1):
            condition = " und ".join(f"{c.slot} {c.op} {c.value}" for c in case.when) or f"Fall {index}"
            lines.append(f"  {node.id} -->|{_escape(condition)}| {case.next}")
        if node.next:
            label = "sonst" if node.kind is NodeKind.BRANCH else ""
            arrow = f" -->|{label}| " if label else " --> "
            lines.append(f"  {node.id}{arrow}{node.next}")
        if node.on_no_match:
            lines.append(f"  {node.id} -.->|nicht verstanden| {node.on_no_match}")
        if node.on_no_input:
            lines.append(f"  {node.id} -.->|keine Antwort| {node.on_no_input}")
        if node.on_error:
            lines.append(f"  {node.id} -.->|Fehler| {node.on_error}")

    for command in flow.global_commands:
        if command.action == "goto" and command.target:
            lines.append(f"  GLOBAL_{command.name}[/\"{_escape(command.name)} (ueberall)\"/]")
            lines.append(f"  GLOBAL_{command.name} -.-> {command.target}")

    lines.append(f"  START(( )) --> {flow.start}")
    return "\n".join(lines)


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _escape(text: str) -> str:
    return text.replace('"', "'").replace("|", "/")
