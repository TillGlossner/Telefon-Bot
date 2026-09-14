"""Datenmodell eines Entscheidungsbaums (Flow).

Der Baum ist bewusst *deterministisch* und datengetrieben: Fachabteilungen
pflegen YAML, nicht Python. Sprachverstehen (NLU) und Sprachsynthese sind
ausserhalb dieses Moduls; hier geht es nur um Struktur und Uebergaenge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeKind(str, Enum):
    """Knotentypen des Entscheidungsbaums."""

    SAY = "say"
    ASK = "ask"
    CONFIRM = "confirm"
    BRANCH = "branch"
    ACTION = "action"
    TRANSFER = "transfer"
    HANGUP = "hangup"


class ExpectKind(str, Enum):
    """Erwartete Antwortform an einem ``ask``-Knoten."""

    YES_NO = "yes_no"
    CHOICE = "choice"
    NUMBER = "number"
    DIGITS = "digits"
    DATE = "date"
    TIME = "time"
    TEXT = "text"


@dataclass(frozen=True)
class ExpectSpec:
    """Beschreibt, was an einem Knoten erwartet wird und wie es abgebildet wird.

    ``options`` bildet einen Zielwert auf seine Synonyme ab
    (``{"termin": ["termin", "sprechstunde"]}``); ``dtmf`` bildet Tastendruck
    auf denselben Zielwert ab (``{"1": "termin"}``).
    """

    kind: ExpectKind = ExpectKind.TEXT
    options: dict[str, list[str]] = field(default_factory=dict)
    dtmf: dict[str, str] = field(default_factory=dict)
    min_value: float | None = None
    max_value: float | None = None
    length: int | None = None
    fuzzy: bool = True

    @property
    def values(self) -> list[str]:
        """Zulaessige Zielwerte (nur bei ``choice``/``yes_no`` sinnvoll)."""
        if self.kind is ExpectKind.YES_NO:
            return ["yes", "no"]
        return list(self.options)


@dataclass(frozen=True)
class Condition:
    """Einzelbedingung eines ``branch``-Knotens: ``slot op value``."""

    slot: str
    op: str = "eq"
    value: Any = None

    OPS = ("eq", "ne", "lt", "lte", "gt", "gte", "in", "contains", "set", "unset")

    def evaluate(self, slots: dict[str, Any]) -> bool:
        actual = slots.get(self.slot)
        if self.op == "set":
            return actual is not None
        if self.op == "unset":
            return actual is None
        if actual is None:
            return False
        try:
            if self.op == "eq":
                return _coerce_eq(actual, self.value)
            if self.op == "ne":
                return not _coerce_eq(actual, self.value)
            if self.op == "lt":
                return float(actual) < float(self.value)
            if self.op == "lte":
                return float(actual) <= float(self.value)
            if self.op == "gt":
                return float(actual) > float(self.value)
            if self.op == "gte":
                return float(actual) >= float(self.value)
            if self.op == "in":
                return actual in (self.value or [])
            if self.op == "contains":
                return str(self.value).lower() in str(actual).lower()
        except (TypeError, ValueError):
            return False
        raise ValueError(f"Unbekannter Operator: {self.op}")


def _coerce_eq(actual: Any, expected: Any) -> bool:
    """Gleichheit mit sanfter Typangleichung (YAML liefert oft str statt int)."""
    if actual == expected:
        return True
    if isinstance(actual, bool) or isinstance(expected, bool):
        return False
    try:
        return float(actual) == float(expected)
    except (TypeError, ValueError):
        return str(actual).strip().lower() == str(expected).strip().lower()


@dataclass(frozen=True)
class Case:
    """Ein Zweig eines ``branch``-Knotens; alle Bedingungen sind UND-verknuepft."""

    when: list[Condition]
    next: str

    def matches(self, slots: dict[str, Any]) -> bool:
        return all(cond.evaluate(slots) for cond in self.when)


@dataclass(frozen=True)
class Node:
    """Ein Knoten des Entscheidungsbaums."""

    id: str
    kind: NodeKind
    text: str | None = None
    reprompt: str | None = None
    no_input_text: str | None = None
    slot: str | None = None
    expect: ExpectSpec | None = None
    transitions: dict[str, str] = field(default_factory=dict)
    cases: list[Case] = field(default_factory=list)
    action: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    assign: str | None = None
    target: str | None = None
    reason: str | None = None
    next: str | None = None
    on_yes: str | None = None
    on_no: str | None = None
    on_no_match: str | None = None
    on_no_input: str | None = None
    on_error: str | None = None
    max_attempts: int | None = None
    timeout_s: float | None = None
    barge_in: bool | None = None
    tags: list[str] = field(default_factory=list)

    def successors(self) -> list[str]:
        """Alle statisch referenzierten Folgeknoten (fuer Validierung/Graph)."""
        out: list[str] = []
        for value in (
            self.next,
            self.on_yes,
            self.on_no,
            self.on_no_match,
            self.on_no_input,
            self.on_error,
        ):
            if value:
                out.append(value)
        out.extend(self.transitions.values())
        out.extend(case.next for case in self.cases)
        return out


@dataclass(frozen=True)
class SlotSpec:
    """Deklaration eines Slots (Gespraechsvariable)."""

    name: str
    kind: ExpectKind = ExpectKind.TEXT
    description: str = ""
    sensitive: bool = False
    """``sensitive`` steuert die Redaktion in Transkripten/Logs (DSGVO)."""


@dataclass(frozen=True)
class GlobalCommand:
    """Ueberall gueltiges Sprachkommando ("Mitarbeiter", "wiederholen", "Notfall")."""

    name: str
    phrases: list[str]
    action: str  # "goto" | "repeat" | "back"
    target: str | None = None
    dtmf: str | None = None


@dataclass(frozen=True)
class FlowSettings:
    """Vorgaben fuer das Gespraechsverhalten; pro Knoten ueberschreibbar."""

    max_attempts: int = 2
    timeout_s: float = 6.0
    barge_in: bool = True
    min_confidence: float = 0.45
    """ASR-Hypothesen unterhalb dieser Konfidenz gelten als 'nicht verstanden'."""
    escalation_node: str | None = None
    """Zielknoten, wenn wiederholtes Nichtverstehen eskaliert werden muss."""


@dataclass(frozen=True)
class Flow:
    """Ein vollstaendiger, validierter Entscheidungsbaum."""

    id: str
    start: str
    nodes: dict[str, Node]
    version: int = 1
    locale: str = "de-DE"
    description: str = ""
    slots: dict[str, SlotSpec] = field(default_factory=dict)
    global_commands: list[GlobalCommand] = field(default_factory=list)
    settings: FlowSettings = field(default_factory=FlowSettings)

    def node(self, node_id: str) -> Node:
        try:
            return self.nodes[node_id]
        except KeyError:
            raise KeyError(f"Knoten '{node_id}' existiert nicht in Flow '{self.id}'") from None
