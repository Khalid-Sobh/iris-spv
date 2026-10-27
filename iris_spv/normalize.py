"""Turn a raw source dict into a clean Record, or reject it with a reason.

Every function either returns a clean value or raises RecordRejected.
No hidden state, no clock access (the caller passes `now`) -> deterministic.
"""
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timezone

from iris_spv.models import Identity, Record, RecordRejected

# ---------- small helpers ----------------------------------------------------

def fold(text: str) -> str:
    """Casefold + transliterate umlauts + drop punctuation: 'Müller-Park' -> 'mueller park'."""
    text = text.casefold()
    for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def clean(text) -> str:
    """Collapse whitespace; None -> ''."""
    return " ".join(str(text or "").split())


# ---------- individual fields --------------------------------------------------

def normalize_court(raw) -> str:
    """'AG münchen' / 'Amtsgericht München' / 'München' -> 'Amtsgericht München'."""
    s = clean(raw)
    if not s:
        raise RecordRejected("missing_court")
    low = s.casefold()
    if low.startswith("amtsgericht "):
        s = s[len("amtsgericht "):]
    elif low.startswith("ag "):
        s = s[3:]
    return f"Amtsgericht {s}"


# 'HRB 12345', 'HRB12345 B' (Berlin-style suffix), leading zeros dropped.
_REGISTER_RE = re.compile(r"^(HRA|HRB)\s*0*(\d+)\s*([A-Z]{1,2})?$", re.I)
_OTHER_REGISTERS = re.compile(r"^(VR|GnR|PR|GsR)\b", re.I)  # associations, co-ops...


def parse_register(raw) -> tuple[str, str, str]:
    """'hrb 0267890 b' -> ('HRB', '267890', 'B')."""
    s = clean(raw)
    if not s:
        raise RecordRejected("missing_register_number")
    m = _REGISTER_RE.match(s)
    if not m:
        if _OTHER_REGISTERS.match(s):
            raise RecordRejected("unsupported_register_type", s)
        raise RecordRejected("bad_register_number", s)
    return m.group(1).upper(), m.group(2), (m.group(3) or "").upper()


# Longest patterns first, so 'GmbH & Co. KG' is not mistaken for plain 'KG'.
_LEGAL_FORMS = [
    ("GmbH & Co. KG", r"gmbh\s*&\s*co\.?\s*kg"),
    ("UG (haftungsbeschraenkt)", r"ug\s*\(haftungsbeschr[aä]nkt\)"),
    ("GmbH", r"gmbh"),
    ("AG", r"ag"),
    ("KG", r"kg"),
    ("SE", r"se"),
]


def split_legal_form(name: str) -> tuple[str, str]:
    """'Solarpark Foo GmbH & Co. KG' -> ('Solarpark Foo', 'GmbH & Co. KG')."""
    for label, pattern in _LEGAL_FORMS:
        m = re.search(rf"\s+{pattern}\.?$", name, re.I)
        if m:
            return name[: m.start()].strip(), label
    return name, ""


def parse_date(raw, field_name: str) -> date:
    """Accept ISO (2026-09-14) or German (14.09.2026); anything else is rejected."""
    s = clean(raw)
    if not s:
        raise RecordRejected(f"missing_{field_name}")
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise RecordRejected(f"bad_{field_name}", s)


def parse_capital(raw) -> float | None:
    """'25.000,00 EUR' -> 25000.0 ; empty -> None."""
    s = clean(raw).upper().replace("EUR", "").replace("€", "").strip()
    if not s:
        return None
    if "," in s:                       # German format: dot = thousands, comma = decimals
        s = s.replace(".", "").replace(",", ".")
    try:
        value = float(s)
    except ValueError:
        raise RecordRejected("bad_capital", clean(raw))
    if value < 0:
        raise RecordRejected("bad_capital", clean(raw))
    return value


# Only formations are of interest for this radar.
_FORMATION_EVENTS = {"neueintragung", "ersteintragung", "neugruendung", "formation"}


def parse_event(raw) -> str:
    s = fold(clean(raw))
    if not s:
        raise RecordRejected("missing_event")
    if s not in _FORMATION_EVENTS:
        raise RecordRejected("not_formation_event", clean(raw))
    return "FORMATION"


# ---------- putting it together -----------------------------------------------

def identity_fields(raw: dict) -> Identity:
    """Identity only (name + register). Reference sources use just this part."""
    name = clean(raw.get("name"))
    if not name:
        raise RecordRejected("missing_name")
    court = normalize_court(raw.get("court"))
    reg_type, number, suffix = parse_register(raw.get("register"))
    base_name, legal_form = split_legal_form(name)
    # The stable ID is the register tuple, NEVER the name.
    record_id = f"{fold(court)}|{reg_type}|{number}{suffix}"
    return Identity(
        record_id=record_id,
        company_name=name,
        company_name_norm=fold(base_name),
        legal_form=legal_form,
        register_court=court,
        register_type=reg_type,
        register_number=number,
        register_suffix=suffix,
    )


def normalize(raw: dict, source: str, run_id: str, now: datetime | None = None) -> Record:
    """Full normalization of one raw record. Raises RecordRejected on any problem."""
    if "_malformed_line" in raw:  # FileSource flags lines that are not valid JSON
        raise RecordRejected("malformed_json", f"line {raw['_malformed_line']}")

    now = now or datetime.now(timezone.utc)
    ident = identity_fields(raw)
    event = parse_event(raw.get("event"))
    formation_date = parse_date(raw.get("event_date"), "event_date")
    source_date = parse_date(raw.get("published"), "source_date")
    if formation_date > now.date():
        raise RecordRejected("future_event_date", formation_date.isoformat())

    capital = parse_capital(raw.get("capital"))
    activity = clean(raw.get("object"))

    # Hash only the business fields (not run_id / timestamps), so re-running
    # the same data produces the same hash -> "unchanged".
    hash_input = "|".join([
        ident.record_id, ident.company_name, event, formation_date.isoformat(),
        str(capital), activity,
    ])
    return Record(
        identity=ident,
        source=source,
        source_url=clean(raw.get("source_url")),
        source_date=source_date.isoformat(),
        retrieved_at=now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        run_id=run_id,
        formation_event=event,
        formation_date=formation_date.isoformat(),
        share_capital_eur=capital,
        activity_text=activity,
        content_hash=hashlib.sha256(hash_input.encode()).hexdigest(),
        raw_payload=json.dumps(raw, ensure_ascii=False, sort_keys=True),
    )
