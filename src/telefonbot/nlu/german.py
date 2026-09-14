"""Deutschsprachige Parser fuer Telefonantworten.

Am Telefon kommt aus der Spracherkennung selten sauberes Deutsch ("vierzehnter
dritter", "halb drei", "ja genau, richtig"). Diese Funktionen bilden solche
Aeusserungen auf Werte ab. Alles ist reine Standardbibliothek und damit ohne
Modelle testbar.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata

# ------------------------------------------------------------- Normalisierung

_UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def normalize(text: str) -> str:
    """Kleinschreibung, Umlaute ausgeschrieben, Satzzeichen weg, Leerraum normiert."""
    text = unicodedata.normalize("NFC", text or "").lower()
    for src, dst in _UMLAUTS.items():
        text = text.replace(src, dst)
    text = re.sub(r"[^\w\s:.,-]", " ", text)
    # Punkt/Komma/Doppelpunkt nur zwischen Ziffern behalten ("14.3.", "2,5", "9:30"),
    # als Satzzeichen dagegen entfernen.
    text = re.sub(r"(?<!\d)[.,:]|[.,:](?!\d)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list[str]:
    """Wortliste der normalisierten Eingabe."""
    return [t for t in re.split(r"[\s,.:-]+", normalize(text)) if t]


# --------------------------------------------------------------------- Ja/Nein

_YES = {
    "ja", "jo", "jep", "jup", "joa", "jawohl", "klar", "genau", "richtig", "korrekt",
    "stimmt", "passt", "gerne", "bitte", "okay", "ok", "sicher", "absolut", "exakt",
    "positiv", "einverstanden", "yes",
}
_NO = {
    "nein", "ne", "nee", "noe", "nicht", "falsch", "negativ", "quatsch", "keinesfalls",
    "niemals", "no",
}
_NEGATORS = {"nicht", "kein", "keine", "keinen", "nein", "ne", "nee", "noe"}


def parse_yes_no(text: str) -> bool | None:
    """``True``/``False``/``None`` (nicht verstanden).

    Negationen gewinnen: "stimmt nicht" ist Nein, nicht Ja.
    """
    words = tokens(text)
    if not words:
        return None
    has_negator = any(w in _NEGATORS for w in words)
    has_yes = any(w in _YES for w in words)
    has_no = any(w in _NO for w in words)
    if has_negator:
        return False
    if has_yes and not has_no:
        return True
    if has_no and not has_yes:
        return False
    return None


# ---------------------------------------------------------------------- Zahlen

_UNITS = {
    "null": 0, "eins": 1, "ein": 1, "eine": 1, "einen": 1, "zwei": 2, "zwo": 2, "drei": 3,
    "vier": 4, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
    "elf": 11, "zwoelf": 12, "dreizehn": 13, "vierzehn": 14, "fuenfzehn": 15,
    "sechzehn": 16, "siebzehn": 17, "achtzehn": 18, "neunzehn": 19,
}
_TENS = {
    "zwanzig": 20, "dreissig": 30, "vierzig": 40, "fuenfzig": 50,
    "sechzig": 60, "siebzig": 70, "achtzig": 80, "neunzig": 90,
}
_ORDINALS = {
    "erster": 1, "erste": 1, "ersten": 1, "zweiter": 2, "zweite": 2, "zweiten": 2,
    "dritter": 3, "dritte": 3, "dritten": 3, "vierter": 4, "vierte": 4, "vierten": 4,
    "fuenfter": 5, "fuenfte": 5, "fuenften": 5, "sechster": 6, "sechste": 6, "sechsten": 6,
    "siebter": 7, "siebte": 7, "siebten": 7, "siebenter": 7, "siebente": 7,
    "achter": 8, "achte": 8, "achten": 8, "neunter": 9, "neunte": 9, "neunten": 9,
    "zehnter": 10, "zehnte": 10, "zehnten": 10, "elfter": 11, "elfte": 11, "elften": 11,
    "zwoelfter": 12, "zwoelfte": 12, "zwoelften": 12,
}


def parse_number_word(word: str) -> int | None:
    """Ein deutsches Zahlwort bis 99 (auch "einundzwanzig") als ``int``."""
    word = normalize(word).replace(" ", "")
    if not word:
        return None
    if word.isdigit():
        return int(word)
    if word in _UNITS:
        return _UNITS[word]
    if word in _TENS:
        return _TENS[word]
    if word in _ORDINALS:
        return _ORDINALS[word]
    if "und" in word:
        unit_part, _, tens_part = word.partition("und")
        if unit_part in _UNITS and tens_part in _TENS:
            return _TENS[tens_part] + _UNITS[unit_part]
    if word.endswith("hundert"):
        prefix = word[: -len("hundert")]
        factor = _UNITS.get(prefix, 1) if prefix else 1
        return factor * 100
    return None


def parse_number(text: str) -> float | None:
    """Erste Zahl in der Aeusserung -- als Ziffern oder als Zahlwort."""
    norm = normalize(text)
    match = re.search(r"-?\d+(?:[.,]\d+)?", norm)
    if match:
        return float(match.group(0).replace(",", "."))
    for word in tokens(norm):
        value = parse_number_word(word)
        if value is not None:
            return float(value)
    return None


def parse_digits(text: str, *, length: int | None = None) -> str | None:
    """Ziffernfolge, z.B. Matrikelnummer ("eins zwei drei" oder "123").

    ``length`` erzwingt die erwartete Stellenzahl -- am Telefon der wichtigste
    Schutz gegen halb verstandene Nummern.
    """
    digits: list[str] = []
    for word in tokens(text):
        if word.isdigit():
            digits.append(word)
            continue
        value = parse_number_word(word)
        if value is None:
            continue
        digits.append(str(int(value)))
    joined = "".join(digits)
    if not joined:
        return None
    if length is not None and len(joined) != length:
        return None
    return joined


# ---------------------------------------------------------------------- Datum

_WEEKDAYS = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
    "freitag": 4, "samstag": 5, "sonnabend": 5, "sonntag": 6,
}
_MONTHS = {
    "januar": 1, "februar": 2, "maerz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}


def parse_date(text: str, *, today: dt.date | None = None) -> str | None:
    """Datum als ISO-String ``YYYY-MM-DD``.

    Versteht "heute", "morgen", "uebermorgen", Wochentage (naechstes Vorkommen),
    "14.3.", "14. Maerz", "vierzehnter dritter".
    """
    today = today or dt.date.today()
    norm = normalize(text)
    if not norm:
        return None

    if "uebermorgen" in norm:
        return (today + dt.timedelta(days=2)).isoformat()
    if "morgen" in norm:
        return (today + dt.timedelta(days=1)).isoformat()
    if "heute" in norm:
        return today.isoformat()

    iso = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", norm)
    if iso:
        return _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    numeric = re.search(r"\b(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\s*(\d{2,4})?", norm)
    if numeric:
        day, month = int(numeric.group(1)), int(numeric.group(2))
        year = _resolve_year(numeric.group(3), day, month, today)
        return _safe_date(year, month, day)

    for name, month in _MONTHS.items():
        if name in norm:
            day_match = re.search(r"\b(\d{1,2})\s*\.?\s*(?=" + name + r")", norm)
            day = int(day_match.group(1)) if day_match else _ordinal_before(norm, name)
            if day is None:
                continue
            year = _resolve_year(None, day, month, today)
            return _safe_date(year, month, day)

    ordinals = [parse_number_word(w) for w in tokens(norm) if w in _ORDINALS]
    if len(ordinals) >= 2 and ordinals[0] and ordinals[1]:
        year = _resolve_year(None, ordinals[0], ordinals[1], today)
        return _safe_date(year, ordinals[1], ordinals[0])

    for name, weekday in _WEEKDAYS.items():
        if name in norm:
            delta = (weekday - today.weekday()) % 7
            if delta == 0 or "naechste" in norm or "naechsten" in norm:
                delta += 7 if delta == 0 else 0
            return (today + dt.timedelta(days=delta)).isoformat()
    return None


def _ordinal_before(norm: str, month_name: str) -> int | None:
    prefix = norm.split(month_name)[0].strip()
    if not prefix:
        return None
    last = prefix.split()[-1]
    return parse_number_word(last)


def _resolve_year(raw: str | None, day: int, month: int, today: dt.date) -> int:
    """Jahr bestimmen: explizit, sonst das naechste Vorkommen des Datums."""
    if raw:
        year = int(raw)
        return year + 2000 if year < 100 else year
    candidate = _safe_date(today.year, month, day)
    if candidate and dt.date.fromisoformat(candidate) < today:
        return today.year + 1
    return today.year


def _safe_date(year: int, month: int, day: int) -> str | None:
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


# -------------------------------------------------------------------- Uhrzeit

_QUARTER = re.compile(r"(dreiviertel|viertel|halb)\s*(?:nach|vor)?\s*(\w+)")


def parse_time(text: str) -> str | None:
    """Uhrzeit als ``HH:MM``.

    Versteht "14:30", "14 uhr 30", "halb drei", "viertel nach drei",
    "dreiviertel vier" und beruecksichtigt "nachmittags"/"abends".
    """
    norm = normalize(text)
    if not norm:
        return None
    pm = any(w in norm for w in ("nachmittag", "nachmittags", "abend", "abends"))

    colon = re.search(r"\b(\d{1,2})[:.](\d{2})\b", norm)
    if colon:
        return _safe_time(int(colon.group(1)), int(colon.group(2)), pm)

    uhr = re.search(r"\b(\d{1,2})\s*uhr\s*(\d{1,2})?\b", norm)
    if uhr:
        minute = int(uhr.group(2)) if uhr.group(2) else 0
        return _safe_time(int(uhr.group(1)), minute, pm)

    word_uhr = re.search(r"\b(\w+)\s+uhr\b", norm)
    if word_uhr:
        hour = parse_number_word(word_uhr.group(1))
        if hour is not None:
            return _safe_time(hour, 0, pm)

    quarter = _QUARTER.search(norm)
    if quarter:
        kind, ref_word = quarter.group(1), quarter.group(2)
        ref = parse_number_word(ref_word)
        if ref is not None:
            if kind == "halb":
                return _safe_time(ref - 1, 30, pm)
            if kind == "dreiviertel":
                return _safe_time(ref - 1, 45, pm)
            if "vor" in norm:
                return _safe_time(ref - 1, 45, pm)
            return _safe_time(ref - 1, 15, pm) if "nach" not in norm else _safe_time(ref, 15, pm)
    return None


def _safe_time(hour: int, minute: int, pm: bool = False) -> str | None:
    if pm and hour < 12:
        hour += 12
    if hour == 24:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"
