"""YAML -> :class:`Flow`.

Fehler in Dialogbaeumen sollen beim Laden auffallen, nicht im Telefonat.
Deshalb ist der Loader streng und gibt praezise Fehlermeldungen mit Knotenbezug.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from telefonbot.flow.model import (
    Case,
    Condition,
    ExpectKind,
    ExpectSpec,
    Flow,
    FlowSettings,
    GlobalCommand,
    Node,
    NodeKind,
    SlotSpec,
)


class FlowLoadError(ValueError):
    """Der Flow ist syntaktisch oder strukturell fehlerhaft."""


def load_flow_file(path: str | Path, *, strict: bool = True) -> Flow:
    """Laedt einen Flow aus einer YAML-Datei."""
    import yaml  # lokal importiert: der Engine-Kern bleibt ohne Fremdabhaengigkeit

    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise FlowLoadError(f"{path}: YAML nicht lesbar: {exc}") from exc
    except OSError as exc:
        raise FlowLoadError(f"{path}: Datei nicht lesbar: {exc}") from exc
    try:
        return load_flow(raw, strict=strict)
    except FlowLoadError as exc:
        raise FlowLoadError(f"{path}: {exc}") from exc


def load_flow(raw: Any, *, strict: bool = True) -> Flow:
    """Baut einen Flow aus einer bereits geparsten YAML-Struktur."""
    if not isinstance(raw, dict):
        raise FlowLoadError("Flow-Datei muss ein YAML-Mapping sein")

    flow_id = _require_str(raw, "id")
    start = _require_str(raw, "start")
    raw_nodes = raw.get("nodes")
    if not isinstance(raw_nodes, dict) or not raw_nodes:
        raise FlowLoadError("'nodes' fehlt oder ist leer")

    nodes = {node_id: _node(node_id, body) for node_id, body in raw_nodes.items()}
    flow = Flow(
        id=flow_id,
        start=start,
        nodes=nodes,
        version=int(raw.get("version", 1)),
        locale=str(raw.get("locale", "de-DE")),
        description=str(raw.get("description", "")),
        slots=_slots(raw.get("slots") or {}),
        global_commands=_global_commands(raw.get("global_commands") or []),
        settings=_settings(raw.get("settings") or {}),
    )

    from telefonbot.flow.validate import validate_flow  # zirkulaeren Import vermeiden

    issues = validate_flow(flow)
    errors = [i for i in issues if i.severity == "error"]
    if errors and strict:
        raise FlowLoadError(
            "Flow ist nicht ausfuehrbar:\n" + "\n".join(f"  - {i}" for i in errors)
        )
    return flow


# --------------------------------------------------------------------- Details


def _require_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FlowLoadError(f"'{key}' fehlt oder ist kein nicht-leerer String")
    return value.strip()


def _node(node_id: str, body: Any) -> Node:
    if not isinstance(body, dict):
        raise FlowLoadError(f"Knoten '{node_id}': muss ein Mapping sein")
    kind_raw = body.get("type")
    try:
        kind = NodeKind(str(kind_raw))
    except ValueError:
        allowed = ", ".join(k.value for k in NodeKind)
        raise FlowLoadError(
            f"Knoten '{node_id}': unbekannter Typ '{kind_raw}' (erlaubt: {allowed})"
        ) from None

    unknown = set(body) - _ALLOWED_NODE_KEYS
    if unknown:
        raise FlowLoadError(
            f"Knoten '{node_id}': unbekannte Felder {sorted(unknown)} "
            "(Tippfehler? erlaubt sind u.a. text, next, expect, transitions)"
        )

    transitions = body.get("transitions") or {}
    if not isinstance(transitions, dict):
        raise FlowLoadError(f"Knoten '{node_id}': 'transitions' muss ein Mapping sein")

    return Node(
        id=node_id,
        kind=kind,
        text=_opt_str(body.get("text") or body.get("prompt")),
        reprompt=_opt_str(body.get("reprompt")),
        no_input_text=_opt_str(body.get("no_input_text")),
        slot=_opt_str(body.get("slot")),
        expect=_expect(node_id, body.get("expect")),
        transitions={_key(k): str(v) for k, v in transitions.items()},
        cases=_cases(node_id, body.get("cases") or []),
        action=_opt_str(body.get("action")),
        args=dict(body.get("args") or {}),
        assign=_opt_str(body.get("assign")),
        target=_opt_str(body.get("target")),
        reason=_opt_str(body.get("reason")),
        next=_opt_str(body.get("next")),
        on_yes=_opt_str(body.get("on_yes")),
        on_no=_opt_str(body.get("on_no")),
        on_no_match=_opt_str(body.get("on_no_match")),
        on_no_input=_opt_str(body.get("on_no_input")),
        on_error=_opt_str(body.get("on_error")),
        max_attempts=_opt_int(body.get("max_attempts")),
        timeout_s=_opt_float(body.get("timeout_s")),
        barge_in=body.get("barge_in"),
        tags=[str(t) for t in (body.get("tags") or [])],
    )


_ALLOWED_NODE_KEYS = {
    "type", "text", "prompt", "reprompt", "no_input_text", "slot", "expect",
    "transitions", "cases", "action", "args", "assign", "target", "reason",
    "next", "on_yes", "on_no", "on_no_match", "on_no_input", "on_error",
    "max_attempts", "timeout_s", "barge_in", "tags", "comment",
}


def _expect(node_id: str, raw: Any) -> ExpectSpec | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = {"type": raw}
    if not isinstance(raw, dict):
        raise FlowLoadError(f"Knoten '{node_id}': 'expect' muss String oder Mapping sein")
    try:
        kind = ExpectKind(str(raw.get("type", "text")))
    except ValueError:
        allowed = ", ".join(k.value for k in ExpectKind)
        raise FlowLoadError(
            f"Knoten '{node_id}': unbekannter expect-Typ '{raw.get('type')}' (erlaubt: {allowed})"
        ) from None

    options_raw = raw.get("options") or {}
    if isinstance(options_raw, list):  # Kurzform: nur Werte, Synonym == Wert
        options_raw = {_key(v): [_key(v)] for v in options_raw}
    if not isinstance(options_raw, dict):
        raise FlowLoadError(f"Knoten '{node_id}': 'options' muss Mapping oder Liste sein")
    options = {
        _key(key): [str(s) for s in (syn if isinstance(syn, list) else [syn])]
        for key, syn in options_raw.items()
    }
    return ExpectSpec(
        kind=kind,
        options=options,
        dtmf={str(k): _key(v) for k, v in (raw.get("dtmf") or {}).items()},
        min_value=_opt_float(raw.get("min")),
        max_value=_opt_float(raw.get("max")),
        length=_opt_int(raw.get("length")),
        fuzzy=bool(raw.get("fuzzy", True)),
    )


def _cases(node_id: str, raw: Any) -> list[Case]:
    if not isinstance(raw, list):
        raise FlowLoadError(f"Knoten '{node_id}': 'cases' muss eine Liste sein")
    cases: list[Case] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or "next" not in item:
            raise FlowLoadError(f"Knoten '{node_id}', Fall {index}: 'next' fehlt")
        when_raw = item.get("when") or []
        if isinstance(when_raw, dict):
            when_raw = [when_raw]
        conditions = []
        for cond in when_raw:
            if not isinstance(cond, dict) or "slot" not in cond:
                raise FlowLoadError(f"Knoten '{node_id}', Fall {index}: Bedingung ohne 'slot'")
            op = str(cond.get("op", "eq"))
            if op not in Condition.OPS:
                raise FlowLoadError(
                    f"Knoten '{node_id}', Fall {index}: unbekannter Operator '{op}' "
                    f"(erlaubt: {', '.join(Condition.OPS)})"
                )
            conditions.append(Condition(slot=str(cond["slot"]), op=op, value=cond.get("value")))
        cases.append(Case(when=conditions, next=str(item["next"])))
    return cases


def _slots(raw: Any) -> dict[str, SlotSpec]:
    if not isinstance(raw, dict):
        raise FlowLoadError("'slots' muss ein Mapping sein")
    out: dict[str, SlotSpec] = {}
    for name, body in raw.items():
        body = body or {}
        if isinstance(body, str):
            body = {"type": body}
        try:
            kind = ExpectKind(str(body.get("type", "text")))
        except ValueError:
            raise FlowLoadError(f"Slot '{name}': unbekannter Typ '{body.get('type')}'") from None
        out[str(name)] = SlotSpec(
            name=str(name),
            kind=kind,
            description=str(body.get("description", "")),
            sensitive=bool(body.get("sensitive", False)),
        )
    return out


def _global_commands(raw: Any) -> list[GlobalCommand]:
    if not isinstance(raw, list):
        raise FlowLoadError("'global_commands' muss eine Liste sein")
    commands: list[GlobalCommand] = []
    for item in raw:
        if not isinstance(item, dict) or "name" not in item:
            raise FlowLoadError("Globales Kommando ohne 'name'")
        action = str(item.get("action", "goto"))
        if action not in ("goto", "repeat", "back"):
            raise FlowLoadError(
                f"Globales Kommando '{item['name']}': unbekannte Aktion '{action}'"
            )
        phrases = item.get("phrases") or []
        if isinstance(phrases, str):
            phrases = [phrases]
        commands.append(
            GlobalCommand(
                name=str(item["name"]),
                phrases=[str(p) for p in phrases],
                action=action,
                target=_opt_str(item.get("target")),
                dtmf=_opt_str(item.get("dtmf")),
            )
        )
    return commands


def _settings(raw: Any) -> FlowSettings:
    if not isinstance(raw, dict):
        raise FlowLoadError("'settings' muss ein Mapping sein")
    defaults = FlowSettings()
    return FlowSettings(
        max_attempts=int(raw.get("max_attempts", defaults.max_attempts)),
        timeout_s=float(raw.get("timeout_s", defaults.timeout_s)),
        barge_in=bool(raw.get("barge_in", defaults.barge_in)),
        min_confidence=float(raw.get("min_confidence", defaults.min_confidence)),
        escalation_node=_opt_str(raw.get("escalation_node")),
    )


def _key(value: Any) -> str:
    """Schluessel eines Uebergangs oder einer Option als Text.

    YAML 1.1 liest ``yes``/``no``/``on``/``off`` als Wahrheitswerte -- ohne diese
    Umsetzung wuerde aus ``transitions: {yes: ...}`` der Schluessel ``True``,
    und der Baum liefe genau an der Ja/Nein-Frage ins Leere.
    """
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)
