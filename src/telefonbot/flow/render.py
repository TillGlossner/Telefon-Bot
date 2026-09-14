"""Platzhalter in Ansagetexten fuellen: ``"Termin am {datum}"``.

Bewusst kein ``str.format`` und kein ``eval``: Texte kommen aus YAML, das
Fachabteilungen pflegen. Unbekannte Platzhalter werden zu leerem Text statt zu
einer Exception mitten im Telefonat -- die Validierung meldet sie vorher.
"""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")


def placeholders(text: str | None) -> set[str]:
    """Alle in ``text`` referenzierten Platzhalternamen."""
    if not text:
        return set()
    return {m.group(1) for m in _PLACEHOLDER.finditer(text)}


def render(text: str | None, context: dict[str, Any]) -> str:
    """Ersetzt ``{name}`` durch den Wert aus ``context`` (fehlend -> leer)."""
    if not text:
        return ""

    def _sub(match: re.Match[str]) -> str:
        value = context.get(match.group(1))
        return "" if value is None else str(value)

    return _PLACEHOLDER.sub(_sub, text).strip()


def render_args(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Rendert Platzhalter rekursiv in Aktions-Argumenten."""
    out: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            out[key] = render(value, context) if _PLACEHOLDER.search(value) else value
        elif isinstance(value, dict):
            out[key] = render_args(value, context)
        elif isinstance(value, list):
            out[key] = [
                render(v, context) if isinstance(v, str) and _PLACEHOLDER.search(v) else v
                for v in value
            ]
        else:
            out[key] = value
    return out
